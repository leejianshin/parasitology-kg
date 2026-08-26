#!/usr/bin/env python3
"""Deterministically rebuild the review-only P9-B1Q architecture evidence chain."""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
import subprocess
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


def semantic_set(core: dict[str, Any]) -> dict[str, Any]:
    return {k: core[k] for k in ("resolved_mentions", "resolved_events", "resolved_relations", "semantic_roles", "narrative_intents", "resolved_references", "resolved_overrides")}


def refresh_core(core: dict[str, Any]) -> None:
    core["semantic_object_set_sha256"] = csha(semantic_set(core))
    core["solution_id"] = f"SOL-{core['semantic_object_set_sha256'][:24]}"


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
    for builder in (
        "build-r3a-reference-override-evidence.py",
        "build-r3b-negation-evidence.py",
    ):
        subprocess.run(
            ["python", str(HERE / builder)],
            cwd=REPO,
            check=True,
            capture_output=True,
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
        write(f"event-frame-{suffix}-positive.json", frame)
        frames[suffix] = frame

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
        for item in result["actual_input_objects"] + [result["actual_output_object"]]:
            absolute = resolve(item["content_path"])
            item["canonical_sha256"] = raw_sha(absolute)
            item["byte_length"] = len(absolute.read_bytes())
        body = copy.deepcopy(result)
        body.pop("result_sha256", None)
        result["result_sha256"] = csha(body)
        write(name, result)

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
    summary["schema_gate"] = {
        "gate_id": "p9b1q-ajv-draft2020-strict",
        "ajv_version": "8.17.1",
        "strict": True,
        "compiled_schema_count": 12,
        "fixture_pair_count": 27,
        "valid_fixture_count": 27,
        "result": "PASS",
        "runner_sha256": raw_sha(HERE / "strict-schema-gate.mjs"),
        "lockfile_sha256": raw_sha(HERE / "package-lock.json"),
    }
    write("reference-validator-execution-summary.json", summary)
    schema_run = subprocess.run(
        ["node", str(HERE / "strict-schema-gate.mjs")],
        cwd=HERE,
        check=False,
        capture_output=True,
        text=True,
    )
    if schema_run.returncode != 0:
        raise RuntimeError(
            f"bootstrap strict schema gate failed: {schema_run.stderr.strip()}"
        )
    schema_result = json.loads(schema_run.stdout)
    if (
        schema_result.get("result") != "PASS"
        or schema_result.get("compiled_schema_count") != 12
        or schema_result.get("fixture_pair_count") != 27
        or schema_result.get("valid_fixture_count") != 27
    ):
        raise RuntimeError(
            f"bootstrap strict schema gate count/result mismatch: {schema_result}"
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
