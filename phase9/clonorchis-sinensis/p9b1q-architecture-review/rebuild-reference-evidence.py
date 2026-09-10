#!/usr/bin/env python3
"""Deterministically rebuild the review-only P9-B1Q architecture evidence chain."""

from __future__ import annotations

import copy
import base64
import graphlib
import hashlib
import io
import json
import os
import stat
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIX = HERE / "fixtures"


def cbytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def csha(value: Any) -> str:
    return sha_bytes(cbytes(value))


def load(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def write(name: str, value: Any) -> None:
    (FIX / name).write_bytes(cbytes(value))


def raw_sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def resolve(relative: str) -> Path:
    local = HERE / relative
    return local if local.exists() else REPO / relative


def apply_remove(value: dict[str, Any], pointer: str) -> dict[str, Any]:
    result = copy.deepcopy(value)
    tokens = pointer.lstrip("/").split("/")
    parent: Any = result
    for token in tokens[:-1]:
        parent = parent[int(token)] if isinstance(parent, list) else parent[token]
    parent.pop(int(tokens[-1]) if isinstance(parent, list) else tokens[-1])
    return result


def pointer_get(value: Any, pointer: str) -> Any:
    current = value
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


SEMANTIC_COLLECTIONS = (
    "resolved_mentions", "resolved_events", "resolved_relations", "semantic_roles",
    "narrative_intents", "forbidden_relations", "resolved_references", "resolved_overrides",
)


def semantic_set(core: dict[str, Any], *, fields=None) -> dict[str, Any]:
    # This literal is a conformance guard, not a caller-configurable identity domain.
    frozen = ("resolved_mentions", "resolved_events", "resolved_relations", "semantic_roles",
              "narrative_intents", "forbidden_relations", "resolved_references", "resolved_overrides")
    selected = SEMANTIC_COLLECTIONS if fields is None else tuple(fields)
    if tuple(SEMANTIC_COLLECTIONS) != frozen or selected != frozen:
        raise ValueError("SEMANTIC_IDENTITY_DEFINITION_DRIFT")
    if any(k not in core or not isinstance(core[k], list) for k in frozen):
        raise ValueError("MISSING_OR_INVALID_SEMANTIC_COLLECTION")
    return {k: core[k] for k in frozen}


def refresh_core(core: dict[str, Any]) -> None:
    core["semantic_object_set_sha256"] = csha(semantic_set(core))
    core["solution_id"] = f"SOL-{core['semantic_object_set_sha256'][:24]}"


class GlobalSourceCorrection:
    """Evaluate the sealed CONTROL catalog; never select sources by hash equality.

    The catalog supplies structural (file, pointer, resolver, source, mode) rules,
    not replacement values. Its observed/expected-value columns are not evaluated.
    The two committed authorizations are the only changes to that design input.
    Planning runs N9 in a separate complete tree; narrow_refresh alone writes.
    """

    REVIEW = "phase9/clonorchis-sinensis/p9b1q-architecture-review/"
    AUTH = "phase9/clonorchis-sinensis/p9b1q/"
    TYPED_RESULT = REVIEW + "fixtures/typed-result-exposure-positive.json"
    SUMMARY = REVIEW + "fixtures/reference-validator-execution-summary.json"
    EXECUTION = "EXECUTION#N9_FRESH_ACCEPTED_STDOUT"
    DESIGN_SHA = "9571669f9b2b711e1b855e3e92eca936a219c3b07d8744e9b526e5c6ce5694eb"
    ARCHIVE_SHA = "e42aa5fa9184694ad92be90ab22a56da463a6f49ead87ecab8e2c6dd5be43c2c"
    MANIFEST_SHA = "841007859bd10c09f379a1ea710a9b7bb6eb3f835e4a6377cd65312d6fafee3a"
    LOCK_SHA = "67c9fc1f782b526774d63022a41ab6f35dcee0b146f666dccf6b350e5009d09a"
    PRESERVED = {
        "/solver_trace_sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        "/solver/configuration_sha256": "7750ae58d7c89215809df97ce008e9bd9638447b9b91127e456e67b5d7de1c00",
    }
    AUTH_IDENTITIES = {
        AUTH + "p9b2-c5-d5-global-source-resolver-u1-u3-preservation-n9-correction-authorization.yml":
            "fc81d818eac44af04cd8b4ff0da149c692fad75532572f78b0fd44fe5229d18c",
        AUTH + "p9b2-c5-d5-s2-actual-reference-hash-domain-correction-authorization.yml":
            "443aee183f68e7c6a929a6ee8252ea7e3288c588d72b4561a17d494fdac17634",
    }
    PACKAGES = {"ajv": "8.17.1", "fast-deep-equal": "3.1.3", "fast-uri": "3.1.5",
                "json-schema-traverse": "1.0.0", "require-from-string": "2.0.2", "yaml": "2.8.1"}

    @staticmethod
    def read_object(name, raw):
        return json.loads(raw) if name.endswith(".json") else yaml.safe_load(raw)

    @staticmethod
    def at(obj, pointer):
        if pointer == "":
            return obj
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ValueError("INVALID_CATALOG_POINTER")
        return pointer_get(obj, pointer)

    @classmethod
    def assign(cls, obj, pointer, value):
        parent, _, leaf = pointer.rpartition("/")
        record = cls.at(obj, parent)
        leaf = leaf.replace("~1", "/").replace("~0", "~")
        key = int(leaf) if isinstance(record, list) else leaf
        record[key]  # Existing fields only, including scalar type preservation.
        if type(record[key]) is not type(value):
            raise ValueError("CATALOG_TARGET_TYPE_DRIFT: " + pointer)
        record[key] = copy.deepcopy(value)

    @staticmethod
    def ordered(dependencies):
        if any(not isinstance(v, list) or len(v) != len(set(v)) for v in dependencies.values()):
            raise ValueError("DUPLICATE_DAG_EDGE")
        if any(source not in dependencies for values in dependencies.values() for source in values):
            raise ValueError("MISSING_DAG_PREDECESSOR")
        try:
            sorter = graphlib.TopologicalSorter(dependencies)
            sorter.prepare()
            result = []
            while sorter.is_active():
                ready = sorted(sorter.get_ready())
                result.extend(ready)
                sorter.done(*ready)
            return result
        except graphlib.CycleError as exc:
            raise ValueError("CYCLIC_SOURCE_DEPENDENCY") from exc

    def __init__(self, frozen_bytes, *, design_archive, offline_archive, workspace):
        self.base = dict(frozen_bytes)
        self.workspace = Path(workspace).resolve(strict=True)
        if self.workspace.is_relative_to(REPO.resolve()):
            raise ValueError("N9_WORKSPACE_INSIDE_AUTHORITATIVE_REPOSITORY")
        self.offline_archive = Path(offline_archive).resolve(strict=True)
        raw = Path(design_archive).read_bytes()
        if sha_bytes(raw) != self.DESIGN_SHA:
            raise ValueError("ACCEPTED_DESIGN_IDENTITY_MISMATCH")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            catalog = json.loads(archive.read("field-catalog.json"))
            self.dependencies = json.loads(archive.read("field-level-dag.json"))["dependencies"]
            inventory = json.loads(archive.read("input-byte-inventory.json"))["files"]
            policy = json.loads(archive.read("future-refresh-policy.json"))
            historical = json.loads(archive.read("historical-bindings.json"))
        identities = {r["path"]: r["sha256"] for r in inventory} | self.AUTH_IDENTITIES
        if len(identities) != 308 or set(self.base) != set(identities):
            raise ValueError("INCOMPLETE_AUTHORIZED_BASE_INVENTORY")
        for name, digest in identities.items():
            if sha_bytes(self.base[name]) != digest:
                raise ValueError("FROZEN_BASE_IDENTITY_MISMATCH: " + name)
        self.rows = {}
        for row in catalog:
            key = row["file"] + "#" + row["pointer"]
            if key in self.rows:
                raise ValueError("DUPLICATE_CATALOG_TARGET")
            self.rows[key] = row
        self.policy_keys = {r["file"] + "#" + r["pointer"] for r in policy["fields"]}
        if len(self.policy_keys) != len(policy["fields"]):
            raise ValueError("DUPLICATE_POLICY_TARGET")
        self.field_policy = {}
        for key in sorted(self.policy_keys):
            r = self.rows[key]
            if not r.get("future_write") or not r.get("mode"):
                raise ValueError("NONWRITABLE_CATALOG_TARGET")
            self.field_policy.setdefault(r["file"], []).append(r["pointer"])
        for pointers in self.field_policy.values():
            for i, pointer in enumerate(pointers):
                if any(other.startswith(pointer + "/") for other in pointers[i+1:]):
                    raise ValueError("OVERLAPPING_POLICY_TARGET")
        if any(row["file"] in self.field_policy for row in historical):
            raise ValueError("HISTORICAL_SNAPSHOT_CAPTURED")
        self.s2_keys = set()
        source = self.REVIEW + "fixtures/diagnostic-predicate-argument-binding-positive.json"
        complete_source_edges = [key for key, row in self.rows.items()
                                 if row["file"] == source and row.get("mode")]
        for suffix in ("positive", "diagnostic-role-catalog-positive"):
            target = self.REVIEW + "fixtures/stage-validation-s2-" + suffix + ".json"
            for leaf, mode in (("canonical_sha256", "RAW"), ("byte_length", "LEN")):
                key = target + "#/actual_input_objects/7/" + leaf
                row = self.rows[key]
                if row.get("source") != source or key not in self.policy_keys:
                    raise ValueError("S2_CORRECTION_SCOPE_DRIFT")
                row.update(source_pointer="", mode=mode, resolver_id="R06")
                self.dependencies[key] = ["FROZEN_INPUT:" + source + "#"] + complete_source_edges
                self.s2_keys.add(key)
        self.dependencies.setdefault("FROZEN_INPUT:" + source + "#", [])
        self.order = self.ordered(self.dependencies)
        self.positions = {key: i for i, key in enumerate(self.order)}
        if not set(self.rows).issuperset(self.policy_keys):
            raise ValueError("UNKNOWN_POLICY_TARGET")
        self.file_edges = sorted({(node.split("#")[0], dep.removeprefix("FROZEN_INPUT:").split("#")[0])
                                  for node, deps in self.dependencies.items()
                                  for dep in deps if not node.startswith(("FROZEN_INPUT:", "EXECUTION#"))
                                  and node.split("#")[0] != dep.removeprefix("FROZEN_INPUT:").split("#")[0]})
        self.bytes = dict(self.base)
        self.objects = {}
        self.completed = set()
        self.fresh_summary = None
        self.proof = {"policy_field_count": len(self.policy_keys), "policy_file_count": len(self.field_policy),
                      "s2_r06_target_count": 4, "s2_r07_target_count": 0,
                      "field_dag_sha256": csha(self.dependencies), "file_edges_sha256": csha(self.file_edges),
                      "topological_order_sha256": csha(self.order)}
        self.proof["historical_binding_count"] = sum(row["binding_count"] for row in historical)
        self.proof["historical_writable_count"] = 0
        self._rule_fields = ("file", "pointer", "source", "source_pointer", "mode", "resolver_id", "classification", "future_write")
        self._rule_contract = {key: tuple(row.get(field) for field in self._rule_fields)
                               for key, row in self.rows.items()}
        self._policy_identity = csha(self.field_policy)
        self.preservation(self.base)

    def preservation(self, snapshot):
        typed = self.read_object(self.TYPED_RESULT, snapshot[self.TYPED_RESULT])
        for pointer, literal in self.PRESERVED.items():
            if self.at(typed, pointer) != literal:
                raise ValueError("OPAQUE_PRESERVATION_FAIL_CLOSED_NO_REPAIR: " + pointer)
        for suffix, selector in (("positive", "/bindings/exposure"),
                                 ("diagnostic-role-catalog-positive", "/bindings/diagnostic-role-catalog")):
            name = self.REVIEW + "fixtures/stage-validation-s2-" + suffix + ".json"
            obj = self.read_object(name, snapshot[name])
            if self.at(obj, "/actual_input_objects/7/content_json_pointer") != selector:
                raise ValueError("S2_EXTRACTION_SELECTOR_CHANGED")

    @classmethod
    def scalar_patch(cls, name, original, updates):
        """Patch PyYAML source spans in Unicode text; encode once after validation."""
        text = original.decode("utf-8")
        root = yaml.compose(text)
        spans = {}
        seen = set()

        def visit(node, pointer):
            if id(node) in seen:
                raise ValueError("UNSAFE_YAML_ALIAS")
            seen.add(id(node))
            if isinstance(node, yaml.ScalarNode):
                spans[pointer] = node
            elif isinstance(node, yaml.SequenceNode):
                for i, child in enumerate(node.value):
                    visit(child, pointer + "/" + str(i))
            elif isinstance(node, yaml.MappingNode):
                keys = set()
                for key, child in node.value:
                    if not isinstance(key, yaml.ScalarNode) or key.value in keys:
                        raise ValueError("UNSAFE_YAML_DUPLICATE_OR_COMPLEX_KEY")
                    keys.add(key.value)
                    visit(child, pointer + "/" + key.value.replace("~", "~0").replace("/", "~1"))
        visit(root, "")
        before = yaml.safe_load(text)
        after = copy.deepcopy(before)
        replacements = []
        for pointer, value in updates.items():
            cls.assign(after, pointer, value)
            node = spans.get(pointer)
            if node is None or node.style in ("|", ">"):
                raise ValueError("UNSAFE_YAML_NONSIMPLE_SCALAR")
            if isinstance(value, str):
                if node.style == "'":
                    token = "'" + value.replace("'", "''") + "'"
                elif node.style == '"':
                    token = json.dumps(value, ensure_ascii=False)
                elif yaml.safe_load(value) == value and "\n" not in value:
                    token = value
                else:
                    raise ValueError("UNSAFE_YAML_SCALAR_STYLE_CHANGE")
            elif type(value) is int:
                token = str(value)
            else:
                raise ValueError("UNSAFE_YAML_TARGET_TYPE")
            replacements.append((node.start_mark.index, node.end_mark.index, token))
        previous = len(text) + 1
        for start, end, token in sorted(replacements, reverse=True):
            if end > previous:
                raise ValueError("OVERLAPPING_YAML_SPAN")
            text = text[:start] + token + text[end:]
            previous = start
        if yaml.safe_load(text) != after:
            raise ValueError("UNRELATED_YAML_PARSED_MUTATION")
        return text.encode("utf-8")

    def object(self, name):
        if name not in self.base:
            raise ValueError("MISSING_STRUCTURAL_SOURCE: " + name)
        if name not in self.objects:
            self.objects[name] = self.read_object(name, self.bytes[name])
        return self.objects[name]

    def manifest_count(self, pointer):
        summary = self.fresh_summary
        owner = self.object(self.REVIEW + "design-manifest.yml")
        group, leaf = pointer.strip("/").split("/")
        if group == "inventory_counts":
            return len(owner[leaf])
        if summary is None:
            raise ValueError("MANIFEST_COUNT_BEFORE_N9")
        if group == "executable_evidence":
            if leaf == "repeat_runs":
                return summary[leaf]
            if leaf == "integrated_r3b_positive_cases":
                return sum(row["case"].startswith("POS-R3B-") for row in summary["positive"])
            return len(summary[leaf.removesuffix("_cases")])
        if group == "schema_gate":
            return summary[group][{"positive_fixture_pair_count": "fixture_pair_count"}.get(leaf, leaf)]
        if group == "failure_code_governance" and leaf not in ("formal_fixture_count", "explicit_fixture_failure_code_count"):
            return summary["registry_failure_governance"][leaf]
        counts = {key: len(self.object(self.REVIEW + "fixtures/" + filename)["cases"])
                  for key, filename in (("stage_fixture_count", "stage-validator-negative-fixtures.yml"),
                                        ("r3a_fixture_count", "r3a-reference-override-negative-fixtures.yml"),
                                        ("r3b_fixture_count", "r3b-negation-scope-negative-fixtures.yml"))}
        if leaf in ("total_fixture_count", "formal_fixture_count", "explicit_fixture_failure_code_count"):
            return sum(counts.values())
        return counts[leaf]

    def derive(self, key):
        row = self.rows[key]
        if tuple(row.get(field) for field in self._rule_fields) != self._rule_contract[key]:
            raise ValueError("STRUCTURAL_SOURCE_AUTHORITY_REPLACEMENT")
        mode, name, pointer = row.get("mode"), row["file"], row["pointer"]
        if mode == "N9_ACCEPTED_EXECUTION_OUTPUT":
            if self.fresh_summary is None or self.EXECUTION not in self.completed:
                raise ValueError("SUMMARY_BEFORE_FRESH_EXECUTION")
            return self.at(self.fresh_summary, pointer)
        if mode == "MANIFEST_COUNT":
            return self.manifest_count(pointer)
        source, sp = row["source"], row.get("source_pointer", "")
        if source not in self.bytes:
            raise ValueError("MISSING_STRUCTURAL_SOURCE: " + source)
        raw = self.bytes[source]
        if key in self.s2_keys and cbytes(json.loads(raw)) != raw:
            raise ValueError("S2_NONCANONICAL_WHOLE_SOURCE")
        if mode == "RAW":
            return sha_bytes(raw)
        if mode == "LEN":
            return len(raw)
        selected = self.at(self.object(source), sp)
        if mode == "HASH":
            return csha(selected)
        if mode == "CLEN":
            return len(cbytes(selected))
        if mode == "COPY":
            return copy.deepcopy(selected)
        if mode == "SELF":
            candidate = copy.deepcopy(selected)
            del candidate[pointer.rsplit("/", 1)[1]]
            return csha(candidate)
        if mode == "SEMANTIC":
            return csha(semantic_set(selected))
        if mode == "SOL":
            return "SOL-" + selected[:24]
        if mode in ("PROBE_SEM", "PROBE_CORE", "R3A_PROBE"):
            candidate = copy.deepcopy(selected)
            if mode == "R3A_PROBE":
                probe = self.at(self.object(name), pointer.rsplit("/", 1)[0])
                operations = probe["operation"]
            else:
                probe = self.object(name)
                operations = probe["mutation"]
            for operation in operations:
                if set(operation) != {"op", "path"} or operation["op"] != "remove":
                    raise ValueError("INVALID_PERSISTED_REMOVAL")
                candidate = apply_remove(candidate, operation["path"])
            refresh_core(candidate)
            return csha(candidate) if mode == "PROBE_CORE" else csha(semantic_set(candidate))
        raise ValueError("UNSUPPORTED_AUTHORIZED_RESOLVER: " + str(mode))

    def update(self, key, value):
        row = self.rows[key]
        name, pointer = row["file"], row["pointer"]
        obj = self.object(name)
        if self.at(obj, pointer) == value:
            return
        if key not in self.policy_keys:
            raise ValueError("CORRECTION_REQUIRES_UNAUTHORIZED_POLICY_DELTA: " + key)
        self.assign(obj, pointer, value)
        before = self.read_object(name, self.base[name])
        restored = copy.deepcopy(obj)
        updates = {}
        for target in self.field_policy[name]:
            old, new = self.at(before, target), self.at(obj, target)
            if old != new:
                updates[target] = new
            self.assign(restored, target, old)
        if restored != before:
            raise ValueError("NONADMITTED_SEMANTIC_MUTATION")
        self.bytes[name] = (cbytes(obj) if name.endswith(".json") else
                            self.scalar_patch(name, self.base[name], updates)) if updates else self.base[name]

    def archives(self):
        raw = self.offline_archive.read_bytes()
        if len(raw) != 389120 or sha_bytes(raw) != self.ARCHIVE_SHA:
            raise ValueError("OFFLINE_WRAPPER_IDENTITY")
        lock_raw = self.base[self.REVIEW + "package-lock.json"]
        if sha_bytes(lock_raw) != self.LOCK_SHA:
            raise ValueError("FROZEN_LOCK_IDENTITY")
        lock = json.loads(lock_raw)["packages"]
        result = {}
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as wrapper:
            members = wrapper.getmembers()
            names = {name + "-" + version + ".tgz" for name, version in self.PACKAGES.items()} | {"manifest.json"}
            if len(members) != 7 or {m.name for m in members} != names or not all(m.isfile() for m in members):
                raise ValueError("OFFLINE_WRAPPER_MEMBERS")
            if sha_bytes(wrapper.extractfile("manifest.json").read()) != self.MANIFEST_SHA:
                raise ValueError("OFFLINE_MANIFEST_IDENTITY")
            for name, version in self.PACKAGES.items():
                filename = name + "-" + version + ".tgz"
                payload = wrapper.extractfile(filename).read()
                sri = "sha512-" + base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii")
                locked = lock["node_modules/" + name]
                if (locked["version"] != version or locked["integrity"] != sri or
                        locked["resolved"] != "https://registry.npmjs.org/" + name + "/-/" + filename):
                    raise ValueError("OFFLINE_ARCHIVE_SRI_OR_SOURCE")
                with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
                    files = archive.getmembers()
                    if len({m.name for m in files}) != len(files):
                        raise ValueError("OFFLINE_DUPLICATE_TAR_MEMBER")
                    for member in files:
                        parts = member.name.split("/")
                        if parts[0] != "package" or any(p in ("", ".", "..") for p in parts) or not member.isfile():
                            raise ValueError("OFFLINE_UNSAFE_TAR_MEMBER")
                    package = json.loads(archive.extractfile("package/package.json").read())
                    if (package["name"], package["version"]) != (name, version):
                        raise ValueError("OFFLINE_TAR_PACKAGE_IDENTITY")
                    result[name] = {m.name.removeprefix("package/"): archive.extractfile(m).read() for m in files}
        return result

    def check_semantics(self):
        if set(self.bytes) != set(self.base):
            raise ValueError("INCOMPLETE_OR_EXTRA_PROSPECTIVE_INVENTORY")
        self.preservation(self.bytes)
        for name in self.base:
            if name not in self.field_policy:
                if self.bytes[name] != self.base[name]:
                    raise ValueError("PROTECTED_PROSPECTIVE_BYTES_CHANGED")
                continue
            before = self.read_object(name, self.base[name])
            after = self.read_object(name, self.bytes[name])
            updates = {p: self.at(after, p) for p in self.field_policy[name]
                       if self.at(before, p) != self.at(after, p)}
            exact = (cbytes(after) if name.endswith(".json") else self.scalar_patch(name, self.base[name], updates)) if updates else self.base[name]
            for pointer in self.field_policy[name]:
                self.assign(after, pointer, self.at(before, pointer))
            if before != after:
                raise ValueError("SEMANTIC_PROJECTION_CHANGED")
            if exact != self.bytes[name]:
                raise ValueError("UNRELATED_PROSPECTIVE_BYTE_MUTATION")

    def verify_s2_identity(self, snapshot):
        for key in self.s2_keys:
            row = self.rows[key]
            source = snapshot[row["source"]]
            if cbytes(json.loads(source)) != source:
                raise ValueError("S2_NONCANONICAL_WHOLE_SOURCE")
            expected = len(source) if row["mode"] == "LEN" else sha_bytes(source)
            actual = self.at(json.loads(snapshot[row["file"]]), row["pointer"])
            if actual != expected:
                raise ValueError("S2_SUBOBJECT_OR_STALE_IDENTITY_FORBIDDEN")

    def check_n9_output(self, stdout, exit_code):
        if exit_code != 0:
            raise ValueError("N9_NONZERO_EXIT")
        summary = json.loads(stdout)
        if cbytes(summary) != stdout:
            raise ValueError("N9_NONCANONICAL_STDOUT")
        if summary["result"] != "PASS" or summary["repeat_runs"] != 3:
            raise ValueError("N9_NONPASS_OR_REPEAT_COUNT")
        for key, count in (("positive", 18), ("minimality", 8), ("negative", 84)):
            if len(summary[key]) != count or summary[key + "_pass_count"] != count:
                raise ValueError("N9_CASE_COUNT_MISMATCH")
            passed = sum(not row["errors"] for row in summary[key]) if key == "positive" else sum(row["passed"] is True for row in summary[key])
            if passed != count:
                raise ValueError("N9_CASE_PASS_ASSERTION_MISMATCH")
        gate = summary["schema_gate"]
        if (gate["result"] != "PASS" or gate["compiled_schema_count"] != 13 or
                gate["fixture_pair_count"] != 37 or gate["valid_fixture_count"] != 37):
            raise ValueError("N9_SCHEMA_COUNTS")
        if summary["registry_failure_governance"]["result"] != "PASS":
            raise ValueError("N9_FAILURE_CODE_GOVERNANCE")
        for field, name in (("executable_sha256", "reference-stage-semantic-validator.py"),
                            ("configuration_sha256", "stage-semantic-validator-contract.yml")):
            if summary[field] != sha_bytes(self.base[self.REVIEW + name]):
                raise ValueError("N9_FROZEN_EXECUTABLE_OR_CONFIGURATION")
        if (gate["runner_sha256"] != sha_bytes(self.base[self.REVIEW + "strict-schema-gate.mjs"])
                or gate["lockfile_sha256"] != self.LOCK_SHA):
            raise ValueError("N9_SCHEMA_RUNNER_IDENTITY")
        payload = {key: summary[key] for key in ("registry_failure_governance", "positive", "minimality", "negative",
                                               "positive_pass_count", "minimality_pass_count", "negative_pass_count")}
        if summary["run_payload_sha256"] != csha(payload):
            raise ValueError("N9_PAYLOAD_HASH_MISMATCH")
        return summary

    def execute_n9(self):
        if not set(self.dependencies[self.EXECUTION]) <= self.completed:
            raise ValueError("PREMATURE_N9_MISSING_PREDECESSOR")
        self.check_semantics()
        self.verify_s2_identity(self.bytes)
        for key in self.completed:
            if key in self.rows and self.rows[key].get("mode"):
                row = self.rows[key]
                obj = self.read_object(row["file"], self.bytes[row["file"]])
                if obj != self.object(row["file"]) or self.at(obj, row["pointer"]) != self.derive(key):
                    raise ValueError("STALE_OR_WRONG_N9_PREDECESSOR: " + key)
        packages = self.archives()  # Always verify raw bytes before preparation.
        node = shutil.which("node")
        if node is None:
            raise ValueError("OFFLINE_NODE_EXECUTABLE_UNAVAILABLE")
        env = {"PATH": str(Path(node).resolve().parent) + ":/usr/bin:/bin", "LANG": "C.UTF-8",
               "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
        with tempfile.TemporaryDirectory(prefix="d5-n9-", dir=self.workspace) as temporary:
            outside = Path(temporary)
            tree = outside / "predecessors"
            tree.mkdir()
            for name, raw in self.bytes.items():
                path = tree / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            dep_root = outside / "verified-dependencies"
            modules = dep_root / "node_modules"
            module_bytes = {}
            for package, files in packages.items():
                for relative, raw in files.items():
                    path = modules / package / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
                    module_bytes[path] = raw
            review = tree / self.REVIEW
            (review / "node_modules").symlink_to(modules, target_is_directory=True)
            probe = r'''const fs=require('fs'),path=require('path'),m=require('module');
const root=fs.realpathSync(process.argv[1]);const r=m.createRequire(path.join(root,'probe.cjs'));
for(const name of JSON.parse(process.argv[2])) {let p=fs.realpathSync(r.resolve(name));
if(!p.startsWith(root+path.sep))throw Error('MODULE_SHADOWING');r(name);}
for(const p of Object.keys(require.cache))if(!fs.realpathSync(p).startsWith(root+path.sep))throw Error('TRANSITIVE_SHADOWING');'''
            checked = subprocess.run([node, "-e", probe, str(dep_root), json.dumps(list(self.PACKAGES))],
                                     env=env, cwd=outside, capture_output=True)
            if checked.returncode:
                raise ValueError("OFFLINE_NODE_MODULE_ORIGIN: " + checked.stderr.decode(errors="replace"))

            identities = {}

            def seal():
                live_identities = {}
                inode_set = set()
                for base in (tree, modules):
                    for path in [base, *base.rglob("*")]:
                        info = path.lstat()
                        if path == review / "node_modules":
                            if not path.is_symlink() or path.resolve() != modules.resolve():
                                raise ValueError("N9_DEPENDENCY_LINK_DRIFT")
                        elif not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                            raise ValueError("N9_UNSEALED_OBJECT_KIND")
                        if stat.S_ISREG(info.st_mode):
                            identity = (info.st_dev, info.st_ino)
                            if info.st_nlink != 1 or identity in inode_set:
                                raise ValueError("N9_ALIASED_OBJECT")
                            inode_set.add(identity)
                        live_identities[str(path)] = (info.st_dev, info.st_ino, info.st_mode)
                if identities and live_identities != identities:
                    raise ValueError("N9_SEALED_OBJECT_OR_DIRECTORY_IDENTITY_DRIFT")
                identities.update(live_identities)
                actual = {p.relative_to(tree).as_posix(): p.read_bytes() for p in tree.rglob("*")
                          if p.is_file() and "node_modules" not in p.parts}
                if actual != self.bytes:
                    raise ValueError("N9_PREDECESSOR_TREE_DRIFT")
                if any(p.read_bytes() != raw for p, raw in module_bytes.items()):
                    raise ValueError("OFFLINE_DEPENDENCY_IDENTITY_DRIFT")
                actual_deps = {p for p in modules.rglob("*") if p.is_file()}
                if actual_deps != set(module_bytes):
                    raise ValueError("OFFLINE_DEPENDENCY_INVENTORY_DRIFT")
            seal()
            index_probe = "import runpy,sys; from pathlib import Path; m=runpy.run_path(sys.argv[1]); print(m['build_index'](Path(sys.argv[2])).index_sha256)"
            index_run = subprocess.run([sys.executable, "-I", "-B", "-c", index_probe,
                                        str(tree / "scripts/p9b1_local_retrieval.py"), str(tree)],
                                       cwd=outside, env=env, capture_output=True)
            index_name = self.REVIEW + "fixtures/retrieval-result-exposure-positive.json"
            if (index_run.returncode or index_run.stdout.decode().strip() != self.object(index_name)["index_sha256"]):
                raise ValueError("R19_SEALED_INDEX_RECOMPUTATION_FAILED")
            self.proof["r19_independent_index_verification"] = "PASS"
            # -I removes ambient cwd/user site. Add only the sealed validator's
            # sibling directory, then verify every imported file's origin.
            entry = r'''import sys,runpy
from pathlib import Path
script=Path(sys.argv[1]).resolve(); tree=Path(sys.argv[2]).resolve()
sys.argv=[str(script),'--mode','all'];sys.path.insert(0,str(script.parent))
def no_network(event,args):
    if event.startswith(('socket.','urllib.','http.client.')): raise RuntimeError('NETWORK_FORBIDDEN')
sys.addaudithook(no_network)
try:
    runpy.run_path(str(script),run_name='__main__')
finally:
    for module in tuple(sys.modules.values()):
        origin=getattr(module,'__file__',None)
        if origin and not origin.startswith('<'):
            path=Path(origin).resolve()
            if not (path.is_relative_to(Path(sys.base_prefix).resolve()) or path.is_relative_to(tree)):
                raise RuntimeError('PYTHON_IMPORT_SHADOWING: '+str(path))
'''
            completed = subprocess.run([sys.executable, "-I", "-B", "-c", entry,
                                        str(review / "reference-stage-semantic-validator.py"), str(tree)],
                                       cwd=outside, env=env, capture_output=True)
            seal()
            self.proof["n9_exit_code"] = completed.returncode
            self.proof["n9_stderr"] = completed.stderr.decode("utf-8", errors="replace")
            self.proof["n9_stdout_sha256"] = sha_bytes(completed.stdout)
            self.proof["n9_stdout"] = completed.stdout.decode("utf-8", errors="replace")
            self.fresh_summary = self.check_n9_output(completed.stdout, completed.returncode)
            self.proof["offline_dependency_count"] = len(packages)
            self.proof["n9_payload_sha256"] = self.fresh_summary["run_payload_sha256"]

    def plan(self):
        if self.completed:
            raise ValueError("GLOBAL_PLANNER_REUSE_FORBIDDEN")
        if (csha(self.field_policy) != self._policy_identity or set(self._rule_contract) != set(self.rows)
                or self.policy_keys != {name + "#" + p for name, values in self.field_policy.items() for p in values}
                or csha(self.dependencies) != self.proof["field_dag_sha256"]
                or csha(self.order) != self.proof["topological_order_sha256"]):
            raise ValueError("GLOBAL_POLICY_OR_TOPOLOGY_REPLACEMENT")
        for key in self.order:
            if not set(self.dependencies[key]) <= self.completed:
                raise ValueError("FORWARD_SOURCE_DEPENDENCY")
            if key == self.EXECUTION:
                self.execute_n9()
            elif key in self.rows and self.rows[key].get("mode"):
                self.update(key, self.derive(key))
            self.completed.add(key)
        self.check_semantics()
        self.proof["actual_changed_fields"] = sum(self.at(self.read_object(row["file"], self.base[row["file"]]), row["pointer"])
                                                   != self.at(self.object(row["file"]), row["pointer"])
                                                   for key, row in self.rows.items() if key in self.policy_keys)
        self.proof["actual_changed_files"] = sum(self.base[n] != self.bytes[n] for n in self.base)
        return dict(self.bytes)


def narrow_refresh(root: Path, *, frozen_bytes: dict[str, bytes],
                   field_policy: dict[str, list[str]], rules: list[dict[str, Any]],
                   prospective_bytes: dict[str, bytes] | None = None,
                   global_build: dict[str, Any] | None = None) -> list[str]:
    """Rebind explicit derived fields, validating the entire transaction before writes.

    frozen_bytes is the independently acquired, complete input snapshot supplied by
    CONTROL, never a candidate-owned hash summary. field_policy is prospective
    authorization, not inferred from existing hash values. Rules are ordered;
    forward dependencies and repeated targets are rejected. No legacy generation
    code is called. A caller can supply a prospective patch for independent checking.
    The same snapshot/policy/rules are reusable for an idempotent second execution.
    """
    supplied_root = Path(root)
    if supplied_root.is_symlink():
        raise ValueError("SYMLINK_REFRESH_ROOT")
    root = supplied_root.resolve(strict=True)

    directory_identities = {}

    def complete_snapshot():
        # Independently enumerate the disposable tree. Never infer this inventory
        # from the caller's snapshot or filter away unlisted protected objects.
        expected = set()
        for name in frozen_bytes:
            if (not isinstance(name, str) or not name or "\\" in name or ":" in name
                    or any(part in ("", ".", "..", ".git", "node_modules") for part in name.split("/"))):
                raise ValueError("UNSAFE_SNAPSHOT_PATH")
            normalized = Path(name).as_posix()
            if normalized != name or normalized in expected:
                raise ValueError("ALIASED_SNAPSHOT_PATH")
            expected.add(normalized)
        actual = set()
        identities = set()

        def visit(directory):
            info = directory.stat(follow_symlinks=False)
            identity = (info.st_dev, info.st_ino)
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("NON_DIRECTORY_REFRESH_COMPONENT")
            if directory in directory_identities:
                if directory_identities[directory] != identity:
                    raise ValueError("DIRECTORY_IDENTITY_CHANGED: " + str(directory))
            else:
                directory_identities[directory] = identity
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name in (".git", "node_modules"):
                        raise ValueError("NON_DISPOSABLE_REFRESH_ROOT")
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        raise ValueError("SYMLINK_SNAPSHOT_PATH")
                    if stat.S_ISDIR(info.st_mode):
                        visit(Path(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        name = Path(entry.path).relative_to(root).as_posix()
                        identity = (info.st_dev, info.st_ino)
                        if name in actual or identity in identities:
                            raise ValueError("ALIASED_ROOT_FILE")
                        actual.add(name)
                        identities.add(identity)
                    else:
                        raise ValueError("NON_REGULAR_SNAPSHOT_OBJECT")
        visit(root)
        if actual != expected:
            raise ValueError("INCOMPLETE_FROZEN_SNAPSHOT")

    complete_snapshot()

    global_plan = None
    if global_build is not None:
        if field_policy or rules or set(global_build) != {"design_archive", "offline_archive", "workspace"}:
            raise ValueError("GLOBAL_POLICY_CALLER_REPLACEMENT")
        builder = GlobalSourceCorrection(frozen_bytes, **global_build)
        global_plan = builder.plan()
        field_policy = builder.field_policy

    for name, pointers in field_policy.items():
        if name == GlobalSourceCorrection.TYPED_RESULT:
            for pointer in pointers:
                for protected in GlobalSourceCorrection.PRESERVED:
                    if (pointer == protected or pointer.startswith(protected + "/")
                            or protected.startswith(pointer + "/")):
                        raise ValueError("OPAQUE_PRESERVATION_NO_RECOMPUTATION")

    def path(name):
        if not isinstance(name, str) or not name or "\\" in name or ":" in name:
            raise ValueError("UNSAFE_REFRESH_PATH")
        parts = name.split("/")
        if any(x in ("", ".", "..") for x in parts):
            raise ValueError("UNSAFE_REFRESH_PATH")
        result = root.joinpath(*parts)
        if any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)):
            raise ValueError("SYMLINK_REFRESH_PATH")
        if not result.is_file() or not result.resolve().is_relative_to(root):
            raise ValueError("MISSING_REFRESH_OBJECT")
        return result

    def decode(name, raw):
        return json.loads(raw) if name.endswith(".json") else yaml.safe_load(raw)

    def encode(name, value):
        return cbytes(value) if name.endswith(".json") else yaml.safe_dump(
            value, allow_unicode=True, sort_keys=False).encode("utf-8")

    def tokens(pointer):
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ValueError("INVALID_REFRESH_POINTER")
        return [x.replace("~1", "/").replace("~0", "~") for x in pointer[1:].split("/")]

    def get(obj, pointer):
        if pointer == "":
            return obj
        for token in tokens(pointer):
            obj = obj[int(token)] if isinstance(obj, list) else obj[token]
        return obj

    def put(obj, pointer, value):
        ts = tokens(pointer)
        parent = get(obj, "/" + "/".join(pointer[1:].split("/")[:-1])) if len(ts) > 1 else obj
        key = int(ts[-1]) if isinstance(parent, list) else ts[-1]
        parent[key]  # Never insert missing fields or repair malformed objects.
        parent[key] = value

    def canonical_source(rule):
        allowed = {"path", "pointer", "derivation", "source_path", "source_pointer",
                   "source_role", "expected_value"}
        if set(rule) - allowed:
            raise ValueError("UNAUTHORIZED_SOURCE_RULE_FIELD")
        name, pointer, kind = rule["path"], rule["pointer"], rule["derivation"]
        ts = tokens(pointer)
        owner = decode(name, frozen_bytes[name])
        parent_pointer = pointer.rsplit("/", 1)[0]
        record = get(owner, parent_pointer)
        architecture = "phase9/clonorchis-sinensis/p9b1q-architecture-review/"
        roles = {
            "REFERENCE_STAGE_VALIDATOR_EXECUTABLE": architecture + "reference-stage-semantic-validator.py",
            "PRODUCTION_SCOPED_QUERY_IR_EXECUTABLE": "scripts/p9b1q_scoped_query_ir.py",
        }
        requested_role = rule.get("source_role")
        if requested_role is not None and requested_role not in roles:
            raise ValueError("UNKNOWN_SOURCE_ROLE")

        def reference(value):
            if (not isinstance(value, str) or not value or "\\" in value or ":" in value
                    or any(t in ("", ".", "..") for t in value.split("/"))):
                raise ValueError("UNSAFE_SOURCE_REFERENCE")
            candidates = {n for n in (value, architecture + value) if n in frozen_bytes}
            if len(candidates) != 1:
                raise ValueError("MISSING_OR_AMBIGUOUS_CANONICAL_SOURCE")
            return candidates.pop()

        # Target identity establishes a role; the caller can only assert it.
        fixed_targets = {
            (architecture + "fixtures/reference-validator-execution-summary.json", "/executable_sha256"):
                "REFERENCE_STAGE_VALIDATOR_EXECUTABLE",
            (architecture + "fixtures/typed-result-exposure-positive.json", "/solver/executable_sha256"):
                "REFERENCE_STAGE_VALIDATOR_EXECUTABLE",
        }
        expected_role = fixed_targets.get((name, pointer))
        if (pointer == "/producer/executable_sha256"
                and name.startswith(architecture + "fixtures/")
                and isinstance(record, dict) and "producer_id" in record):
            expected_role = "REFERENCE_STAGE_VALIDATOR_EXECUTABLE"
        reference_fields = {
            "canonical_sha256": ("path", "content_path"),
            "byte_length": ("path", "content_path"),
            "executable_sha256": ("executable_path",),
            "configuration_sha256": ("configuration_path",),
            "validator_executable_sha256": ("validator_executable_path",),
            "validator_configuration_sha256": ("validator_configuration_path",),
        }
        keys = [k for k in reference_fields.get(ts[-1], ()) if isinstance(record, dict) and k in record]
        source_pointer = ""
        if ts[-1] == "candidate_semantic_object_set_sha256":
            if (kind != "REMOVAL_CANDIDATE_SHA256" or len(ts) != 4
                    or ts[:2] != ["objects", "minimality_probes"] or not ts[2].isdigit()):
                raise ValueError("R3A_DERIVATION_REQUIRED")
            source = name
            source_pointer = "/objects/typed_solution_core"
        elif expected_role is not None:
            if kind != "RAW_SHA256":
                raise ValueError("UNSUPPORTED_EXECUTABLE_BINDING")
            source = roles[expected_role]
            if keys and (len(keys) != 1 or reference(record[keys[0]]) != source):
                raise ValueError("FIXED_ROLE_RECORD_SOURCE_MISMATCH")
        elif keys:
            if len(keys) != 1 or kind not in ("RAW_SHA256", "BYTE_LENGTH", "CANONICAL_SHA256"):
                raise ValueError("INVALID_RECORD_SOURCE_DERIVATION")
            source = reference(record[keys[0]])
            source_pointer = record.get("content_json_pointer") or ""
            s2_actual = (name in {architecture + "fixtures/stage-validation-s2-positive.json",
                                  architecture + "fixtures/stage-validation-s2-diagnostic-role-catalog-positive.json"}
                         and pointer in {"/actual_input_objects/7/canonical_sha256", "/actual_input_objects/7/byte_length"})
            if s2_actual:
                if kind not in ("RAW_SHA256", "BYTE_LENGTH"):
                    raise ValueError("S2_REQUIRES_WHOLE_RESOLVED_OBJECT_IDENTITY")
                source_pointer = ""
            elif source_pointer and kind != "CANONICAL_SHA256":
                raise ValueError("SUBOBJECT_CANONICAL_DERIVATION_REQUIRED")
        elif kind == "SELF_SHA256":
            if ts[-1] not in ("result_sha256", "sidecar_sha256", "link_sha256"):
                raise ValueError("UNSUPPORTED_SELF_HASH_FIELD")
            source = name
            source_pointer = parent_pointer
        elif (name.endswith("/design-manifest.yml") and len(ts) == 2
              and ts[0] in ("protected_files", "design_files", "fixture_files")):
            source = reference(ts[1])
            if kind != "RAW_SHA256":
                raise ValueError("UNSUPPORTED_MANIFEST_PATH_DERIVATION")
        else:
            raise ValueError("UNRESOLVED_CANONICAL_SOURCE_AUTHORITY")
        if requested_role is not None and roles[requested_role] != source:
            raise ValueError("SOURCE_ROLE_TARGET_MISMATCH")
        if rule.get("source_path", source) != source:
            raise ValueError("SOURCE_PATH_AUTHORITY_MISMATCH")
        if rule.get("source_pointer", source_pointer) != source_pointer:
            raise ValueError("SOURCE_POINTER_AUTHORITY_MISMATCH")
        if source not in frozen_bytes:
            raise ValueError("MISSING_CANONICAL_SOURCE")
        return source, source_pointer

    # Normative objects cannot be made writable by a hash-shaped field policy.
    for name, pointers in field_policy.items():
        lower = name.lower()
        if (name not in frozen_bytes or not pointers or len(pointers) != len(set(pointers))
                or ("/fixtures/" not in name and not name.endswith("/design-manifest.yml"))
                or any(x in lower for x in ("schema", "authority", "ontology", "mapping", "contract", "authorization"))):
            raise ValueError("PROTECTED_OR_UNAUTHORIZED_REFRESH_PATH")
        for pointer in pointers:
            tokens(pointer)
    current = {name: path(name).read_bytes() for name in frozen_bytes}
    planned = dict(frozen_bytes) if global_plan is None else global_plan
    objects = {}
    targets = [(r["path"], r["pointer"]) for r in rules]
    if len(targets) != len(set(targets)):
        raise ValueError("DUPLICATE_REFRESH_TARGET")
    pending_paths = [r["path"] for r in rules]
    for rule in rules:
        name, pointer = rule["path"], rule["pointer"]
        if name not in field_policy or pointer not in field_policy[name]:
            raise ValueError("UNAUTHORIZED_REFRESH_FIELD")
        source, source_pointer = canonical_source(rule)
        pending_paths.pop(0)
        if source not in planned or (source != name and source in pending_paths):
            raise ValueError("UNRESOLVED_OR_FORWARD_REFRESH_SOURCE")
        kind = rule["derivation"]
        leaf = tokens(pointer)[-1]
        manifest = name.endswith("/design-manifest.yml")
        allowed_leaf = (leaf.endswith("sha256") or leaf == "byte_length" or
                        (manifest and tokens(pointer)[0] in ("design_files", "fixture_files", "protected_files")))
        if not allowed_leaf:
            raise ValueError("SEMANTIC_REFRESH_TARGET")
        obj = objects.setdefault(name, decode(name, planned[name]))
        source_raw = planned[source]
        if (name.endswith(("/stage-validation-s2-positive.json", "/stage-validation-s2-diagnostic-role-catalog-positive.json"))
                and pointer in {"/actual_input_objects/7/canonical_sha256", "/actual_input_objects/7/byte_length"}
                and cbytes(decode(source, source_raw)) != source_raw):
            raise ValueError("S2_NONCANONICAL_WHOLE_SOURCE")
        if kind == "RAW_SHA256":
            value = sha_bytes(source_raw)
        elif kind == "BYTE_LENGTH":
            if leaf != "byte_length":
                raise ValueError("DERIVATION_TARGET_MISMATCH")
            value = len(source_raw)
        elif kind == "CANONICAL_SHA256":
            value = csha(get(decode(source, source_raw), source_pointer))
        elif kind == "SELF_SHA256":
            candidate = copy.deepcopy(get(obj, source_pointer))
            del candidate[tokens(pointer)[-1]]
            value = csha(candidate)
        elif kind == "REMOVAL_CANDIDATE_SHA256":
            if leaf != "candidate_semantic_object_set_sha256":
                raise ValueError("REMOVAL_TARGET_MISMATCH")
            core = copy.deepcopy(get(decode(source, source_raw), source_pointer))
            # The operation is read from the actual persisted probe, not the rule.
            probe_pointer = pointer.rsplit("/", 1)[0]
            probe = get(decode(name, frozen_bytes[name]), probe_pointer)
            for operation in probe["operation"]:
                if set(operation) != {"op", "path"} or operation["op"] != "remove":
                    raise ValueError("UNSUPPORTED_REMOVAL_OPERATION")
                ts = tokens(operation["path"])
                if len(ts) != 2 or ts[0] not in SEMANTIC_COLLECTIONS:
                    raise ValueError("INVALID_REMOVAL_TARGET")
                core = apply_remove(core, operation["path"])
            value = csha(semantic_set(core))
        else:
            raise ValueError("UNSUPPORTED_REFRESH_DERIVATION")
        if leaf == "byte_length" and kind != "BYTE_LENGTH":
            raise ValueError("DERIVATION_TARGET_MISMATCH")
        if "expected_value" in rule and rule["expected_value"] != value:
            raise ValueError("UPSTREAM_DERIVATION_MISMATCH")
        put(obj, pointer, value)
        # Compare every other field, including semantic fields, without stripping them.
        before = decode(name, frozen_bytes[name])
        restored = copy.deepcopy(obj)
        for target_name, target_pointer in targets:
            if target_name == name:
                put(restored, target_pointer, get(before, target_pointer))
        if restored != before:
            raise ValueError("SEMANTIC_PAYLOAD_CHANGED")
        planned[name] = frozen_bytes[name] if obj == before else encode(name, obj)
    expected = {n: planned[n] for n in field_policy if planned[n] != frozen_bytes[n]}
    if prospective_bytes is not None and prospective_bytes != expected:
        raise ValueError("PROSPECTIVE_PATCH_MISMATCH")
    # Every actual input must equal either the trusted starting bytes or the exact
    # validated result of this transaction. This also detects synchronized tampering.
    for name, raw in current.items():
        if raw != frozen_bytes[name] and raw != planned[name]:
            raise ValueError("FROZEN_INPUT_CHANGED: " + name)
    changed = sorted(n for n in expected if current[n] != expected[n])
    # Pin all potentially written objects before the first output mutation.
    complete_snapshot()
    if any(path(n).read_bytes() != raw for n, raw in current.items()):
        raise ValueError("REFRESH_INPUT_CHANGED_DURING_VALIDATION")
    expected_live_bytes = dict(current)
    handles = {}
    written = []

    def pinned_bytes(name):
        fd, identity = handles[name]
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != identity:
            raise ValueError("PINNED_OBJECT_IDENTITY_CHANGED: " + name)
        os.lseek(fd, 0, os.SEEK_SET)
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    def write_pinned(name, raw):
        fd, _ = handles[name]
        pinned_bytes(name)  # Verify the original object, never a replacement path.
        os.lseek(fd, 0, os.SEEK_SET)
        offset = 0
        while offset < len(raw):
            count = os.write(fd, raw[offset:])
            if count <= 0:
                raise ValueError("SHORT_PINNED_WRITE: " + name)
            offset += count
        os.ftruncate(fd, len(raw))
        os.fsync(fd)
        if pinned_bytes(name) != raw:
            raise ValueError("PINNED_BYTE_MISMATCH: " + name)

    def validate_live_bytes():
        complete_snapshot()
        for name, (fd, identity) in handles.items():
            info = path(name).stat(follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or (info.st_dev, info.st_ino) != identity):
                raise ValueError("OUTPUT_PATH_IDENTITY_CHANGED: " + name)
            if pinned_bytes(name) != expected_live_bytes[name]:
                raise ValueError("PINNED_INPUT_CHANGED: " + name)
        for name, raw in expected_live_bytes.items():
            if path(name).read_bytes() != raw:
                raise ValueError("WRITE_PHASE_INPUT_CHANGED: " + name)

    try:
        for name in changed:
            target = path(name)
            info = target.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("UNSAFE_OUTPUT_OBJECT: " + name)
            identity = (info.st_dev, info.st_ino)
            fd = os.open(target, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
            handles[name] = (fd, identity)
            if pinned_bytes(name) != current[name]:
                raise ValueError("PINNED_INPUT_MISMATCH: " + name)
        validate_live_bytes()
        for name in changed:
            validate_live_bytes()
            written.append(name)  # Includes a partially failed write.
            write_pinned(name, expected[name])
            expected_live_bytes[name] = expected[name]
            validate_live_bytes()
        validate_live_bytes()
    except Exception as failure:
        rollback_errors = []
        for name in reversed(written):
            try:
                # The descriptor still owns the original object after unlink,
                # rename, or movement of any ancestor outside the root pathname.
                write_pinned(name, current[name])
            except Exception as rollback_failure:
                rollback_errors.append(name + ": " + str(rollback_failure))
        for name in written:
            try:
                if pinned_bytes(name) != current[name]:
                    raise ValueError("ROLLBACK_FINAL_BYTE_MISMATCH")
            except Exception as rollback_failure:
                rollback_errors.append(name + ": " + str(rollback_failure))
        if rollback_errors:
            raise ValueError("ROLLBACK_FAILED: " + "; ".join(rollback_errors)) from failure
        raise ValueError("REFRESH_TRANSACTION_FAIL_CLOSED: " + str(failure)) from failure
    finally:
        for fd, _ in handles.values():
            os.close(fd)

    return changed


def replace_hashes(value: Any, old_exec: str, new_exec: str, old_contract: str, new_contract: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str) and child == old_exec:
                value[key] = new_exec
            elif isinstance(child, str) and child == old_contract:
                value[key] = new_contract
            else:
                replace_hashes(child, old_exec, new_exec, old_contract, new_contract)
    elif isinstance(value, list):
        for child in value:
            replace_hashes(child, old_exec, new_exec, old_contract, new_contract)


def reference(path: str, kind: str, schema_id: str) -> dict[str, Any]:
    absolute = resolve(path)
    return {
        "object_kind": kind,
        "path": path,
        "schema_id": schema_id,
        "canonical_sha256": raw_sha(absolute),
        "byte_length": len(absolute.read_bytes()),
    }


def bootstrap_failure_code_governance() -> tuple[dict[str, Any], dict[str, int]]:
    """Compute the bootstrap gate from the registry, emitters, and fixtures."""
    validator = runpy.run_path(
        str(HERE / "reference-stage-semantic-validator.py"),
        run_name="p9b1q_reference_validator_bootstrap",
    )
    governance = validator["validate_failure_code_governance"]()
    if governance["result"] != "PASS":
        raise RuntimeError(
            "registry failure-code governance bootstrap failed: "
            f"governance={governance}"
        )
    diagnostics = {
        "registry_count": governance["registry_mapping_count"],
        "validator_mapping_count": governance[
            "validator_constraint_mapping_count"
        ],
        "fixture_expectation_count": governance["formal_fixture_count"],
        "explicit_fixture_failure_code_count": governance[
            "explicit_fixture_failure_code_count"
        ],
        "unknown_constraint_ids": governance["unknown_constraint_ids"],
        "failure_code_mismatches": governance[
            "fixture_failure_code_mismatches"
        ],
        "unregistered_failure_code_mappings": governance[
            "unregistered_failure_code_mappings"
        ],
        "multi_failure_code_mappings": governance[
            "multi_authority_failure_code_mappings"
        ],
    }
    return governance, diagnostics


def main() -> None:
    # Refresh the independently generated R3 evidence bundles before any
    # validator compares their persisted bytes with a current rebuild.
    for builder in ("build-r3a-reference-override-evidence.py",):
        subprocess.run(
            ["python", str(HERE / builder)],
            cwd=REPO,
            check=True,
            capture_output=True,
        )

    event_mapping_authority = yaml.safe_load(
        (
            REPO
            / "phase9/clonorchis-sinensis/p9b1q/event-predicate-type-role-mapping.yml"
        ).read_text(encoding="utf-8")
    )
    event_mapping_keys = (
        "derivation_source_tokens",
        "direct_mention_to_relation_derivation",
        "direct_relation_request",
        "event_field_defaults",
        "event_mapping",
        "event_to_relation_derivation",
    )
    write(
        "authority-event-relation-mapping.json",
        {key: event_mapping_authority[key] for key in event_mapping_keys},
    )

    old_exec = load("normalized-request-exposure-positive.json")["producer"]["executable_sha256"]
    old_contract = load("normalized-request-exposure-positive.json")["producer"]["configuration_sha256"]
    new_exec = raw_sha(HERE / "reference-stage-semantic-validator.py")
    new_contract = raw_sha(HERE / "stage-semantic-validator-contract.yml")
    profile_sha = raw_sha(HERE / "object-canonicalization-and-hash-chain.yml")
    constraint_sha = raw_sha(HERE / "constraint-set-v0.1.yml")
    registry_sha = raw_sha(HERE / "constraint-id-registry.yml")
    negation_authority_sha = raw_sha(HERE / "negation-surface-scope-authority.yml")
    negation_semantic_sha = raw_sha(HERE / "negation_semantic_authority.py")
    projection_sha = raw_sha(HERE / "queryir-projection-rule-set.yml")

    # Direct authority proof for the post-freeze shared-left correction.
    shared_request = {
        "knowledge_version": "clonorchis_pcms_v1", "locale": "zh-CN",
        "query_text": "如果生食淡水鱼，但是粪便检卵阴性。",
        "request_id": "P9B1Q-ARCH-SHARED-ARGUMENT-001", "schema_version": "1.0",
    }
    write("request-shared-argument-positive.json", shared_request)
    shared_norm = {
        "knowledge_version": "clonorchis_pcms_v1", "locale": "zh-CN",
        "normalization_operations": ["NONE"],
        "normalized_query_text": shared_request["query_text"],
        "normalized_request_version": "0.1-candidate",
        "producer": {"configuration_sha256": new_contract, "executable_sha256": new_exec,
                     "producer_id": "p9b1q-request-normalizer", "producer_version": "0.1-fixture"},
        "raw_query_text": shared_request["query_text"],
        "raw_to_normalized_spans": [{"normalized_end": 17, "normalized_start": 0, "raw_end": 17, "raw_start": 0}],
        "request_id": shared_request["request_id"], "request_sha256": csha(shared_request),
    }
    write("normalized-request-shared-argument-positive.json", shared_norm)
    span = lambda start, end: {"start_char": start, "end_char": end, "text": shared_request["query_text"][start:end]}
    def snode(node_id: str, kind: str, start: int, end: int, parent: str | None,
              children: list[str], role: str, operator: tuple[int, int] | None = None,
              shared: str | None = None) -> dict[str, Any]:
        value = {"assertion_marker_ids": [], "child_node_ids": children, "node_id": node_id,
                 "node_kind": kind, "operator_span": span(*operator) if operator else None,
                 "parent_node_id": parent, "scope_role": role, "source_span": span(start, end)}
        if shared is not None:
            value["shared_left_argument_node_id"] = shared
        return value
    shared_ast = {
        "assertion_markers": [], "attachment_sets": [], "canonicalization_profile_sha256": profile_sha,
        "clause_ast_version": "0.2-candidate", "clause_grammar_config_sha256": raw_sha(HERE / "clause-grammar-config.yml"),
        "entity_ontology_sha256": raw_sha(REPO / "schema/entity-types.yml"), "knowledge_version": "clonorchis_pcms_v1",
        "nodes": [
            snode("S000", "ROOT", 0, 17, None, ["S001"], "WHOLE_REQUEST"),
            snode("S001", "CONDITION", 0, 16, "S000", ["S002", "S003"], "MATERIAL_PROPOSITION", (0, 2)),
            snode("S002", "PROPOSITION", 2, 7, "S001", [], "CONDITION_ANTECEDENT"),
            snode("S003", "CONTRAST", 8, 16, "S001", ["S004"], "CONDITION_CONSEQUENT", (8, 10), "S002"),
            snode("S004", "PROPOSITION", 10, 16, "S003", [], "CONTRAST_RIGHT"),
        ],
        "normalized_request_sha256": csha(shared_norm),
        "producer": {"configuration_sha256": raw_sha(HERE / "clause-grammar-config.yml"), "executable_sha256": new_exec,
                     "producer_id": "p9b1q-clause-ast-compiler", "producer_version": "0.1-fixture"},
        "request_id": shared_request["request_id"], "request_sha256": csha(shared_request), "root_node_id": "S000",
        "span_basis": "REQUEST_QUERY_TEXT_UNICODE_CODEPOINT_ZERO_BASED_HALF_OPEN",
        "stage_validator_contract_sha256": new_contract, "surface_mentions": [],
    }
    write("clause-ast-shared-argument-positive.json", shared_ast)

    # Formal Option-B proof: one diagnostic frame contains all three explicit
    # diagnostic predicates.  Repeated disease and method mentions must merge
    # into one canonical role slot with the union of source IDs.
    role_parts = [
        "粪便检查显示虫卵是人的诊断阶段",
        "华支睾吸虫病的确诊方法是粪便检查",
        "华支睾吸虫病的诊断线索包括粪便检查",
        "十二指肠液检查未检出虫卵",
        "比较粪便检查与影像检查后，华支睾吸虫病的确诊方法是粪便检查",
        "粪便检查是华支睾吸虫病的确诊方法，影像检查仅用于比较",
        "犬猫猪与成虫仅用于比较",
    ]
    role_text = "；".join(role_parts) + "。"
    role_request = {
        "knowledge_version": "clonorchis_pcms_v1",
        "locale": "zh-CN",
        "query_text": role_text,
        "request_id": "P9B1Q-ARCH-DIAGNOSTIC-ROLE-CATALOG-001",
        "schema_version": "1.0",
    }
    write("request-diagnostic-role-catalog-positive.json", role_request)
    role_norm = {
        "knowledge_version": "clonorchis_pcms_v1",
        "locale": "zh-CN",
        "normalization_operations": ["NONE"],
        "normalized_query_text": role_text,
        "normalized_request_version": "0.1-candidate",
        "producer": {
            "configuration_sha256": new_contract,
            "executable_sha256": new_exec,
            "producer_id": "p9b1q-request-normalizer",
            "producer_version": "0.1-fixture",
        },
        "raw_query_text": role_text,
        "raw_to_normalized_spans": [{
            "normalized_end": len(role_text),
            "normalized_start": 0,
            "raw_end": len(role_text),
            "raw_start": 0,
        }],
        "request_id": role_request["request_id"],
        "request_sha256": csha(role_request),
    }
    write("normalized-request-diagnostic-role-catalog-positive.json", role_norm)
    role_starts = [0]
    for part in role_parts[:-1]:
        role_starts.append(role_starts[-1] + len(part) + 1)
    role_ends = [start + len(part) for start, part in zip(role_starts, role_parts)]
    role_span = lambda start, end: {
        "start_char": start,
        "end_char": end,
        "text": role_text[start:end],
    }

    def role_node(
        node_id: str,
        kind: str,
        start: int,
        end: int,
        parent: str | None,
        children: list[str],
        scope_role: str,
        operator: tuple[int, int] | None = None,
        assertion_markers: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "assertion_marker_ids": assertion_markers or [],
            "child_node_ids": children,
            "node_id": node_id,
            "node_kind": kind,
            "operator_span": role_span(*operator) if operator else None,
            "parent_node_id": parent,
            "scope_role": scope_role,
            "source_span": role_span(start, end),
        }

    def role_mention(
        mention_id: str,
        surface: str,
        entity_id: str,
        entity_type: str,
        containing_node_id: str,
        start_at: int,
    ) -> dict[str, Any]:
        start = role_text.index(surface, start_at)
        return {
            "candidate_entity_ids": [entity_id],
            "candidate_entity_types": [entity_type],
            "candidate_origin": "FORMAL_ALIAS_EXACT",
            "containing_node_id": containing_node_id,
            "normalized_surface": surface,
            "source_span": role_span(start, start + len(surface)),
            "surface_mention_id": mention_id,
        }

    role_ast = {
        "assertion_markers": [{
            "containing_node_id": "S005",
            "marker_id": "K001",
            "marker_kind": "NEGATOR",
            "scope_status": "UNIQUE",
            "scope_target_candidate_ids": ["U009"],
            "source_span": role_span(
                role_text.index("未检出", role_starts[3]),
                role_text.index("未检出", role_starts[3]) + len("未检出"),
            ),
        }],
        "attachment_sets": [],
        "canonicalization_profile_sha256": profile_sha,
        "clause_ast_version": "0.2-candidate",
        "clause_grammar_config_sha256": raw_sha(HERE / "clause-grammar-config.yml"),
        "entity_ontology_sha256": raw_sha(REPO / "schema/entity-types.yml"),
        "knowledge_version": "clonorchis_pcms_v1",
        "nodes": [
            role_node("S000", "ROOT", 0, len(role_text), None, ["S001"], "WHOLE_REQUEST"),
            role_node("S001", "COORDINATION", 0, len(role_text) - 1, "S000", ["S002", "S003", "S004", "S005", "S006", "S007", "S008"], "MATERIAL_PROPOSITION", (role_ends[0], role_ends[0] + 1)),
            role_node("S002", "PROPOSITION", role_starts[0], role_ends[0], "S001", [], "COORDINATE_MEMBER"),
            role_node("S003", "PROPOSITION", role_starts[1], role_ends[1], "S001", [], "COORDINATE_MEMBER"),
            role_node("S004", "PROPOSITION", role_starts[2], role_ends[2], "S001", [], "COORDINATE_MEMBER"),
            role_node("S005", "PROPOSITION", role_starts[3], role_ends[3], "S001", [], "COORDINATE_MEMBER", assertion_markers=["K001"]),
            role_node("S006", "PROPOSITION", role_starts[4], role_ends[4], "S001", [], "COORDINATE_MEMBER"),
            role_node("S007", "PROPOSITION", role_starts[5], role_ends[5], "S001", [], "COORDINATE_MEMBER"),
            role_node("S008", "PROPOSITION", role_starts[6], role_ends[6], "S001", [], "COORDINATE_MEMBER"),
        ],
        "normalized_request_sha256": csha(role_norm),
        "producer": {
            "configuration_sha256": raw_sha(HERE / "clause-grammar-config.yml"),
            "executable_sha256": new_exec,
            "producer_id": "p9b1q-clause-ast-compiler",
            "producer_version": "0.2-fixture",
        },
        "request_id": role_request["request_id"],
        "request_sha256": csha(role_request),
        "root_node_id": "S000",
        "span_basis": "REQUEST_QUERY_TEXT_UNICODE_CODEPOINT_ZERO_BASED_HALF_OPEN",
        "stage_validator_contract_sha256": new_contract,
        "surface_mentions": [
            role_mention("U001", "粪便检查", "diagnostic.stool_egg_microscopy", "diagnostic_method", "S002", role_starts[0]),
            role_mention("U002", "虫卵", "stage.clonorchis_egg", "life_cycle_stage", "S002", role_starts[0]),
            role_mention("U003", "人", "host.human", "host", "S002", role_starts[0]),
            role_mention("U004", "华支睾吸虫病", "disease.clonorchiasis", "disease", "S003", role_starts[1]),
            role_mention("U005", "粪便检查", "diagnostic.stool_egg_microscopy", "diagnostic_method", "S003", role_starts[1]),
            role_mention("U006", "华支睾吸虫病", "disease.clonorchiasis", "disease", "S004", role_starts[2]),
            role_mention("U007", "粪便检查", "diagnostic.stool_egg_microscopy", "diagnostic_method", "S004", role_starts[2]),
            role_mention("U008", "十二指肠液检查", "diagnostic.duodenal_fluid_egg_microscopy", "diagnostic_method", "S005", role_starts[3]),
            role_mention("U009", "虫卵", "stage.clonorchis_egg", "life_cycle_stage", "S005", role_starts[3]),
            role_mention("U010", "粪便检查", "diagnostic.stool_egg_microscopy", "diagnostic_method", "S006", role_starts[4]),
            role_mention("U011", "影像检查", "diagnostic.biliary_imaging", "diagnostic_method", "S006", role_starts[4]),
            role_mention("U012", "华支睾吸虫病", "disease.clonorchiasis", "disease", "S006", role_starts[4]),
            role_mention("U013", "粪便检查", "diagnostic.stool_egg_microscopy", "diagnostic_method", "S006", role_text.rindex("粪便检查", role_starts[4], role_ends[4])),
            role_mention("U014", "粪便检查", "diagnostic.stool_egg_microscopy", "diagnostic_method", "S007", role_starts[5]),
            role_mention("U015", "华支睾吸虫病", "disease.clonorchiasis", "disease", "S007", role_starts[5]),
            role_mention("U016", "影像检查", "diagnostic.biliary_imaging", "diagnostic_method", "S007", role_starts[5]),
            role_mention("U017", "犬猫猪", "host.domestic_dogs_cats_pigs", "host", "S008", role_starts[6]),
            role_mention("U018", "成虫", "stage.clonorchis_adult", "life_cycle_stage", "S008", role_starts[6]),
        ],
    }
    write("clause-ast-diagnostic-role-catalog-positive.json", role_ast)

    method_occurrence_ids = ["U001", "U005", "U007", "U013", "U014"]
    event_method_occurrence_ids = ["U001"]

    def bound_argument(
        side: str,
        surface_ids: list[str],
        method_binding_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "argument_side": side,
            "binding_state": "BOUND",
            "surface_mention_ids": surface_ids,
            "method_entity_binding_id": method_binding_id,
        }

    diagnostic_argument_binding = {
        "binding_object_version": "0.1-candidate",
        "binding_scope": "DIAGNOSTIC_ONLY",
        "binding_contract_sha256": raw_sha(
            HERE / "diagnostic-predicate-argument-binding-contract.yml"
        ),
        "query_interpreter_config_sha256": raw_sha(
            REPO / "phase9/clonorchis-sinensis/p9b1q/query-interpreter-config.yml"
        ),
        "event_relation_mapping_sha256": raw_sha(
            FIX / "authority-event-relation-mapping.json"
        ),
        "request_bindings": [{
            "request_id": role_request["request_id"],
            "normalized_request_sha256": csha(role_norm),
            "clause_ast_sha256": csha(role_ast),
            "diagnostic_contexts": [{
                "diagnostic_context_id": "DC001",
                "governing_ast_node_ids": ["S002", "S003", "S004", "S006", "S007"],
                "method_entity_bindings": [{
                    "method_entity_binding_id": "DMB001",
                    "method_entity_id": "diagnostic.stool_egg_microscopy",
                    "binding_state": "BOUND",
                    "surface_mention_ids": event_method_occurrence_ids,
                }],
                "predicate_occurrences": [
                    {
                        "predicate_occurrence_id": "DPO001",
                        "canonical_predicate": "diagnostic_stage_for",
                        "proposition_node_id": "S002",
                        "argument_bindings": [
                            bound_argument("SUBJECT", ["U002"]),
                            bound_argument("OBJECT", ["U003"]),
                        ],
                    },
                    {
                        "predicate_occurrence_id": "DPO002",
                        "canonical_predicate": "diagnosed_by",
                        "proposition_node_id": "S003",
                        "argument_bindings": [
                            bound_argument("SUBJECT", ["U004"]),
                            bound_argument("OBJECT", ["U005"], "DMB001"),
                        ],
                    },
                    {
                        "predicate_occurrence_id": "DPO003",
                        "canonical_predicate": "has_diagnostic_clue",
                        "proposition_node_id": "S004",
                        "argument_bindings": [
                            bound_argument("SUBJECT", ["U006"]),
                            bound_argument("OBJECT", ["U007"]),
                        ],
                    },
                    {
                        "predicate_occurrence_id": "DPO004",
                        "canonical_predicate": "diagnosed_by",
                        "proposition_node_id": "S006",
                        "argument_bindings": [
                            bound_argument("SUBJECT", ["U012"]),
                            bound_argument("OBJECT", ["U013"], "DMB001"),
                        ],
                    },
                    {
                        "predicate_occurrence_id": "DPO005",
                        "canonical_predicate": "diagnosed_by",
                        "proposition_node_id": "S007",
                        "argument_bindings": [
                            bound_argument("SUBJECT", ["U015"]),
                            bound_argument("OBJECT", ["U014"], "DMB001"),
                        ],
                    },
                ],
            }],
        }],
    }
    role_mentions = {
        item["surface_mention_id"]: item
        for item in role_ast["surface_mentions"]
    }
    stool_method_source_ids = method_occurrence_ids
    role_frame = {
        "canonicalization_profile_sha256": profile_sha,
        "clause_ast_sha256": csha(role_ast),
        "entity_ontology_sha256": raw_sha(REPO / "schema/entity-types.yml"),
        "event_frame_version": "0.2-candidate",
        "event_relation_mapping_sha256": raw_sha(FIX / "authority-event-relation-mapping.json"),
        "frames": [{
            "assertion": {
                "assertion_status": "AFFIRMED",
                "finding_polarity": "POSITIVE",
                "governing_ast_node_ids": ["S002", "S003", "S004", "S006", "S007"],
                "marker_ids": [],
                "temporal_scope": "GENERAL",
            },
            "diagnostic_binding": {
                "method_slot_id": "V001",
                "polarity_source_ids": ["S002", "S003", "S004", "S006", "S007"],
                "specimen_slot_id": "SP001",
                "target_slot_ids": ["V002"],
            },
            "event_type_domain": ["DIAGNOSTIC_FINDING"],
            "frame_id": "EF001",
            "frame_status": "FIXED",
            "normalized_identity": {
                "actor_slot_ids": ["V003", "V004"],
                "anatomical_site_slot_ids": [],
                "event_type_domain": ["DIAGNOSTIC_FINDING"],
                "method_slot_id": "V001",
                "specimen_slot_ids": ["SP001"],
                "target_slot_ids": ["V002"],
                "temporal_scope_domain": ["GENERAL"],
            },
            "participant_slots": [
                {"binding_status": "FIXED", "domain": {"entity_ids": ["diagnostic.stool_egg_microscopy"], "entity_types": ["diagnostic_method"]}, "semantic_role": "METHOD", "slot_id": "V001", "source_ids": stool_method_source_ids},
                {"binding_status": "FIXED", "domain": {"entity_ids": ["stage.clonorchis_egg"], "entity_types": ["life_cycle_stage"]}, "semantic_role": "TARGET", "slot_id": "V002", "source_ids": ["U002"]},
                {"binding_status": "FIXED", "domain": {"entity_ids": ["host.human"], "entity_types": ["host"]}, "semantic_role": "ACTOR", "slot_id": "V003", "source_ids": ["U003"]},
                {"binding_status": "FIXED", "domain": {"entity_ids": ["disease.clonorchiasis"], "entity_types": ["disease"]}, "semantic_role": "ACTOR", "slot_id": "V004", "source_ids": ["U004", "U006", "U012", "U015"]},
            ],
            "source_ast_node_ids": ["S002", "S003", "S004", "S006", "S007", "S008"],
            "source_spans": [
                role_span(role_starts[index], role_ends[index])
                for index in (0, 1, 2, 4, 5, 6)
            ],
        }, {
            "assertion": {
                "assertion_status": "AFFIRMED",
                "finding_polarity": "NEGATIVE",
                "governing_ast_node_ids": ["S005"],
                "marker_ids": [],
                "temporal_scope": "GENERAL",
            },
            "diagnostic_binding": {
                "method_slot_id": "V005",
                "polarity_source_ids": ["K001"],
                "specimen_slot_id": "SP002",
                "target_slot_ids": ["V006"],
            },
            "event_type_domain": ["DIAGNOSTIC_FINDING"],
            "frame_id": "EF002",
            "frame_status": "FIXED",
            "normalized_identity": {
                "actor_slot_ids": [],
                "anatomical_site_slot_ids": [],
                "event_type_domain": ["DIAGNOSTIC_FINDING"],
                "method_slot_id": "V005",
                "specimen_slot_ids": ["SP002"],
                "target_slot_ids": ["V006"],
                "temporal_scope_domain": ["GENERAL"],
            },
            "participant_slots": [
                {"binding_status": "FIXED", "domain": {"entity_ids": ["diagnostic.duodenal_fluid_egg_microscopy"], "entity_types": ["diagnostic_method"]}, "semantic_role": "METHOD", "slot_id": "V005", "source_ids": ["U008"]},
                {"binding_status": "FIXED", "domain": {"entity_ids": ["stage.clonorchis_egg"], "entity_types": ["life_cycle_stage"]}, "semantic_role": "TARGET", "slot_id": "V006", "source_ids": ["U009"]},
            ],
            "source_ast_node_ids": ["S005"],
            "source_spans": [role_span(role_starts[3], role_ends[3])],
        }],
        "knowledge_version": "clonorchis_pcms_v1",
        "normalized_request_sha256": csha(role_norm),
        "override_hypotheses": [],
        "producer": {
            "configuration_sha256": raw_sha(FIX / "authority-event-relation-mapping.json"),
            "executable_sha256": new_exec,
            "producer_id": "p9b1q-event-frame-compiler",
            "producer_version": "0.2-fixture",
        },
        "reference_hypotheses": [],
        "request_id": role_request["request_id"],
        "request_sha256": csha(role_request),
        "specimen_slots": [{
            "binding_status": "FIXED",
            "source_ids": stool_method_source_ids,
            "source_spans": [
                role_span(
                    role_mentions[source_id]["source_span"]["start_char"],
                    role_mentions[source_id]["source_span"]["start_char"] + 2,
                )
                for source_id in stool_method_source_ids
            ],
            "specimen_code_domain": ["STOOL"],
            "specimen_slot_id": "SP001",
        }, {
            "binding_status": "FIXED",
            "source_ids": ["U008"],
            "source_spans": [role_span(
                role_text.index("十二指肠液检查", role_starts[3]),
                role_text.index("十二指肠液检查", role_starts[3]) + len("十二指肠液"),
            )],
            "specimen_code_domain": ["DUODENAL_FLUID"],
            "specimen_slot_id": "SP002",
        }],
        "stage_validator_contract_sha256": new_contract,
    }
    write("event-frame-diagnostic-role-catalog-positive.json", role_frame)

    requests: dict[str, dict[str, Any]] = {}
    normalized: dict[str, dict[str, Any]] = {}
    asts: dict[str, dict[str, Any]] = {}
    frames: dict[str, dict[str, Any]] = {}
    for suffix in ("exposure", "diagnostic"):
        request = load(f"request-{suffix}-positive.json")
        requests[suffix] = request
        norm = load(f"normalized-request-{suffix}-positive.json")
        norm["producer"]["executable_sha256"] = new_exec
        norm["producer"]["configuration_sha256"] = new_contract
        write(f"normalized-request-{suffix}-positive.json", norm)
        normalized[suffix] = norm

        ast = load(f"clause-ast-{suffix}-positive.json")
        if suffix == "diagnostic":
            egg = next(
                item for item in ast["surface_mentions"]
                if item["surface_mention_id"] == "U002"
            )
            egg["normalized_surface"] = "卵"
            egg["candidate_origin"] = "FORMAL_ALIAS_EXACT"
            egg["source_span"] = {"start_char": 3, "end_char": 4, "text": "卵"}
        ast["normalized_request_sha256"] = csha(norm)
        ast["stage_validator_contract_sha256"] = new_contract
        ast["producer"]["executable_sha256"] = new_exec
        write(f"clause-ast-{suffix}-positive.json", ast)
        asts[suffix] = ast

        frame = load(f"event-frame-{suffix}-positive.json")
        frame["normalized_request_sha256"] = csha(norm)
        frame["clause_ast_sha256"] = csha(ast)
        frame["stage_validator_contract_sha256"] = new_contract
        frame["producer"]["executable_sha256"] = new_exec
        frame["event_relation_mapping_sha256"] = raw_sha(FIX / "authority-event-relation-mapping.json")
        frame["producer"]["configuration_sha256"] = raw_sha(FIX / "authority-event-relation-mapping.json")
        write(f"event-frame-{suffix}-positive.json", frame)
        frames[suffix] = frame

    def empty_diagnostic_binding(
        norm: dict[str, Any], ast: dict[str, Any]
    ) -> dict[str, Any]:
        binding = copy.deepcopy(diagnostic_argument_binding)
        binding["request_bindings"] = [{
            "request_id": norm["request_id"],
            "normalized_request_sha256": csha(norm),
            "clause_ast_sha256": csha(ast),
            "diagnostic_contexts": [],
        }]
        return binding

    diagnostic_binding_evidence = {
        "evidence_set_version": "0.1-candidate",
        "bindings": {
            "exposure": empty_diagnostic_binding(
                normalized["exposure"], asts["exposure"]
            ),
            "diagnostic": empty_diagnostic_binding(
                normalized["diagnostic"], asts["diagnostic"]
            ),
            "diagnostic-role-catalog": diagnostic_argument_binding,
        },
    }
    write(
        "diagnostic-predicate-argument-binding-positive.json",
        diagnostic_binding_evidence,
    )

    core = load("typed-solution-exposure-positive.json")
    registry = yaml.safe_load((HERE / "constraint-id-registry.yml").read_text(encoding="utf-8"))
    core["satisfied_constraint_ids"] = [
        entry["id"]
        for entry in registry["entries"]
        if entry["stage"] in {
            "S0_NORMALIZED_REQUEST",
            "S1_CLAUSE_AST",
            "S2_EVENT_FRAME",
            "S3_TYPED_SOLVER",
        }
    ]
    refresh_core(core)
    write("typed-solution-exposure-positive.json", core)
    core_sha = csha(core)

    probe_hashes: dict[str, str] = {}
    for path in sorted(FIX.glob("minimality-removal-probe-*.json")):
        probe = json.loads(path.read_text(encoding="utf-8"))
        replace_hashes(probe, old_exec, new_exec, old_contract, new_contract)
        probe["base_typed_solution_sha256"] = core_sha
        probe["constraint_set_sha256"] = constraint_sha
        candidate = apply_remove(core, probe["mutation"][0]["path"])
        refresh_core(candidate)
        probe["candidate_typed_solution_sha256"] = csha(candidate)
        probe["candidate_semantic_object_set_sha256"] = candidate["semantic_object_set_sha256"]
        probe["recomputed_derived_hashes"] = ["semantic_object_set_sha256"]
        probe["enumerated_solution_count_after_removal"] = 0
        path.write_bytes(cbytes(probe))
        probe_hashes[probe["removed_semantic_object_id"]] = csha(probe)

    query_ir = load("queryir-exposure-positive.json")
    query_ir["producer"]["configuration_sha256"] = projection_sha
    write("queryir-exposure-positive.json", query_ir)

    emission = load("queryir-emission-record-exposure-positive.json")
    emission["normalized_request_sha256"] = csha(normalized["exposure"])
    emission["clause_ast_sha256"] = csha(asts["exposure"])
    emission["event_frame_sha256"] = csha(frames["exposure"])
    emission["semantic_solution_core_sha256"] = core_sha
    emission["projection_rule_set_sha256"] = projection_sha
    emission["query_ir"] = copy.deepcopy(query_ir)
    emission["query_ir_sha256"] = csha(query_ir)
    for trace in emission["field_traces"]:
        trace["emitted_value_sha256"] = csha(
            pointer_get(query_ir, trace["query_ir_json_pointer"])
        )
        for binding in trace["source_bindings"]:
            if binding["object_kind"] == "TYPED_SOLUTION":
                binding["object_sha256"] = core_sha
            elif binding["object_kind"] == "CLAUSE_AST":
                binding["object_sha256"] = csha(asts["exposure"])
    roots = {"R01": ["LN0001", "LN0004"], "N01": ["LN0001", "LN0004", "LN0005"], "N02": ["LN0001", "LN0004", "LN0006"], "Q01": ["LN0001", "LN0004", "LN0007"], "Q02": ["LN0001", "LN0004", "LN0008"]}
    witness = emission["minimality_witness"]
    for item in witness["retained_object_witnesses"]:
        if item["semantic_object_id"] in roots:
            item["license_path_node_ids"] = roots[item["semantic_object_id"]]
        item["removal_probe_sha256"] = probe_hashes[item["semantic_object_id"]]
    witness_body = copy.deepcopy(witness)
    witness_body.pop("witness_sha256", None)
    witness["witness_sha256"] = csha(witness_body)
    write("queryir-emission-record-exposure-positive.json", emission)

    typed = load("typed-result-exposure-positive.json")
    replace_hashes(typed, old_exec, new_exec, old_contract, new_contract)
    typed["normalized_request_sha256"] = csha(normalized["exposure"])
    typed["clause_ast_sha256"] = csha(asts["exposure"])
    typed["event_frame_sha256"] = csha(frames["exposure"])
    typed["event_relation_mapping_sha256"] = raw_sha(
        FIX / "authority-event-relation-mapping.json"
    )
    typed["constraint_set_sha256"] = constraint_sha
    typed["constraint_registry_sha256"] = registry_sha
    typed["selected_solution"] = copy.deepcopy(core)
    typed["selected_solution"]["queryir_emission_record"] = emission
    typed["solver"]["executable_sha256"] = new_exec
    typed["stage_validator_contract_sha256"] = new_contract
    write("typed-result-exposure-positive.json", typed)

    # Stage validation results bind exact actual bytes after every leaf is final.
    stage_files = [f"stage-validation-s{i}-positive.json" for i in range(5)]
    for name in stage_files:
        result = load(name)
        replace_hashes(result, old_exec, new_exec, old_contract, new_contract)
        result["canonicalization_profile_sha256"] = profile_sha
        result["validator_contract_sha256"] = new_contract
        result["validator"]["executable_sha256"] = new_exec
        result["validator"]["configuration_sha256"] = new_contract
        result["validator"]["validator_version"] = "0.3-reference"
        stage_id = result["stage"]
        result["verified_constraint_ids"] = yaml.safe_load(
            (HERE / "stage-semantic-validator-contract.yml").read_text(encoding="utf-8")
        )["validators"][stage_id]["registered_constraints"]
        if name == "stage-validation-s1-positive.json" and not any(
            item["object_kind"] == "ENTITY_ALIAS_AUTHORITY"
            for item in result["actual_input_objects"]
        ):
            alias_path = REPO / "phase9/clonorchis-sinensis/p9b1q/query-interpreter-config.yml"
            result["actual_input_objects"].append({
                "object_kind": "ENTITY_ALIAS_AUTHORITY",
                "content_path": "phase9/clonorchis-sinensis/p9b1q/query-interpreter-config.yml",
                "content_json_pointer": None,
                "schema_id": "phase9/clonorchis-sinensis/p9b1q/query-interpreter-config.yml",
                "canonical_sha256": raw_sha(alias_path),
                "byte_length": len(alias_path.read_bytes()),
            })
        if name in ("stage-validation-s1-positive.json", "stage-validation-s3-positive.json"):
            required = {
                "NEGATION_SURFACE_SCOPE_AUTHORITY": {
                    "content_path": "phase9/clonorchis-sinensis/p9b1q-architecture-review/negation-surface-scope-authority.yml",
                    "schema_id": "negation-surface-scope-authority-schema-candidate.yml",
                    "canonical_sha256": negation_authority_sha,
                    "byte_length": len((HERE / "negation-surface-scope-authority.yml").read_bytes()),
                },
                "NEGATION_SEMANTIC_AUTHORITY_EXECUTABLE": {
                    "content_path": "phase9/clonorchis-sinensis/p9b1q-architecture-review/negation_semantic_authority.py",
                    "schema_id": "python3-pure-semantic-authority",
                    "canonical_sha256": negation_semantic_sha,
                    "byte_length": len((HERE / "negation_semantic_authority.py").read_bytes()),
                },
            }
            present = {item["object_kind"] for item in result["actual_input_objects"]}
            for object_kind, fields in required.items():
                if object_kind not in present:
                    result["actual_input_objects"].append(
                        {"object_kind": object_kind, "content_json_pointer": None} | fields
                    )
        if name == "stage-validation-s3-positive.json" and not any(
            item["object_kind"] == "PROJECTION_RULE_SET"
            for item in result["actual_input_objects"]
        ):
            result["actual_input_objects"].append({
                "object_kind": "PROJECTION_RULE_SET",
                "content_path": "phase9/clonorchis-sinensis/p9b1q-architecture-review/queryir-projection-rule-set.yml",
                "content_json_pointer": None,
                "schema_id": "queryir-projection-rule-set.yml",
                "canonical_sha256": projection_sha,
                "byte_length": len((HERE / "queryir-projection-rule-set.yml").read_bytes()),
            })
        if name == "stage-validation-s3-positive.json" and not any(
            item["object_kind"] == "CONSTRAINT_SET_SCHEMA"
            for item in result["actual_input_objects"]
        ):
            schema_path = HERE / "constraint-set-schema-candidate.yml"
            result["actual_input_objects"].append({
                "object_kind": "CONSTRAINT_SET_SCHEMA",
                "content_path": "phase9/clonorchis-sinensis/p9b1q-architecture-review/constraint-set-schema-candidate.yml",
                "content_json_pointer": None,
                "schema_id": "constraint-set-schema-candidate.yml",
                "canonical_sha256": raw_sha(schema_path),
                "byte_length": len(schema_path.read_bytes()),
            })
        if name == "stage-validation-s2-positive.json" and not any(
            item["object_kind"] == "QUERY_INTERPRETER_CONFIG"
            for item in result["actual_input_objects"]
        ):
            query_config_path = (
                REPO
                / "phase9/clonorchis-sinensis/p9b1q/query-interpreter-config.yml"
            )
            result["actual_input_objects"].append({
                "object_kind": "QUERY_INTERPRETER_CONFIG",
                "content_path": "phase9/clonorchis-sinensis/p9b1q/query-interpreter-config.yml",
                "content_json_pointer": None,
                "schema_id": "phase9/clonorchis-sinensis/p9b1q/query-interpreter-config.yml",
                "canonical_sha256": raw_sha(query_config_path),
                "byte_length": len(query_config_path.read_bytes()),
            })
        if name == "stage-validation-s2-positive.json" and not any(
            item["object_kind"] == "DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING"
            for item in result["actual_input_objects"]
        ):
            binding_path = FIX / "diagnostic-predicate-argument-binding-positive.json"
            result["actual_input_objects"].append({
                "object_kind": "DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING",
                "content_path": "phase9/clonorchis-sinensis/p9b1q-architecture-review/fixtures/diagnostic-predicate-argument-binding-positive.json",
                "content_json_pointer": None,
                "schema_id": "diagnostic-predicate-argument-binding-schema-candidate.yml",
                "canonical_sha256": raw_sha(binding_path),
                "byte_length": len(binding_path.read_bytes()),
            })
        if name == "stage-validation-s2-positive.json":
            for item in result["actual_input_objects"]:
                if item["object_kind"] == "DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING":
                    item["content_json_pointer"] = "/bindings/exposure"
        for item in result["actual_input_objects"] + [result["actual_output_object"]]:
            absolute = resolve(item["content_path"])
            item["canonical_sha256"] = raw_sha(absolute)
            item["byte_length"] = len(absolute.read_bytes())
        body = copy.deepcopy(result)
        body.pop("result_sha256", None)
        result["result_sha256"] = csha(body)
        write(name, result)

    shared_stage = copy.deepcopy(load("stage-validation-s1-positive.json"))
    shared_stage["request_id"] = shared_request["request_id"]
    for item in shared_stage["actual_input_objects"]:
        if item["object_kind"] == "NORMALIZED_REQUEST":
            item["content_path"] = "phase9/clonorchis-sinensis/p9b1q-architecture-review/fixtures/normalized-request-shared-argument-positive.json"
            item["canonical_sha256"] = raw_sha(FIX / "normalized-request-shared-argument-positive.json")
            item["byte_length"] = len((FIX / "normalized-request-shared-argument-positive.json").read_bytes())
    shared_stage["actual_output_object"]["content_path"] = "phase9/clonorchis-sinensis/p9b1q-architecture-review/fixtures/clause-ast-shared-argument-positive.json"
    shared_stage["actual_output_object"]["canonical_sha256"] = raw_sha(FIX / "clause-ast-shared-argument-positive.json")
    shared_stage["actual_output_object"]["byte_length"] = len((FIX / "clause-ast-shared-argument-positive.json").read_bytes())
    shared_body = copy.deepcopy(shared_stage); shared_body.pop("result_sha256", None)
    shared_stage["result_sha256"] = csha(shared_body)
    write("stage-validation-s1-shared-argument-positive.json", shared_stage)

    role_stage = copy.deepcopy(load("stage-validation-s2-positive.json"))
    role_stage["request_id"] = role_request["request_id"]
    role_stage["verified_constraint_ids"] = yaml.safe_load(
        (HERE / "stage-semantic-validator-contract.yml").read_text(encoding="utf-8")
    )["validators"]["S2_EVENT_FRAME"]["registered_constraints"]
    for item in role_stage["actual_input_objects"]:
        if item["object_kind"] == "NORMALIZED_REQUEST":
            item["content_path"] = "phase9/clonorchis-sinensis/p9b1q-architecture-review/fixtures/normalized-request-diagnostic-role-catalog-positive.json"
        elif item["object_kind"] == "CLAUSE_AST":
            item["content_path"] = "phase9/clonorchis-sinensis/p9b1q-architecture-review/fixtures/clause-ast-diagnostic-role-catalog-positive.json"
        elif item["object_kind"] == "DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING":
            item["content_json_pointer"] = "/bindings/diagnostic-role-catalog"
        absolute = resolve(item["content_path"])
        item["canonical_sha256"] = raw_sha(absolute)
        item["byte_length"] = len(absolute.read_bytes())
    role_stage["actual_output_object"]["content_path"] = "phase9/clonorchis-sinensis/p9b1q-architecture-review/fixtures/event-frame-diagnostic-role-catalog-positive.json"
    role_output_path = resolve(role_stage["actual_output_object"]["content_path"])
    role_stage["actual_output_object"]["canonical_sha256"] = raw_sha(role_output_path)
    role_stage["actual_output_object"]["byte_length"] = len(role_output_path.read_bytes())
    role_stage_body = copy.deepcopy(role_stage)
    role_stage_body.pop("result_sha256", None)
    role_stage["result_sha256"] = csha(role_stage_body)
    write("stage-validation-s2-diagnostic-role-catalog-positive.json", role_stage)

    sidecar = load("execution-binding-sidecar-positive.json")
    replace_hashes(sidecar, old_exec, new_exec, old_contract, new_contract)
    sidecar["canonicalization_profile_sha256"] = profile_sha
    sidecar["validator_contract_sha256"] = new_contract
    by_path: dict[str, dict[str, Any]] = {}
    for item in sidecar["actual_objects"]:
        by_path[item["path"]] = reference(item["path"], item["object_kind"], item["schema_id"])
    review_prefix = "phase9/clonorchis-sinensis/p9b1q-architecture-review/"
    for stage_name in stage_files:
        stage = load(stage_name)
        for item in stage["actual_input_objects"] + [stage["actual_output_object"]]:
            relative = item["content_path"]
            if relative.startswith(review_prefix):
                relative = relative[len(review_prefix):]
            by_path[relative] = reference(relative, item["object_kind"], item["schema_id"])
    extras = [
        ("strict-schema-gate.mjs", "STRICT_SCHEMA_GATE_EXECUTABLE", "node-esm-review-executable"),
        ("package.json", "SCHEMA_GATE_DEPENDENCY_MANIFEST", "npm-package-json"),
        ("package-lock.json", "SCHEMA_GATE_DEPENDENCY_LOCK", "npm-package-lock-v3"),
    ]
    for path, kind, schema_id in extras:
        by_path[path] = reference(path, kind, schema_id)
    preferred = [item["path"] for item in sidecar["actual_objects"]]
    sidecar["actual_objects"] = [by_path[path] for path in preferred if path in by_path]
    sidecar["actual_objects"].extend(by_path[path] for path in sorted(set(by_path) - set(preferred)))
    sidecar_body = copy.deepcopy(sidecar)
    sidecar_body.pop("sidecar_sha256", None)
    sidecar["sidecar_sha256"] = csha(sidecar_body)
    write("execution-binding-sidecar-positive.json", sidecar)
    actual_sidecar_canonical_sha256 = csha(sidecar)

    index = load("object-store-index-positive.json")
    index["objects"] = [
        {k: item[k] for k in ("canonical_sha256", "object_kind", "path", "schema_id")}
        for item in sidecar["actual_objects"]
    ]
    index["objects"].append({
        "canonical_sha256": actual_sidecar_canonical_sha256,
        "object_kind": "EXECUTION_BINDING_SIDECAR",
        "path": "fixtures/execution-binding-sidecar-positive.json",
        "schema_id": "execution-binding-sidecar-architecture-schema-candidate.yml",
    })
    index["sidecar_sha256"] = actual_sidecar_canonical_sha256
    write("object-store-index-positive.json", index)

    negative_path = FIX / "stage-validator-negative-fixtures.yml"
    negative = yaml.safe_load(negative_path.read_text(encoding="utf-8"))
    negative["status"] = "R3H_LOCAL_CANDIDATE_PENDING_FINAL_RE_REVIEW"
    role_base_paths = [
        "fixtures/request-diagnostic-role-catalog-positive.json",
        "fixtures/normalized-request-diagnostic-role-catalog-positive.json",
        "fixtures/clause-ast-diagnostic-role-catalog-positive.json",
        "fixtures/event-frame-diagnostic-role-catalog-positive.json",
    ]
    existing_base_paths = {item["path"] for item in negative["base_objects"]}
    for path in role_base_paths:
        if path not in existing_base_paths:
            negative["base_objects"].append({
                "path": path,
                "canonical_sha256": raw_sha(resolve(path)),
            })

    new_constraint = "CNS-EF-DIAGNOSTIC-ROLE-DERIVATION"
    new_failure = "DIAGNOSTIC_ROLE_DERIVATION_INVALID"
    base_case = {
        "stage": "S2_EVENT_FRAME",
        "valid_base_object_path": "fixtures/event-frame-diagnostic-role-catalog-positive.json",
        "paired_actual_object_paths": [
            "fixtures/clause-ast-diagnostic-role-catalog-positive.json"
        ],
        "expected_result": "FAIL_CLOSED",
        "expected_constraint_id": new_constraint,
        "expected_failure_code": new_failure,
        "semantic_mutation_target_count": 1,
        "derived_updates": [],
    }

    def output_case(
        fixture_id: str,
        fault_class: str,
        path: str,
        operation: str,
        value: Any = None,
    ) -> dict[str, Any]:
        patch = {"op": operation, "path": path}
        if operation != "remove":
            patch["value"] = value
        return copy.deepcopy(base_case) | {
            "fixture_id": fixture_id,
            "fault_class": fault_class,
            "patch": [patch],
            "semantic_mutation": {
                "target_object": "STAGE_BASE_OBJECT",
                "target_path": path,
                "mutation_intent": fault_class,
                "expected_constraint_id": new_constraint,
                "mechanism": "RFC6902",
            },
        }

    def input_case(
        fixture_id: str,
        fault_class: str,
        object_kind: str,
        path: str,
        value: Any,
        *,
        operation: str = "replace",
        case_base: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return copy.deepcopy(case_base or base_case) | {
            "fixture_id": fixture_id,
            "fault_class": fault_class,
            "patch": [],
            "actual_input_mutation": {
                "object_kind": object_kind,
                "patch": [{"op": operation, "path": path, "value": value}],
            },
            "semantic_mutation": {
                "target_object": object_kind,
                "target_path": path,
                "mutation_intent": fault_class,
                "expected_constraint_id": new_constraint,
                "mechanism": "CROSS_OBJECT_RFC6902",
            },
        }

    extra_theme_slot = {
        "binding_status": "FIXED",
        "domain": {
            "entity_ids": ["disease.clonorchiasis"],
            "entity_types": ["disease"],
        },
        "semantic_role": "THEME",
        "slot_id": "V900",
        "source_ids": ["U004"],
    }
    type_only_slot = {
        "binding_status": "FIXED",
        "domain": {
            "entity_ids": ["stage.clonorchis_egg"],
            "entity_types": ["life_cycle_stage"],
        },
        "semantic_role": "ACTOR",
        "slot_id": "V900",
        "source_ids": ["U002"],
    }
    duplicate_role_slot = {
        "binding_status": "FIXED",
        "domain": {
            "entity_ids": ["diagnostic.stool_egg_microscopy"],
            "entity_types": ["diagnostic_method"],
        },
        "semantic_role": "THEME",
        "slot_id": "V900",
        "source_ids": ["U001"],
    }
    duplicate_method_slot = copy.deepcopy(duplicate_role_slot)
    duplicate_method_slot["semantic_role"] = "METHOD"
    duplicate_method_slot["source_ids"] = stool_method_source_ids
    unrelated_method_slot = {
        "binding_status": "FIXED",
        "domain": {
            "entity_ids": ["diagnostic.biliary_imaging"],
            "entity_types": ["diagnostic_method"],
        },
        "semantic_role": "METHOD",
        "slot_id": "V900",
        "source_ids": ["U011"],
    }
    duplicate_id_slot = {
        "binding_status": "FIXED",
        "domain": {
            "entity_ids": ["disease.clonorchiasis"],
            "entity_types": ["disease"],
        },
        "semantic_role": "ACTOR",
        "slot_id": "V001",
        "source_ids": ["U004"],
    }
    exposure_base_case = copy.deepcopy(base_case)
    exposure_base_case["valid_base_object_path"] = (
        "fixtures/event-frame-exposure-positive.json"
    )
    exposure_base_case["paired_actual_object_paths"] = [
        "fixtures/clause-ast-exposure-positive.json"
    ]
    dangling_exposure_context = {
        "diagnostic_context_id": "DC999",
        "governing_ast_node_ids": ["S999"],
        "method_entity_bindings": [{
            "binding_state": "BOUND",
            "method_entity_binding_id": "DMB999",
            "method_entity_id": "diagnostic.stool_egg_microscopy",
            "surface_mention_ids": ["U999"],
        }],
        "predicate_occurrences": [{
            "argument_bindings": [{
                "argument_side": "SUBJECT",
                "binding_state": "BOUND",
                "method_entity_binding_id": None,
                "surface_mention_ids": ["U998"],
            }, {
                "argument_side": "OBJECT",
                "binding_state": "BOUND",
                "method_entity_binding_id": "DMB999",
                "surface_mention_ids": ["U999"],
            }],
            "canonical_predicate": "diagnosed_by",
            "predicate_occurrence_id": "DPO999",
            "proposition_node_id": "S999",
        }],
    }

    role_cases = [
        output_case("NEG-S2-DIAGNOSTIC-ROLE-MISSING-REQUIRED-PARTICIPANT", "MISSING_REQUIRED_PREDICATE_PARTICIPANT", "/frames/0/participant_slots/3/source_ids", "replace", ["U004"]),
        output_case("NEG-S2-DIAGNOSTIC-ROLE-EXTRA-UNLICENSED", "EXTRA_PREDICATE_UNLICENSED_PARTICIPANT_ROLE", "/frames/0/participant_slots/4", "add", extra_theme_slot),
        input_case("NEG-S2-DIAGNOSTIC-ROLE-SUBJECT-OBJECT-REVERSAL", "SUBJECT_OBJECT_ROLE_REVERSAL", "EVENT_RELATION_MAPPING", "/event_mapping/DIAGNOSTIC_FINDING/diagnostic_participant_role_catalog/diagnostic_stage_for/subject/semantic_role", "ACTOR"),
        output_case("NEG-S2-DIAGNOSTIC-ROLE-TYPE-ONLY-EXPANSION", "TYPE_ONLY_ROLE_EXPANSION", "/frames/0/participant_slots/4", "add", type_only_slot),
        output_case("NEG-S2-DIAGNOSTIC-ROLE-SAME-MENTION-DUPLICATE", "SAME_MENTION_ILLEGAL_DUPLICATE_ROLE", "/frames/0/participant_slots/4", "add", duplicate_role_slot),
        output_case("NEG-S2-DIAGNOSTIC-ROLE-METHOD-SHORTCUT-PREDICATE-LOSS", "METHOD_SHORTCUT_DROPS_EXPRESSED_PREDICATE", "/frames/0/source_ast_node_ids", "replace", ["S002"]),
        input_case("NEG-S2-DIAGNOSTIC-ROLE-CATALOG-DIRECTION-DRIFT", "CATALOG_SOURCE_TOKEN_DRIFT", "EVENT_RELATION_MAPPING", "/event_mapping/DIAGNOSTIC_FINDING/diagnostic_participant_role_catalog/diagnostic_stage_for/subject/source_token", "disease"),
        output_case("NEG-S2-DIAGNOSTIC-ROLE-DUPLICATE-METHOD", "DUPLICATE_METHOD_INSTEAD_OF_CANONICAL_MERGE", "/frames/0/participant_slots/4", "add", duplicate_method_slot),
        output_case("NEG-S2-DIAGNOSTIC-ROLE-WRONG-IDENTITY-DIMENSION", "NORMALIZED_IDENTITY_WRONG_ROLE_DIMENSION", "/frames/0/normalized_identity/actor_slot_ids", "replace", ["V003"]),
        output_case("NEG-S2-DIAGNOSTIC-ROLE-PARTICIPANT-SET-MISMATCH", "ACTUAL_PARTICIPANT_SET_DIFFERS_FROM_RECOMPUTED_EXPECTED_SET", "/frames/0/participant_slots/3/source_ids", "replace", ["U003", "U004", "U006"]),
        output_case("NEG-S2-DIAGNOSTIC-ROLE-UNRELATED-SAME-TYPE-METHOD", "UNRELATED_SAME_TYPE_MENTION_NOT_BOUND", "/frames/0/participant_slots/4", "add", unrelated_method_slot),
        output_case("NEG-S2-DIAGNOSTIC-ROLE-UNBOUND-SAME-ENTITY-OCCURRENCE", "UNBOUND_SAME_ENTITY_OCCURRENCE_PROVENANCE", "/frames/0/participant_slots/0/source_ids/5", "add", "U010"),
        input_case(
            "NEG-S2-DIAGNOSTIC-ROLE-AMBIGUOUS-OCCURRENCE-BINDING",
            "AMBIGUOUS_OCCURRENCE_BINDING",
            "DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING",
            "/request_bindings/0/diagnostic_contexts/0/predicate_occurrences/3/argument_bindings/1",
            {
                "argument_side": "OBJECT",
                "binding_state": "AMBIGUOUS",
                "surface_mention_ids": ["U010", "U013"],
                "method_entity_binding_id": "DMB001",
            },
        ),
        input_case(
            "NEG-S2-DIAGNOSTIC-ROLE-UNRESOLVED-OCCURRENCE-BINDING",
            "UNRESOLVED_OCCURRENCE_BINDING",
            "DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING",
            "/request_bindings/0/diagnostic_contexts/0/predicate_occurrences/3/argument_bindings/1",
            {
                "argument_side": "OBJECT",
                "binding_state": "UNRESOLVED",
                "surface_mention_ids": [],
                "method_entity_binding_id": "DMB001",
            },
        ),
        input_case(
            "NEG-S2-DIAGNOSTIC-AUTHORITY-NONDIAGNOSTIC-WRONG-REQUEST",
            "SUPPLIED_AUTHORITY_WRONG_REQUEST_ID",
            "DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING",
            "/request_bindings/0/request_id",
            "P9B1Q-WRONG-REQUEST",
            case_base=exposure_base_case,
        ),
        input_case(
            "NEG-S2-DIAGNOSTIC-AUTHORITY-NONDIAGNOSTIC-WRONG-NORMALIZED-HASH",
            "SUPPLIED_AUTHORITY_WRONG_NORMALIZED_REQUEST_HASH",
            "DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING",
            "/request_bindings/0/normalized_request_sha256",
            "0" * 64,
            case_base=exposure_base_case,
        ),
        input_case(
            "NEG-S2-DIAGNOSTIC-AUTHORITY-NONDIAGNOSTIC-WRONG-AST-HASH",
            "SUPPLIED_AUTHORITY_WRONG_CLAUSE_AST_HASH",
            "DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING",
            "/request_bindings/0/clause_ast_sha256",
            "0" * 64,
            case_base=exposure_base_case,
        ),
        input_case(
            "NEG-S2-DIAGNOSTIC-AUTHORITY-NONDIAGNOSTIC-DANGLING-CONTEXT",
            "SUPPLIED_AUTHORITY_UNSELECTED_DANGLING_CONTEXT",
            "DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING",
            "/request_bindings/0/diagnostic_contexts/0",
            dangling_exposure_context,
            operation="add",
            case_base=exposure_base_case,
        ),
    ]
    duplicate_id_case = output_case(
        "NEG-S2-DUPLICATE-PARTICIPANT-SLOT-ID",
        "DUPLICATE_PARTICIPANT_SLOT_ID",
        "/frames/0/participant_slots/4",
        "add",
        duplicate_id_slot,
    )
    duplicate_id_case["expected_constraint_id"] = "CNS-EF-ID_UNIQUE"
    duplicate_id_case["expected_failure_code"] = "DUPLICATE_ID"
    duplicate_id_case["semantic_mutation"]["expected_constraint_id"] = (
        "CNS-EF-ID_UNIQUE"
    )
    new_fixture_ids = {
        item["fixture_id"] for item in role_cases + [duplicate_id_case]
    }
    negative["cases"] = [
        item for item in negative["cases"]
        if item.get("fixture_id") not in new_fixture_ids
    ] + role_cases + [duplicate_id_case]
    for item in negative["base_objects"]:
        item["canonical_sha256"] = raw_sha(resolve(item["path"]))
    for case in negative["cases"]:
        if "base_object_canonical_sha256" in case:
            case["base_object_canonical_sha256"] = raw_sha(resolve(case["valid_base_object_path"]))
        if case["stage"] == "S5_RUNTIME_BINDING":
            case["paired_actual_object_paths"] = [item["path"] for item in sidecar["actual_objects"]]
    negative_path.write_text(yaml.safe_dump(negative, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Bootstrap the persisted summary into the new Schema using current formal
    # authorities, validate that bootstrap strictly, then replace it with actual
    # full execution. No case result is synthesized here.
    summary = load("reference-validator-execution-summary.json")
    summary["executable_sha256"] = new_exec
    summary["configuration_sha256"] = new_contract
    governance, governance_diagnostics = bootstrap_failure_code_governance()
    summary["registry_failure_governance"] = governance
    bootstrap_validator = runpy.run_path(
        str(HERE / "reference-stage-semantic-validator.py"),
        run_name="p9b1q_reference_validator_shared_bootstrap",
    )
    shared_s0_errors = bootstrap_validator["validate_s0"](shared_norm, shared_request)
    shared_s1_errors = bootstrap_validator["validate_s1"](shared_ast, shared_norm)
    if shared_s0_errors or shared_s1_errors:
        raise RuntimeError(f"shared argument positive bootstrap failed: S0={shared_s0_errors}; S1={shared_s1_errors}")
    summary["positive"] = [
        item for item in summary["positive"]
        if item["case"] not in {
            "POS-S0-shared-argument",
            "POS-S1-shared-argument",
            "POS-S0-diagnostic-role-catalog",
            "POS-S1-diagnostic-role-catalog",
            "POS-S2-diagnostic-role-catalog",
        }
    ] + [
        {"case": "POS-S0-shared-argument", "errors": []},
        {"case": "POS-S1-shared-argument", "errors": []},
        {"case": "POS-S0-diagnostic-role-catalog", "errors": []},
        {"case": "POS-S1-diagnostic-role-catalog", "errors": []},
        {"case": "POS-S2-diagnostic-role-catalog", "errors": []},
    ]
    summary["positive_pass_count"] = len(summary["positive"])
    stage_negative_run = subprocess.run(
        ["python", str(HERE / "reference-stage-semantic-validator.py"), "--mode", "negative"],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    stage_negative = json.loads(stage_negative_run.stdout)
    r3b_negative_run = subprocess.run(
        ["python", str(HERE / "reference-stage-semantic-validator.py"), "--mode", "r3b"],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    r3b_negative = json.loads(r3b_negative_run.stdout)["negative"]
    if not all(item["passed"] for item in stage_negative + r3b_negative):
        raise RuntimeError("bootstrap negative execution did not pass")
    summary["negative"] = stage_negative + r3b_negative
    summary["negative_pass_count"] = len(summary["negative"])
    # Discover the live inventory before serializing its counts.  The existing
    # summary remains a schema fixture during this bootstrap pass, but none of
    # its previously recorded counts controls discovery or gate success.
    schema_run = subprocess.run(
        ["node", str(HERE / "strict-schema-gate.mjs")],
        cwd=HERE,
        check=False,
        capture_output=True,
        text=True,
    )
    schema_result = json.loads(schema_run.stdout)
    invalid_fixtures = {
        item.get("fixture")
        for item in schema_result.get("results", [])
        if not item.get("valid")
    }
    if (
        not isinstance(schema_result.get("compiled_schema_count"), int)
        or not isinstance(schema_result.get("fixture_pair_count"), int)
        or invalid_fixtures
        - {"fixtures/reference-validator-execution-summary.json"}
    ):
        raise RuntimeError(
            f"bootstrap strict schema gate discovery/result mismatch: {schema_result}"
        )
    summary["schema_gate"] = {
        key: schema_result[key]
        for key in (
            "gate_id",
            "ajv_version",
            "strict",
            "compiled_schema_count",
            "fixture_pair_count",
        )
    }
    summary["schema_gate"].update(
        {
            # The only bootstrap-invalid fixture is this summary itself.  Once
            # replaced below, the fresh full gate must independently prove the
            # dynamically discovered pair inventory is entirely valid.
            "valid_fixture_count": schema_result["fixture_pair_count"],
            "result": "PASS",
            "runner_sha256": raw_sha(HERE / "strict-schema-gate.mjs"),
            "lockfile_sha256": raw_sha(HERE / "package-lock.json"),
        }
    )
    write("reference-validator-execution-summary.json", summary)
    verified_schema_run = subprocess.run(
        ["node", str(HERE / "strict-schema-gate.mjs")],
        cwd=HERE,
        check=False,
        capture_output=True,
        text=True,
    )
    verified_schema_result = json.loads(verified_schema_run.stdout)
    if (
        verified_schema_run.returncode != 0
        or verified_schema_result.get("result") != "PASS"
        or verified_schema_result.get("compiled_schema_count")
        != schema_result.get("compiled_schema_count")
        or verified_schema_result.get("fixture_pair_count")
        != schema_result.get("fixture_pair_count")
        or verified_schema_result.get("valid_fixture_count")
        != verified_schema_result.get("fixture_pair_count")
    ):
        raise RuntimeError(
            f"verified strict schema gate discovery/result mismatch: {verified_schema_result}"
        )
    completed = subprocess.run(
        ["python", str(HERE / "reference-stage-semantic-validator.py"), "--mode", "all"],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    final_summary = json.loads(completed.stdout)
    if final_summary.get("registry_failure_governance") != governance:
        raise RuntimeError("final summary governance differs from bootstrap authority")
    (FIX / "reference-validator-execution-summary.json").write_bytes(completed.stdout)
    subprocess.run(
        ["python", str(HERE / "build-design-manifest.py")],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    print(json.dumps({"validator_sha256": new_exec, "contract_sha256": new_contract, "sidecar_object_count": len(sidecar["actual_objects"]), "summary_sha256": raw_sha(FIX / "reference-validator-execution-summary.json"), "registry_failure_governance": governance_diagnostics}, sort_keys=True))


if __name__ == "__main__":
    main()
