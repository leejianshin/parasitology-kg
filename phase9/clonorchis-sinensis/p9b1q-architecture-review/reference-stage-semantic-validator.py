#!/usr/bin/env python3
"""Deterministic executable evidence for the P9-B1Q architecture contract.

This is a review-only reference validator.  It does not implement retrieval and
does not modify the frozen 6ac0e4b runtime.  It validates the persisted positive
objects, replays the removal witnesses, and applies every RFC 6902 negative
fixture using the frozen constraint order.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import importlib.util
import itertools
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

import negation_semantic_authority as negation_semantic


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIXTURES = HERE / "fixtures"
CONTRACT = HERE / "stage-semantic-validator-contract.yml"
REGISTRY = HERE / "constraint-id-registry.yml"
NEGATIVE = FIXTURES / "stage-validator-negative-fixtures.yml"
R3A_NEGATIVE = FIXTURES / "r3a-reference-override-negative-fixtures.yml"
R3A_POSITIVE = FIXTURES / "r3a-reference-override-positive.json"
SCHEMA_GATE = HERE / "strict-schema-gate.mjs"
CONSTRAINT_SET = HERE / "constraint-set-v0.1.yml"
PROJECTION_RULE_SET = HERE / "queryir-projection-rule-set.yml"
EVENT_IDENTITY_CONTRACT = HERE / "event-identity-contract.yml"
CONSTRAINT_REGISTRY_SCHEMA = HERE / "constraint-id-registry-schema-candidate.yml"
CONSTRAINT_SET_SCHEMA = HERE / "constraint-set-schema-candidate.yml"
NEGATION_AUTHORITY = HERE / "negation-surface-scope-authority.yml"
NEGATION_SEMANTIC_IMPLEMENTATION = HERE / "negation_semantic_authority.py"
R3B_NEGATIVE = FIXTURES / "r3b-negation-scope-negative-fixtures.yml"
R3B_POSITIVE = FIXTURES / "r3b-negation-scope-positive.json"
NEGATIVE_MUTATION_MODEL = HERE / "negative-fixture-semantic-mutation-model.yml"
QUERY_INTERPRETER_CONFIG = REPO / "phase9/clonorchis-sinensis/p9b1q/query-interpreter-config.yml"
DIAGNOSTIC_ARGUMENT_BINDING_CONTRACT = HERE / "diagnostic-predicate-argument-binding-contract.yml"
DIAGNOSTIC_ARGUMENT_BINDING_FIXTURE = FIXTURES / "diagnostic-predicate-argument-binding-positive.json"
_SCHEMA_VALID_CACHE: dict[tuple[str, str], bool] = {}
_SCHEMA_GATE_CACHE: dict[str, Any] | None = None
_REGISTRY_ORDER_CACHE: dict[str, int] | None = None
_REGISTRY_FAILURE_CACHE: dict[str, str] | None = None
_NEGATIVE_MUTATION_MODEL_CACHE: dict[str, Any] | None = None


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha(value: Any) -> str:
    return sha_bytes(canonical_bytes(value))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def resolve_review_path(relative: str) -> Path:
    candidate = HERE / relative
    return candidate if candidate.exists() else REPO / relative


def pointer_get(value: Any, pointer: str) -> Any:
    if pointer in ("", None):
        return value
    current = value
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def pointer_parent(value: Any, pointer: str) -> tuple[Any, str]:
    tokens = pointer.lstrip("/").split("/")
    parent = value
    for token in tokens[:-1]:
        token = token.replace("~1", "/").replace("~0", "~")
        parent = parent[int(token)] if isinstance(parent, list) else parent[token]
    return parent, tokens[-1].replace("~1", "/").replace("~0", "~")


def apply_patch(value: Any, patch: list[dict[str, Any]]) -> Any:
    output = copy.deepcopy(value)
    for operation in patch:
        parent, token = pointer_parent(output, operation["path"])
        key: Any = int(token) if isinstance(parent, list) else token
        if operation["op"] == "remove":
            parent.pop(key)
        elif operation["op"] == "replace":
            parent[key] = copy.deepcopy(operation["value"])
        elif operation["op"] == "add":
            if isinstance(parent, list):
                parent.insert(key, copy.deepcopy(operation["value"]))
            else:
                parent[key] = copy.deepcopy(operation["value"])
        else:
            raise ValueError(f"unsupported patch operation: {operation['op']}")
    return output


def all_json_pointers(value: Any, prefix: str = "") -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            pointer = f"{prefix}/{escaped}"
            result.append(pointer)
            result.extend(all_json_pointers(child, pointer))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            pointer = f"{prefix}/{index}"
            result.append(pointer)
            result.extend(all_json_pointers(child, pointer))
    return result


def registry_failure_map() -> dict[str, str]:
    global _REGISTRY_FAILURE_CACHE
    if _REGISTRY_FAILURE_CACHE is None:
        entries = load_yaml(REGISTRY)["entries"]
        mapping = {entry["id"]: entry["failure_code"] for entry in entries}
        if len(mapping) != len(entries):
            raise RuntimeError("constraint registry contains duplicate IDs")
        _REGISTRY_FAILURE_CACHE = mapping
    return _REGISTRY_FAILURE_CACHE


def registry_failure(constraint_id: str) -> str:
    try:
        return registry_failure_map()[constraint_id]
    except KeyError as exc:
        raise RuntimeError(f"unregistered constraint output: {constraint_id}") from exc


def error(constraint_id: str, failure_code: str, pointer: str) -> dict[str, str]:
    canonical_failure_code = registry_failure(constraint_id)
    if failure_code != canonical_failure_code:
        raise RuntimeError(
            f"unauthorized failure-code mapping: {constraint_id} -> {failure_code}; "
            f"registry requires {canonical_failure_code}"
        )
    return {
        "constraint_id": constraint_id,
        "failure_code": canonical_failure_code,
        "json_pointer": pointer,
    }


def validate_failure_code_governance(
    *,
    source_text_overrides: dict[str, str] | None = None,
    fixture_manifest_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mechanically bind emitters and every formal fixture to the registry.

    Optional in-memory overrides exist only so the formal governance gate can
    replay fail-closed counterexamples without changing persisted authority.
    """
    counterexample_invocation = (
        source_text_overrides is not None
        or fixture_manifest_overrides is not None
    )
    registry = registry_failure_map()
    emitted: dict[str, set[str]] = {}
    unauthorized_dynamic_calls: list[str] = []
    registry_bound_dynamic_calls = 0
    source_text_overrides = source_text_overrides or {}
    for path in (Path(__file__).resolve(), NEGATION_SEMANTIC_IMPLEMENTATION):
        source_text = source_text_overrides.get(
            path.name, path.read_text(encoding="utf-8")
        )
        tree = ast.parse(source_text, filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "error"
            ):
                continue
            if len(node.args) != 3:
                unauthorized_dynamic_calls.append(f"{path.name}:{node.lineno}")
                continue
            constraint_arg, failure_arg = node.args[:2]
            if (
                isinstance(constraint_arg, ast.Constant)
                and isinstance(constraint_arg.value, str)
                and isinstance(failure_arg, ast.Constant)
                and isinstance(failure_arg.value, str)
            ):
                emitted.setdefault(constraint_arg.value, set()).add(
                    failure_arg.value
                )
                continue
            if (
                isinstance(failure_arg, ast.Call)
                and isinstance(failure_arg.func, ast.Name)
                and failure_arg.func.id == "registry_failure"
                and len(failure_arg.args) == 1
                and ast.dump(failure_arg.args[0]) == ast.dump(constraint_arg)
            ):
                registry_bound_dynamic_calls += 1
                continue
            unauthorized_dynamic_calls.append(f"{path.name}:{node.lineno}")

    unknown_constraints = sorted(set(emitted) - set(registry))
    mismatches = sorted(
        (constraint_id, failure_code, registry.get(constraint_id))
        for constraint_id, failure_codes in emitted.items()
        for failure_code in failure_codes
        if registry.get(constraint_id) != failure_code
    )
    multiple_mappings = sorted(
        constraint_id
        for constraint_id, failure_codes in emitted.items()
        if len(failure_codes) != 1
    )
    missing_executable_constraints = sorted(set(registry) - set(emitted))
    match_count = sum(
        1
        for constraint_id, failure_codes in emitted.items()
        for failure_code in failure_codes
        if registry.get(constraint_id) == failure_code
    )
    fixture_manifest_overrides = fixture_manifest_overrides or {}
    formal_fixture_count = 0
    explicit_fixture_failure_code_count = 0
    unknown_fixture_constraint_ids: list[str] = []
    fixture_failure_code_mismatches: list[str] = []
    missing_fixture_failure_codes: list[str] = []
    for manifest_path in (NEGATIVE, R3A_NEGATIVE, R3B_NEGATIVE):
        manifest = fixture_manifest_overrides.get(
            manifest_path.name, load_yaml(manifest_path)
        )
        for case in manifest["cases"]:
            formal_fixture_count += 1
            fixture_id = case.get("fixture_id", "<unknown>")
            constraint_id = case.get("expected_constraint_id")
            failure_code = case.get("expected_failure_code")
            if constraint_id not in registry:
                unknown_fixture_constraint_ids.append(
                    f"{fixture_id}:{constraint_id}"
                )
            if not isinstance(failure_code, str) or not failure_code:
                missing_fixture_failure_codes.append(fixture_id)
            else:
                explicit_fixture_failure_code_count += 1
                if (
                    constraint_id in registry
                    and failure_code != registry[constraint_id]
                ):
                    fixture_failure_code_mismatches.append(
                        f"{fixture_id}:{constraint_id}:{failure_code}"
                    )

    passed = not (
        unknown_constraints
        or mismatches
        or multiple_mappings
        or missing_executable_constraints
        or unauthorized_dynamic_calls
        or unknown_fixture_constraint_ids
        or fixture_failure_code_mismatches
        or missing_fixture_failure_codes
    )
    result = {
        "registry_mapping_count": len(registry),
        "validator_constraint_mapping_count": sum(
            len(value) for value in emitted.values()
        ),
        "executable_constraint_count": len(emitted),
        "formal_fixture_count": formal_fixture_count,
        "explicit_fixture_failure_code_count": explicit_fixture_failure_code_count,
        "match_count": match_count,
        "mismatch_count": len(mismatches),
        "unknown_constraint_ids": len(unknown_fixture_constraint_ids),
        "validator_failure_code_mismatches": len(mismatches),
        "fixture_failure_code_mismatches": len(fixture_failure_code_mismatches),
        "missing_fixture_failure_codes": len(missing_fixture_failure_codes),
        "missing_executable_constraints": len(missing_executable_constraints),
        "unregistered_constraint_outputs": len(unknown_constraints),
        "unregistered_failure_code_mappings": len(mismatches),
        "multi_authority_failure_code_mappings": len(multiple_mappings),
        "multi_failure_code_mappings": len(multiple_mappings),
        "unauthorized_dynamic_output_calls": len(unauthorized_dynamic_calls),
        "registry_bound_dynamic_calls": registry_bound_dynamic_calls,
        "result": "PASS" if passed else "FAIL_CLOSED",
    }
    if counterexample_invocation:
        return result

    stage_manifest = load_yaml(NEGATIVE)
    wrong_code_manifest = copy.deepcopy(stage_manifest)
    wrong_code_manifest["cases"][0]["expected_failure_code"] = "WRONG_TEMP_CODE"
    missing_code_manifest = copy.deepcopy(stage_manifest)
    missing_code_manifest["cases"][0].pop("expected_failure_code")
    unknown_constraint_manifest = copy.deepcopy(stage_manifest)
    unknown_constraint_manifest["cases"][0]["expected_constraint_id"] = (
        "CNS-UNKNOWN-TEMP-CONSTRAINT"
    )
    validator_source = Path(__file__).read_text(encoding="utf-8")
    mapping_literal = (
        'error("CNS-EMIT-MINIMALITY_WITNESS", "MINIMALITY_WITNESS_INVALID",'
    )
    source_prefix, mapping_separator, source_suffix = validator_source.rpartition(
        mapping_literal
    )
    if not mapping_separator:
        raise RuntimeError("S4 minimality emitter mapping is not enumerable")
    changed_validator_source = (
        source_prefix
        + 'error("CNS-EMIT-MINIMALITY_WITNESS", "WRONG_TEMP_CODE",'
        + source_suffix
    )
    counterexamples = {
        "wrong_fixture_code_gate": validate_failure_code_governance(
            fixture_manifest_overrides={NEGATIVE.name: wrong_code_manifest}
        )["result"],
        "missing_fixture_code_gate": validate_failure_code_governance(
            fixture_manifest_overrides={NEGATIVE.name: missing_code_manifest}
        )["result"],
        "unknown_constraint_gate": validate_failure_code_governance(
            fixture_manifest_overrides={NEGATIVE.name: unknown_constraint_manifest}
        )["result"],
        "validator_registry_mapping_gate": validate_failure_code_governance(
            source_text_overrides={Path(__file__).name: changed_validator_source}
        )["result"],
    }
    result.update(
        {
            key: "REJECT" if value == "FAIL_CLOSED" else "ACCEPT"
            for key, value in counterexamples.items()
        }
    )
    result["s4_minimality_fixture_governed"] = any(
        case["fixture_id"] == "NEG-S4-MISSING-RETAINED-OBJECT-WITNESS"
        for case in stage_manifest["cases"]
    )
    if (
        any(value != "FAIL_CLOSED" for value in counterexamples.values())
        or not result["s4_minimality_fixture_governed"]
    ):
        result["result"] = "FAIL_CLOSED"
    return result


def require_failure_code_governance() -> dict[str, Any]:
    result = validate_failure_code_governance()
    if result["result"] != "PASS":
        raise RuntimeError(f"failure-code governance gate failed: {result}")
    return result


def registry_order() -> dict[str, int]:
    global _REGISTRY_ORDER_CACHE
    if _REGISTRY_ORDER_CACHE is None:
        _REGISTRY_ORDER_CACHE = {
            entry["id"]: entry["order"] for entry in load_yaml(REGISTRY)["entries"]
        }
    return _REGISTRY_ORDER_CACHE


def ordered(errors: list[dict[str, str]]) -> list[dict[str, str]]:
    order = registry_order()
    return sorted(errors, key=lambda item: (order[item["constraint_id"]], item["json_pointer"]))


def validate_s0(normalized: dict[str, Any], request: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not schema_valid("normalized-request-schema-candidate.yml", normalized):
        errors.append(error("CNS-NORM-REQUEST_BINDING", "INPUT_HASH_MISMATCH", "/"))
    raw = normalized["raw_query_text"]
    text = normalized["normalized_query_text"]
    spans = normalized["raw_to_normalized_spans"]
    if (
        not spans
        or spans[0]["raw_start"] != 0
        or spans[-1]["raw_end"] != len(raw)
        or spans[0]["normalized_start"] != 0
        or spans[-1]["normalized_end"] != len(text)
        or any(
            raw[s["raw_start"] : s["raw_end"]]
            != text[s["normalized_start"] : s["normalized_end"]]
            for s in spans
        )
    ):
        errors.append(error("CNS-NORM-LOSSLESS_ROUNDTRIP", "NORMALIZATION_NOT_LOSSLESS", "/raw_to_normalized_spans"))
    if normalized["request_id"] != request["request_id"] or normalized["request_sha256"] != canonical_sha(request):
        errors.append(error("CNS-NORM-REQUEST_BINDING", "INPUT_HASH_MISMATCH", "/request_sha256"))
    return ordered(errors)


def spans_in_ast(ast: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    values: list[tuple[str, dict[str, Any]]] = []
    for group in ("nodes", "surface_mentions", "assertion_markers"):
        for index, item in enumerate(ast[group]):
            values.append((f"/{group}/{index}/source_span", item["source_span"]))
            if group == "nodes" and item.get("operator_span") is not None:
                values.append((f"/{group}/{index}/operator_span", item["operator_span"]))
    return values


def validate_shared_argument_integrity(ast: dict[str, Any]) -> list[dict[str, str]]:
    """Validate the sole authorized S1 shared-argument edge shape."""
    nodes = ast.get("nodes", [])
    by_id = {node.get("node_id"): node for node in nodes}
    errors: list[dict[str, str]] = []
    for index, owner in enumerate(nodes):
        target_id = owner.get("shared_left_argument_node_id")
        if target_id is None:
            if owner.get("node_kind") == "CONTRAST" and len(owner.get("child_node_ids", [])) != 2:
                errors.append(error("CNS-AST-SHARED-ARGUMENT-INTEGRITY", "SHARED_ARGUMENT_INVALID", f"/nodes/{index}"))
            continue
        target = by_id.get(target_id)
        parent = by_id.get(owner.get("parent_node_id"))
        children = [by_id.get(value) for value in owner.get("child_node_ids", [])]
        parent_children = [
            by_id.get(value) for value in parent.get("child_node_ids", [])
        ] if parent is not None else []
        antecedent_children = [
            child for child in parent_children
            if child is not None
            and child.get("scope_role") == "CONDITION_ANTECEDENT"
        ]
        structurally_valid = (
            owner.get("node_kind") == "CONTRAST"
            and parent is not None
            and parent.get("node_kind") == "CONDITION"
            and owner.get("scope_role") == "CONDITION_CONSEQUENT"
            and owner.get("node_id") in parent.get("child_node_ids", [])
            and target is not None
            and target.get("node_kind") == "PROPOSITION"
            and target.get("scope_role") == "CONDITION_ANTECEDENT"
            and target.get("parent_node_id") == parent.get("node_id")
            and target_id in parent.get("child_node_ids", [])
            and len(antecedent_children) == 1
            and antecedent_children[0].get("node_id") == target_id
            and target_id != owner.get("node_id")
            and len(children) == 1
            and children[0] is not None
            and children[0].get("scope_role") == "CONTRAST_RIGHT"
            and target.get("source_span", {}).get("end_char", 0)
                <= owner.get("source_span", {}).get("start_char", -1)
            and not any(child and child.get("scope_role") == "CONTRAST_LEFT" for child in children)
            and "shared_left_argument_node_id" not in target
        )
        # The antecedent must have one semantic realization in the complete
        # Clause AST. Exact source coordinates plus PROPOSITION kind identify
        # the realization; equal text at another position remains legal.
        descendants: set[str] = set()
        pending = list(owner.get("child_node_ids", []))
        while pending:
            current_id = pending.pop()
            if current_id in descendants:
                structurally_valid = False
                break
            descendants.add(current_id)
            current = by_id.get(current_id)
            if current:
                pending.extend(current.get("child_node_ids", []))
        structurally_valid = structurally_valid and target_id not in descendants
        if target is not None:
            target_span = target.get("source_span")
            matching_realizations = [
                node for node in nodes
                if node.get("node_kind") == "PROPOSITION"
                and node.get("source_span") == target_span
            ]
            structurally_valid = (
                structurally_valid
                and len(matching_realizations) == 1
                and matching_realizations[0].get("node_id") == target_id
            )
        if not structurally_valid:
            errors.append(error("CNS-AST-SHARED-ARGUMENT-INTEGRITY", "SHARED_ARGUMENT_INVALID", f"/nodes/{index}/shared_left_argument_node_id"))
    return errors


def validate_s1(
    ast: dict[str, Any],
    normalized: dict[str, Any],
    alias_authority: dict[str, Any] | None = None,
    negation_authority: dict[str, Any] | None = None,
    scope_authority_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not schema_valid("clause-ast-schema-candidate.yml", ast):
        if any(
            "shared_left_argument_node_id" in node
            or (node.get("node_kind") == "CONTRAST" and len(node.get("child_node_ids", [])) != 2)
            for node in ast.get("nodes", [])
        ):
            errors.append(error("CNS-AST-SHARED-ARGUMENT-INTEGRITY", "SHARED_ARGUMENT_INVALID", "/"))
        else:
            errors.append(error("CNS-AST-REF_INTEGRITY", "DANGLING_REFERENCE", "/"))
    nodes = ast["nodes"]
    node_ids = {item["node_id"] for item in nodes}
    mention_ids = {item["surface_mention_id"] for item in ast["surface_mentions"]}
    marker_ids = {item["marker_id"] for item in ast["assertion_markers"]}
    attachment_ids = {item["attachment_set_id"] for item in ast["attachment_sets"]}
    roots = [item for item in nodes if item["node_kind"] == "ROOT" and item["parent_node_id"] is None]
    if len(roots) != 1 or ast["root_node_id"] not in node_ids:
        errors.append(error("CNS-AST-SINGLE_ROOT", "MULTIPLE_ROOTS", "/nodes"))
    id_lists = [node_ids, mention_ids, marker_ids, attachment_ids]
    if sum(map(len, id_lists)) != len(set().union(*id_lists)):
        errors.append(error("CNS-AST-ID_UNIQUE", "DUPLICATE_ID", "/"))
    valid_ids = set().union(*id_lists)
    dangling = False
    for item in nodes:
        dangling |= item["parent_node_id"] is not None and item["parent_node_id"] not in node_ids
        dangling |= any(child not in node_ids for child in item["child_node_ids"])
        dangling |= any(marker not in marker_ids for marker in item["assertion_marker_ids"])
    for item in ast["surface_mentions"]:
        dangling |= item["containing_node_id"] not in node_ids
    for item in ast["assertion_markers"]:
        dangling |= item["containing_node_id"] not in node_ids
        dangling |= any(target not in valid_ids for target in item["scope_target_candidate_ids"])
    if dangling:
        errors.append(error("CNS-AST-REF_INTEGRITY", "DANGLING_REFERENCE", "/"))
    errors.extend(validate_shared_argument_integrity(ast))
    text = normalized["normalized_query_text"]
    alias_authority = alias_authority or load_yaml(
        REPO / "phase9/clonorchis-sinensis/p9b1q/query-interpreter-config.yml"
    )
    aliases = alias_authority.get("entity_alias_extensions", {})
    for index, mention in enumerate(ast["surface_mentions"]):
        for entity_id in mention["candidate_entity_ids"]:
            registered_aliases = aliases.get(entity_id)
            surface = mention["normalized_surface"]
            if mention["source_span"]["text"] != surface or not registered_aliases or surface not in registered_aliases:
                errors.append(error("CNS-AST-REF_INTEGRITY", "DANGLING_REFERENCE", f"/surface_mentions/{index}/candidate_entity_ids"))
                break
    for pointer, span in spans_in_ast(ast):
        if span["start_char"] >= span["end_char"]:
            errors.append(error("CNS-AST-SPAN_ORDER", "SPAN_ORDER_INVALID", pointer))
        elif text[span["start_char"] : span["end_char"]] != span["text"]:
            errors.append(error("CNS-AST-SPAN_TEXT_MATCH", "SPAN_TEXT_MISMATCH", pointer))
    for index, item in enumerate(ast["attachment_sets"]):
        if item["status"] == "UNIQUE" and len(item["candidate_governor_ids"]) != 1:
            errors.append(error("CNS-AST-UNIQUE_ATTACHMENT_CARDINALITY", "ATTACHMENT_CARDINALITY_INVALID", f"/attachment_sets/{index}"))
        if item["status"] == "UNRESOLVED" and len(item["candidate_governor_ids"]) < 2:
            errors.append(error("CNS-AST-UNIQUE_ATTACHMENT_CARDINALITY", "ATTACHMENT_CARDINALITY_INVALID", f"/attachment_sets/{index}"))
    node_spans = [item["source_span"] for item in nodes]
    if any(
        (a["start_char"] < b["start_char"] < a["end_char"] < b["end_char"])
        or (b["start_char"] < a["start_char"] < b["end_char"] < a["end_char"])
        for a, b in itertools.combinations(node_spans, 2)
    ):
        errors.append(error("CNS-AST-NONCROSSING", "GRAPH_CYCLE", "/nodes"))
    if not dangling:
        for index, item in enumerate(ast["assertion_markers"]):
            if item["scope_status"] == "UNIQUE" and len(item["scope_target_candidate_ids"]) != 1:
                errors.append(error("CNS-AST-SCOPE_TARGET_INTEGRITY", "SCOPE_TARGET_INVALID", f"/assertion_markers/{index}"))
            if item["scope_status"] == "UNRESOLVED" and len(item["scope_target_candidate_ids"]) < 2:
                errors.append(error("CNS-AST-SCOPE_TARGET_INTEGRITY", "SCOPE_TARGET_INVALID", f"/assertion_markers/{index}"))
    if not errors or scope_authority_records is not None:
        errors.extend(
            negation_semantic.validate_surface_scope_target(
                ast,
                normalized,
                negation_authority or load_yaml(NEGATION_AUTHORITY),
                scope_authority_records,
            )
        )
    return ordered(errors)


def validate_s2(
    frame: dict[str, Any],
    normalized: dict[str, Any],
    ast: dict[str, Any] | None = None,
    query_interpreter_config: dict[str, Any] | None = None,
    entity_ontology: dict[str, Any] | None = None,
    event_mapping: dict[str, Any] | None = None,
    diagnostic_argument_binding: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not schema_valid("event-frame-schema-candidate.yml", frame):
        errors.append(error("CNS-EF-REF_INTEGRITY", "DANGLING_REFERENCE", "/"))
    ast = ast or {}
    query_interpreter_config = query_interpreter_config or load_yaml(
        QUERY_INTERPRETER_CONFIG
    )
    entity_ontology = entity_ontology or load_yaml(REPO / "schema/entity-types.yml")
    event_mapping = event_mapping or load_json(FIXTURES / "authority-event-relation-mapping.json")
    diagnostic_binding_missing = not isinstance(diagnostic_argument_binding, dict) or not diagnostic_argument_binding
    raw_frame_ids = [item["frame_id"] for item in frame["frames"]]
    raw_specimen_ids = [item["specimen_slot_id"] for item in frame["specimen_slots"]]
    raw_slot_ids = [
        slot["slot_id"]
        for item in frame["frames"]
        for slot in item["participant_slots"]
    ]
    raw_reference_ids = [
        item["reference_hypothesis_id"] for item in frame["reference_hypotheses"]
    ]
    raw_override_ids = [
        item["override_hypothesis_id"] for item in frame["override_hypotheses"]
    ]
    raw_global_ids = (
        raw_frame_ids
        + raw_specimen_ids
        + raw_slot_ids
        + raw_reference_ids
        + raw_override_ids
    )
    frame_ids = set(raw_frame_ids)
    specimen_ids = set(raw_specimen_ids)
    slot_ids = set(raw_slot_ids)
    reference_ids = set(raw_reference_ids)
    override_ids = set(raw_override_ids)
    if len(raw_global_ids) != len(set(raw_global_ids)):
        errors.append(error("CNS-EF-ID_UNIQUE", "DUPLICATE_ID", "/"))
    dangling = False
    for item in frame["frames"]:
        binding = item.get("diagnostic_binding")
        if binding:
            dangling |= binding["method_slot_id"] not in slot_ids
            dangling |= binding["specimen_slot_id"] not in specimen_ids
            dangling |= any(target not in slot_ids for target in binding["target_slot_ids"])
        identity = item["normalized_identity"]
        for key in ("actor_slot_ids", "target_slot_ids", "anatomical_site_slot_ids"):
            dangling |= any(target not in slot_ids for target in identity[key])
        dangling |= identity["method_slot_id"] is not None and identity["method_slot_id"] not in slot_ids
        dangling |= any(target not in specimen_ids for target in identity["specimen_slot_ids"])
    ast_ids_all = {
        item[key]
        for collection, key in (("nodes", "node_id"), ("surface_mentions", "surface_mention_id"))
        for item in ast.get(collection, [])
    }
    for reference in frame["reference_hypotheses"]:
        dangling |= reference["anaphor_source_id"] not in ast_ids_all
        dangling |= (
            reference["anaphor_frame_id"] is not None
            and reference["anaphor_frame_id"] not in frame_ids
        )
        dangling |= any(candidate not in ast_ids_all | frame_ids | slot_ids for candidate in reference["candidate_referent_ids"])
    for override in frame["override_hypotheses"]:
        dangling |= override["override_ast_node_id"] not in ast_ids_all
        dangling |= any(candidate not in frame_ids for candidate in override["earlier_frame_ids"] + override["later_frame_ids"])
    if dangling:
        errors.append(error("CNS-EF-REF_INTEGRITY", "DANGLING_REFERENCE", "/frames"))
    for fi, item in enumerate(frame["frames"]):
        local_slots = {slot["slot_id"]: slot for slot in item["participant_slots"]}
        for si, slot in enumerate(item["participant_slots"]):
            domain = slot["domain"]
            if slot["binding_status"] == "FIXED" and (len(domain["entity_ids"]) != 1 or len(domain["entity_types"]) != 1):
                errors.append(error("CNS-EF-NONEMPTY_FIXED_DOMAIN", "EMPTY_FIXED_DOMAIN", f"/frames/{fi}/participant_slots/{si}/domain"))
            if slot["binding_status"] == "COMPETING" and len(domain["entity_ids"]) < 2:
                errors.append(error("CNS-EF-NONEMPTY_FIXED_DOMAIN", "EMPTY_FIXED_DOMAIN", f"/frames/{fi}/participant_slots/{si}/domain"))
            prefix_by_type = {name: config["id_prefix"] for name, config in entity_ontology["entity_types"].items()}
            if any(
                not any(entity_id.startswith(f"{prefix_by_type.get(entity_type, '__missing__')}.") for entity_type in domain["entity_types"])
                for entity_id in domain["entity_ids"]
            ):
                errors.append(error("CNS-EF-SLOT_TYPE", "SLOT_TYPE_MISMATCH", f"/frames/{fi}/participant_slots/{si}/domain"))
            if ast:
                ast_mentions = {
                    mention["surface_mention_id"]: mention
                    for mention in ast.get("surface_mentions", [])
                }
                licensed_ids = {
                    entity_id
                    for source_id in slot["source_ids"]
                    for entity_id in ast_mentions.get(source_id, {}).get("candidate_entity_ids", [])
                }
                if set(domain["entity_ids"]) - licensed_ids:
                    errors.append(error("CNS-EF-SLOT_TYPE", "SLOT_TYPE_MISMATCH", f"/frames/{fi}/participant_slots/{si}/domain"))
        identity = item["normalized_identity"]
        role_bindings = {
            "actor_slot_ids": "ACTOR",
            "target_slot_ids": "TARGET",
            "anatomical_site_slot_ids": "LOCATION",
        }
        identity_role_error = any(
            local_slots.get(slot_id, {}).get("semantic_role") != expected_role
            for field, expected_role in role_bindings.items()
            for slot_id in identity[field]
        )
        if identity["method_slot_id"] is not None:
            identity_role_error |= (
                local_slots.get(identity["method_slot_id"], {}).get("semantic_role")
                != "METHOD"
            )
        identity_dimensions = [
            set(identity["actor_slot_ids"]),
            set(identity["target_slot_ids"]),
            set(identity["anatomical_site_slot_ids"]),
            {identity["method_slot_id"]} if identity["method_slot_id"] else set(),
        ]
        identity_role_error |= any(
            left & right
            for index, left in enumerate(identity_dimensions)
            for right in identity_dimensions[index + 1 :]
        )
        if identity_role_error:
            errors.append(error("CNS-EF-IDENTITY_CONSISTENCY", "EVENT_IDENTITY_MISMATCH", f"/frames/{fi}/normalized_identity"))
        if identity["event_type_domain"] != item["event_type_domain"]:
            errors.append(error("CNS-EF-IDENTITY_CONSISTENCY", "EVENT_IDENTITY_MISMATCH", f"/frames/{fi}/normalized_identity/event_type_domain"))
        event_types = item["event_type_domain"]
        mapping_types = event_mapping["event_mapping"]
        if any(event_type not in mapping_types for event_type in event_types):
            errors.append(error("CNS-EF-IDENTITY_CONSISTENCY", "EVENT_IDENTITY_MISMATCH", f"/frames/{fi}/event_type_domain"))
        binding = item.get("diagnostic_binding")
        is_diagnostic = all(mapping_types[event_type]["event_class"] == "DIAGNOSTIC" for event_type in event_types if event_type in mapping_types)
        if is_diagnostic != (binding is not None):
            errors.append(error("CNS-EF-DIAGNOSTIC_BINDING", "DIAGNOSTIC_BINDING_INVALID", f"/frames/{fi}/diagnostic_binding"))
        if binding is not None:
            method = local_slots.get(binding["method_slot_id"])
            targets = [local_slots.get(target) for target in binding["target_slot_ids"]]
            if (
                method is None
                or method["semantic_role"] != "METHOD"
                or any(target is None or target["semantic_role"] != "TARGET" for target in targets)
                or binding["method_slot_id"] != identity["method_slot_id"]
                or binding["target_slot_ids"] != identity["target_slot_ids"]
                or binding["specimen_slot_id"] not in identity["specimen_slot_ids"]
            ):
                errors.append(error("CNS-EF-DIAGNOSTIC_BINDING", "DIAGNOSTIC_BINDING_INVALID", f"/frames/{fi}/diagnostic_binding"))
        if ast:
            ast_ids = {node["node_id"] for node in ast["nodes"]}
            if any(source not in ast_ids for source in item["source_ast_node_ids"] + item["assertion"]["governing_ast_node_ids"]):
                errors.append(error("CNS-EF-REF_INTEGRITY", "DANGLING_REFERENCE", f"/frames/{fi}"))
    fixed_events = _expected_fixed_events({"EVENT_FRAME": frame})
    for index, reference in enumerate(frame["reference_hypotheses"]):
        expected = 1 if reference["status"] == "UNIQUE" else 2
        if len(reference["candidate_referent_ids"]) < expected or len(reference["identity_relation_domain"]) < expected:
            errors.append(error("CNS-EF-REFERENCE_DOMAIN", "REFERENCE_DOMAIN_INVALID", f"/reference_hypotheses/{index}"))
            continue
        if reference["status"] == "UNIQUE" and reference["anaphor_frame_id"] is not None:
            anchor = fixed_events.get(reference["anaphor_frame_id"])
            referent = fixed_events.get(reference["candidate_referent_ids"][0])
            relation = reference["identity_relation_domain"][0]
            observed = None if anchor is None or referent is None else (
                "SAME_EVENT" if same_event(anchor, referent) else "DISTINCT_EVENT"
            )
            if observed != relation:
                errors.append(error("CNS-EF-REFERENCE_DOMAIN", "REFERENCE_DOMAIN_INVALID", f"/reference_hypotheses/{index}"))
    for index, override in enumerate(frame["override_hypotheses"]):
        expected = 1 if override["status"] == "UNIQUE" else 2 if override["status"] == "UNRESOLVED" else 1
        if len(override["overridden_dimension_domain"]) < expected or set(override["earlier_frame_ids"]) & set(override["later_frame_ids"]):
            errors.append(error("CNS-EF-OVERRIDE_DOMAIN", "OVERRIDE_DOMAIN_INVALID", f"/override_hypotheses/{index}"))
            continue
        if override["status"] == "UNIQUE":
            earlier = fixed_events.get(override["earlier_frame_ids"][0])
            later = fixed_events.get(override["later_frame_ids"][0])
            dimension = override["overridden_dimension_domain"][0]
            if earlier is None or later is None or not override_pair_valid(earlier, later, dimension):
                errors.append(error("CNS-EF-OVERRIDE_DOMAIN", "OVERRIDE_DOMAIN_INVALID", f"/override_hypotheses/{index}"))
    text = normalized["normalized_query_text"]
    specimen_surface = {"STOOL": {"粪便", "粪样", "大便"}}
    for si, specimen in enumerate(frame["specimen_slots"]):
        for pi, span in enumerate(specimen["source_spans"]):
            exact_slice = text[span["start_char"] : span["end_char"]] == span["text"]
            allowed_surface = any(
                span["text"] in specimen_surface.get(code, {span["text"]})
                for code in specimen["specimen_code_domain"]
            )
            if not exact_slice or not allowed_surface:
                errors.append(error("CNS-EF-SPECIMEN_SOURCE", "SPECIMEN_SOURCE_MISSING", f"/specimen_slots/{si}/source_spans/{pi}"))
    if diagnostic_binding_missing:
        errors.append(
            error(
                "CNS-EF-DIAGNOSTIC-ROLE-DERIVATION",
                "DIAGNOSTIC_ROLE_DERIVATION_INVALID",
                "/diagnostic_predicate_argument_binding",
            )
        )
    elif any(
        item.get("event_type_domain") == ["DIAGNOSTIC_FINDING"]
        for item in frame.get("frames", [])
    ):
        errors.extend(
            validate_diagnostic_role_derivation(
                frame,
                normalized,
                ast,
                query_interpreter_config,
                event_mapping,
                diagnostic_argument_binding,
            )
        )
    return ordered(errors)


def _ast_scope_node_ids(ast: dict[str, Any], roots: list[str]) -> set[str]:
    children = {
        node["node_id"]: node.get("child_node_ids", [])
        for node in ast.get("nodes", [])
    }
    result: set[str] = set()
    pending = list(roots)
    while pending:
        node_id = pending.pop()
        if node_id in result:
            continue
        result.add(node_id)
        pending.extend(children.get(node_id, []))
    return result


def _diagnostic_scope(
    item: dict[str, Any], ast: dict[str, Any]
) -> tuple[set[str], list[dict[str, Any]], list[dict[str, Any]]]:
    node_ids = _ast_scope_node_ids(ast, item.get("source_ast_node_ids", []))
    nodes = [
        node for node in ast.get("nodes", []) if node.get("node_id") in node_ids
    ]
    mentions = [
        mention
        for mention in ast.get("surface_mentions", [])
        if mention.get("containing_node_id") in node_ids
    ]
    return node_ids, nodes, mentions


def _cue_is_in_nodes(cue: str, nodes: list[dict[str, Any]]) -> bool:
    return any(cue in node.get("source_span", {}).get("text", "") for node in nodes)


def _minimal_cue_node_ids(
    ast: dict[str, Any],
    scope_node_ids: set[str],
    cues: list[str],
) -> set[str]:
    """Return the structurally most local proposition scopes bearing a cue."""
    candidates = {
        node["node_id"]
        for node in ast.get("nodes", [])
        if node.get("node_id") in scope_node_ids
        and any(
            cue in node.get("source_span", {}).get("text", "")
            for cue in cues
            if isinstance(cue, str) and cue
        )
    }
    return {
        node_id
        for node_id in candidates
        if not (
            (_ast_scope_node_ids(ast, [node_id]) - {node_id}) & candidates
        )
    }


def _mention_groups_for_token(
    token: str,
    mentions: list[dict[str, Any]],
) -> dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]]:
    entity_type = "diagnostic_method" if token == "method_entity_id" else token
    grouped: dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]] = {}
    for mention in mentions:
        if entity_type not in mention.get("candidate_entity_types", []):
            continue
        key = (
            tuple(sorted(mention.get("candidate_entity_ids", []))),
            tuple(sorted(mention.get("candidate_entity_types", []))),
        )
        grouped.setdefault(key, set()).add(mention["surface_mention_id"])
    return grouped


def _slot_key(slot: dict[str, Any], role: str | None = None) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    domain = slot["domain"]
    return (
        role or slot["semantic_role"],
        tuple(sorted(domain["entity_ids"])),
        tuple(sorted(domain["entity_types"])),
    )


def validate_diagnostic_role_derivation(
    frame: dict[str, Any],
    normalized: dict[str, Any],
    ast: dict[str, Any],
    query_interpreter_config: dict[str, Any],
    event_mapping: dict[str, Any],
    diagnostic_argument_binding: dict[str, Any],
) -> list[dict[str, str]]:
    """Validate exact diagnostic-role provenance from independent S2 authority.

    The binding object is outside the candidate Event Frame. Candidate slot
    source_ids are therefore only the actual claim being compared and can
    never define or enlarge the expected occurrence set.
    """
    errors: list[dict[str, str]] = []
    def fail(pointer: str) -> None:
        errors.append(
            error(
                "CNS-EF-DIAGNOSTIC-ROLE-DERIVATION",
                "DIAGNOSTIC_ROLE_DERIVATION_INVALID",
                pointer,
            )
        )

    mapping = event_mapping.get("event_mapping", {}).get("DIAGNOSTIC_FINDING", {})
    catalog = mapping.get("diagnostic_participant_role_catalog")
    predicates = mapping.get("predicates", {})
    if (
        mapping.get("required_role_derivation")
        != "FORMAL_DIAGNOSTIC_ROLE_CATALOG_ONLY"
        or not isinstance(catalog, dict)
    ):
        fail("/event_mapping/DIAGNOSTIC_FINDING/diagnostic_participant_role_catalog")
        return errors

    direction_invalid = False
    for predicate, sides in catalog.items():
        formal = predicates.get(predicate)
        if not isinstance(formal, dict) or not isinstance(sides, dict):
            direction_invalid = True
            continue
        for side, direction_field in (("subject", "subject_from"), ("object", "object_from")):
            rule = sides.get(side)
            direction = formal.get(direction_field)
            if (
                not isinstance(rule, dict)
                or direction != [rule.get("source_token")]
                or rule.get("materialization") != "REQUIRED_WHEN_EXPLICITLY_BOUND"
                or rule.get("semantic_role")
                not in {"ACTOR", "TARGET", "METHOD"}
                or rule.get("cardinality")
                not in {
                    "EXACTLY_ONCE_PER_CANONICAL_PARTICIPANT",
                    "EXACTLY_ONE_METHOD_SLOT_PER_EVENT_METHOD_DOMAIN",
                }
            ):
                direction_invalid = True
    if set(catalog) != set(predicates) or direction_invalid:
        fail("/event_mapping/DIAGNOSTIC_FINDING/diagnostic_participant_role_catalog")

    if not schema_valid(
        "diagnostic-predicate-argument-binding-schema-candidate.yml",
        diagnostic_argument_binding,
    ):
        fail("/diagnostic_predicate_argument_binding")
        return errors

    predicate_cues = query_interpreter_config.get("predicate_cues", {})
    has_expressed_diagnostic_predicate = any(
        _minimal_cue_node_ids(
            ast,
            _diagnostic_scope(item, ast)[0],
            predicate_cues.get(predicate, [])
            if isinstance(predicate_cues.get(predicate, []), list)
            else [],
        )
        for item in frame.get("frames", [])
        if item.get("event_type_domain") == ["DIAGNOSTIC_FINDING"]
        for predicate in catalog
    )
    if not has_expressed_diagnostic_predicate:
        return errors

    default_query_config = load_yaml(QUERY_INTERPRETER_CONFIG)
    query_config_hash = (
        sha_bytes(QUERY_INTERPRETER_CONFIG.read_bytes())
        if query_interpreter_config == default_query_config
        else canonical_sha(query_interpreter_config)
    )
    identity_invalid = (
        diagnostic_argument_binding.get("binding_scope") != "DIAGNOSTIC_ONLY"
        or diagnostic_argument_binding.get("binding_contract_sha256")
        != sha_bytes(DIAGNOSTIC_ARGUMENT_BINDING_CONTRACT.read_bytes())
        or diagnostic_argument_binding.get("query_interpreter_config_sha256")
        != query_config_hash
        or diagnostic_argument_binding.get("event_relation_mapping_sha256")
        != canonical_sha(event_mapping)
    )
    request_bindings = diagnostic_argument_binding.get("request_bindings", [])
    request_binding = request_bindings[0] if len(request_bindings) == 1 else None
    if (
        request_binding is None
        or request_binding.get("request_id") != normalized.get("request_id")
        or request_binding.get("normalized_request_sha256") != canonical_sha(normalized)
        or request_binding.get("clause_ast_sha256") != canonical_sha(ast)
    ):
        identity_invalid = True
    if request_binding is not None and (
        request_binding.get("normalized_request_sha256") != canonical_sha(normalized)
        or request_binding.get("clause_ast_sha256") != canonical_sha(ast)
    ):
        identity_invalid = True
    if identity_invalid:
        fail("/diagnostic_predicate_argument_binding")
        return errors

    mentions_by_id = {
        mention["surface_mention_id"]: mention
        for mention in ast.get("surface_mentions", [])
    }
    ast_node_ids = {node["node_id"] for node in ast.get("nodes", [])}

    def domain_key(
        source_ids: list[str], expected_type: str
    ) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
        mentions = [mentions_by_id.get(source_id) for source_id in source_ids]
        if not source_ids or any(mention is None for mention in mentions):
            return None
        keys = {
            (
                tuple(sorted(mention.get("candidate_entity_ids", []))),
                tuple(sorted(mention.get("candidate_entity_types", []))),
            )
            for mention in mentions
            if mention is not None
        }
        if len(keys) != 1:
            return None
        entity_ids, entity_types = next(iter(keys))
        if expected_type not in entity_types or not entity_ids:
            return None
        return entity_ids, entity_types

    all_contexts = (
        request_binding.get("diagnostic_contexts", [])
        if request_binding is not None
        else []
    )
    raw_context_ids = [item.get("diagnostic_context_id") for item in all_contexts]
    raw_occurrence_ids = [
        occurrence.get("predicate_occurrence_id")
        for context in all_contexts
        for occurrence in context.get("predicate_occurrences", [])
    ]
    raw_method_binding_ids = [
        method.get("method_entity_binding_id")
        for context in all_contexts
        for method in context.get("method_entity_bindings", [])
    ]
    if any(
        len(values) != len(set(values))
        for values in (raw_context_ids, raw_occurrence_ids, raw_method_binding_ids)
    ):
        fail("/diagnostic_predicate_argument_binding/request_bindings")
        return errors

    # Validate the complete supplied authority object before consulting any
    # candidate Event Frame.  No unselected context, occurrence, side, method
    # binding, node, or mention may escape referential-integrity validation.
    authority_invalid = False
    for context in all_contexts:
        governing_node_ids = set(context.get("governing_ast_node_ids", []))
        if not governing_node_ids or not governing_node_ids <= ast_node_ids:
            authority_invalid = True
            continue
        declared_pairs = {
            (
                occurrence.get("canonical_predicate"),
                occurrence.get("proposition_node_id"),
            )
            for occurrence in context.get("predicate_occurrences", [])
        }
        formally_expressed_pairs = {
            (predicate, node_id)
            for predicate in catalog
            for node_id in _minimal_cue_node_ids(
                ast,
                governing_node_ids,
                predicate_cues.get(predicate, [])
                if isinstance(predicate_cues.get(predicate, []), list)
                else [],
            )
        }
        if declared_pairs != formally_expressed_pairs or {
            node_id for _, node_id in declared_pairs
        } != governing_node_ids:
            authority_invalid = True

        method_bindings = {
            method.get("method_entity_binding_id"): method
            for method in context.get("method_entity_bindings", [])
        }
        referenced_method_binding_ids: set[str] = set()
        for method in method_bindings.values():
            source_ids = method.get("surface_mention_ids", [])
            key = domain_key(source_ids, "diagnostic_method")
            if (
                method.get("binding_state") != "BOUND"
                or key is None
                or key[0] != (method.get("method_entity_id"),)
            ):
                authority_invalid = True

        for occurrence in context.get("predicate_occurrences", []):
            predicate = occurrence.get("canonical_predicate")
            proposition_node_id = occurrence.get("proposition_node_id")
            if (
                predicate not in catalog
                or proposition_node_id not in governing_node_ids
                or proposition_node_id not in ast_node_ids
            ):
                authority_invalid = True
                continue
            sides = {
                side.get("argument_side"): side
                for side in occurrence.get("argument_bindings", [])
            }
            if set(sides) != {"SUBJECT", "OBJECT"}:
                authority_invalid = True
                continue
            proposition_scope = _ast_scope_node_ids(ast, [proposition_node_id])
            for side_name, catalog_side in (("SUBJECT", "subject"), ("OBJECT", "object")):
                side = sides[side_name]
                rule = catalog[predicate][catalog_side]
                source_ids = side.get("surface_mention_ids", [])
                expected_type = (
                    "diagnostic_method"
                    if rule["source_token"] == "method_entity_id"
                    else rule["source_token"]
                )
                key = domain_key(source_ids, expected_type)
                method_binding_id = side.get("method_entity_binding_id")
                if (
                    side.get("binding_state") != "BOUND"
                    or key is None
                    or any(
                        mentions_by_id[source_id].get("containing_node_id")
                        not in proposition_scope
                        for source_id in source_ids
                    )
                ):
                    authority_invalid = True
                    continue
                if rule["source_token"] == "method_entity_id":
                    method_authority = method_bindings.get(method_binding_id)
                    if (
                        method_authority is None
                        or key[0] != (method_authority.get("method_entity_id"),)
                    ):
                        authority_invalid = True
                    elif isinstance(method_binding_id, str):
                        referenced_method_binding_ids.add(method_binding_id)
                elif method_binding_id is not None:
                    authority_invalid = True
        if set(method_bindings) != referenced_method_binding_ids:
            authority_invalid = True

    if authority_invalid:
        fail("/diagnostic_predicate_argument_binding/request_bindings")
        return errors

    for frame_index, item in enumerate(frame.get("frames", [])):
        if item.get("event_type_domain") != ["DIAGNOSTIC_FINDING"]:
            continue
        pointer = f"/frames/{frame_index}/participant_slots"
        binding = item.get("diagnostic_binding")
        if not isinstance(binding, dict):
            continue
        slots = item.get("participant_slots", [])
        scope_node_ids, _, _ = _diagnostic_scope(item, ast)
        expressed_pairs = {
            (predicate, node_id)
            for predicate in catalog
            for node_id in _minimal_cue_node_ids(
                ast,
                scope_node_ids,
                predicate_cues.get(predicate, [])
                if isinstance(predicate_cues.get(predicate, []), list)
                else [],
            )
        }
        matching_contexts = [
            context
            for context in all_contexts
            if set(context.get("governing_ast_node_ids", [])) <= scope_node_ids
            and {
                (
                    occurrence.get("canonical_predicate"),
                    occurrence.get("proposition_node_id"),
                )
                for occurrence in context.get("predicate_occurrences", [])
            }
            == expressed_pairs
        ]
        if not expressed_pairs:
            continue
        if len(matching_contexts) != 1:
            fail(pointer)
            continue
        context = matching_contexts[0]
        if any(
            node_id not in ast_node_ids
            for node_id in context.get("governing_ast_node_ids", [])
        ):
            fail(pointer)
            continue

        expected: dict[
            tuple[str, tuple[str, ...], tuple[str, ...]], set[str]
        ] = {}

        def add_expected(
            key: tuple[str, tuple[str, ...], tuple[str, ...]],
            source_ids: set[str],
        ) -> None:
            expected.setdefault(key, set()).update(source_ids)

        method_bindings = {
            method["method_entity_binding_id"]: method
            for method in context.get("method_entity_bindings", [])
        }
        binding_invalid = False
        for method in method_bindings.values():
            source_ids = method.get("surface_mention_ids", [])
            key = domain_key(source_ids, "diagnostic_method")
            if (
                method.get("binding_state") != "BOUND"
                or key is None
                or tuple([method.get("method_entity_id")]) != key[0]
            ):
                binding_invalid = True
            elif key is not None:
                add_expected(("METHOD", key[0], key[1]), set(source_ids))

        for occurrence in context.get("predicate_occurrences", []):
            predicate = occurrence.get("canonical_predicate")
            predicate_node_id = occurrence.get("proposition_node_id")
            if (predicate, predicate_node_id) not in expressed_pairs:
                binding_invalid = True
                continue
            sides = {
                side.get("argument_side"): side
                for side in occurrence.get("argument_bindings", [])
            }
            if set(sides) != {"SUBJECT", "OBJECT"}:
                binding_invalid = True
                continue
            proposition_scope = _ast_scope_node_ids(ast, [predicate_node_id])
            for side_name, catalog_side in (("SUBJECT", "subject"), ("OBJECT", "object")):
                side = sides[side_name]
                rule = catalog[predicate][catalog_side]
                source_ids = side.get("surface_mention_ids", [])
                if side.get("binding_state") != "BOUND":
                    binding_invalid = True
                    continue
                expected_type = (
                    "diagnostic_method"
                    if rule["source_token"] == "method_entity_id"
                    else rule["source_token"]
                )
                key = domain_key(source_ids, expected_type)
                method_binding_id = side.get("method_entity_binding_id")
                if rule["source_token"] == "method_entity_id":
                    method_authority = method_bindings.get(method_binding_id)
                    if (
                        key is None
                        or method_authority is None
                        or key[0] != (method_authority.get("method_entity_id"),)
                    ):
                        binding_invalid = True
                        continue
                else:
                    if method_binding_id is not None or key is None:
                        binding_invalid = True
                        continue
                    if any(
                        mentions_by_id[source_id].get("containing_node_id")
                        not in proposition_scope
                        for source_id in source_ids
                    ):
                        binding_invalid = True
                        continue
                assert key is not None
                add_expected((rule["semantic_role"], key[0], key[1]), set(source_ids))

        actual: dict[
            tuple[str, tuple[str, ...], tuple[str, ...]], tuple[str, set[str]]
        ] = {}
        duplicate_key = False
        source_roles: dict[str, set[str]] = {}
        for slot in slots:
            key = _slot_key(slot)
            if key in actual:
                duplicate_key = True
            else:
                actual[key] = (slot["slot_id"], set(slot["source_ids"]))
            for source_id in slot["source_ids"]:
                source_roles.setdefault(source_id, set()).add(slot["semantic_role"])

        actual_sources = {key: sources for key, (_, sources) in actual.items()}
        same_mention_conflict = any(len(roles) > 1 for roles in source_roles.values())
        if (
            binding_invalid
            or duplicate_key
            or same_mention_conflict
            or expected != actual_sources
        ):
            fail(pointer)
            continue

        identity = item["normalized_identity"]
        expected_actor_ids = {
            actual[key][0] for key in expected if key[0] == "ACTOR"
        }
        expected_target_ids = {
            actual[key][0] for key in expected if key[0] == "TARGET"
        }
        expected_method_ids = {
            actual[key][0] for key in expected if key[0] == "METHOD"
        }
        identity_invalid = (
            set(identity["actor_slot_ids"]) != expected_actor_ids
            or set(identity["target_slot_ids"]) != expected_target_ids
            or len(expected_method_ids) != 1
            or identity["method_slot_id"] not in expected_method_ids
            or binding["method_slot_id"] not in expected_method_ids
            or set(binding["target_slot_ids"]) != expected_target_ids
        )
        if identity_invalid:
            fail(f"/frames/{frame_index}/normalized_identity")
    return errors


def solution_core(typed_result: dict[str, Any]) -> dict[str, Any]:
    core = copy.deepcopy(typed_result["selected_solution"])
    core.pop("queryir_emission_record", None)
    return core


def material_ids(core: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    transforms = [
        ("resolved_mentions", "mention_key", "RM", "M"),
        ("resolved_events", "event_key", "RE", "E"),
        ("resolved_relations", "relation_key", "RR", "R"),
        ("narrative_intents", "narrative_key", "RN", "N"),
        ("semantic_roles", "role_key", "RQ", "Q"),
        ("resolved_references", "reference_key", "RREF", "REF"),
        ("resolved_overrides", "override_key", "ROV", "OVR"),
    ]
    for collection, key, prefix, output_prefix in transforms:
        for item in core[collection]:
            numeric = int(item[key][len(prefix) :])
            result.add(f"{output_prefix}{numeric:02d}")
    return result


def dag_valid(dag: dict[str, Any]) -> bool:
    nodes = {item["node_id"] for item in dag["nodes"]}
    adjacency = {node: [] for node in nodes}
    indegree = {node: 0 for node in nodes}
    for edge in dag["edges"]:
        source, target = edge["from_node_id"], edge["to_node_id"]
        if source not in nodes or target not in nodes:
            return False
        adjacency[source].append(target)
        indegree[target] += 1
    pending = [node for node in dag["topological_order"] if indegree[node] == 0]
    visited: list[str] = []
    while pending:
        node = pending.pop(0)
        if node in visited:
            continue
        visited.append(node)
        for target in adjacency[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                pending.append(target)
    return len(visited) == len(nodes)


def rooted_witness_paths_valid(emission: dict[str, Any]) -> bool:
    dag = emission["license_dag"]
    nodes = {item["node_id"]: item for item in dag["nodes"]}
    edges = {(item["from_node_id"], item["to_node_id"]) for item in dag["edges"]}
    indegree = {node: 0 for node in nodes}
    for source, target in edges:
        if source not in nodes or target not in nodes:
            return False
        indegree[target] += 1
    roots = {node for node, degree in indegree.items() if degree == 0}
    for witness in emission["minimality_witness"]["retained_object_witnesses"]:
        path = witness["license_path_node_ids"]
        if not path or path[0] not in roots:
            return False
        if any((source, target) not in edges for source, target in zip(path, path[1:])):
            return False
        if nodes[path[-1]]["semantic_object_id"] != witness["semantic_object_id"]:
            return False
    return True


def validate_core_minimality(core: dict[str, Any], emission: dict[str, Any]) -> list[str]:
    if core.get("semantic_object_set_sha256") != canonical_sha(semantic_object_set(core)):
        return ["CNS-SOLVER-HASH_BINDING"]
    mention_keys = {item["mention_key"] for item in core["resolved_mentions"]}
    relation_keys = {item["relation_key"] for item in core["resolved_relations"]}
    event_keys = {item["event_key"] for item in core["resolved_events"]}
    selector_ids = {
        entity
        for relation in core["resolved_relations"]
        for selector in (relation["subject_selector"], relation["object_selector"])
        for entity in selector["entity_ids"]
    }
    mention_entities = {item["entity_id"] for item in core["resolved_mentions"]}
    if selector_ids - mention_entities or any(
        root.startswith("RM") and root not in mention_keys
        for relation in core["resolved_relations"]
        for root in relation["root_keys"]
    ):
        return ["CNS-SOLVER-ENTITY_RESOLUTION"]
    if any(
        item["anaphor_key"] not in mention_keys | event_keys
        or item["referent_key"] not in mention_keys | event_keys
        for item in core["resolved_references"]
    ) or any(
        item["earlier_event_key"] not in event_keys
        or item["later_event_key"] not in event_keys
        for item in core["resolved_overrides"]
    ):
        return ["CNS-SOLVER-EVENT_IDENTITY"]
    if (relation_keys and not event_keys) or (event_keys and not relation_keys):
        return ["CNS-SOLVER-EVENT_RELATION_DERIVATION"]
    for item in core["semantic_roles"] + core["narrative_intents"]:
        if any(root.startswith("RR") and root not in relation_keys for root in item["root_keys"]):
            return ["CNS-SOLVER-EVENT_RELATION_DERIVATION"]
    dag_ids = {item["semantic_object_id"] for item in emission["license_dag"]["nodes"]}
    if material_ids(core) != dag_ids or not rooted_witness_paths_valid(emission):
        return ["CNS-SOLVER-LICENSE_DAG"]
    return []


def finite_solution_count(
    base_core: dict[str, Any], emission: dict[str, Any], inputs: dict[str, Any]
) -> int:
    """Enumerate all subsets and run the same semantic authorization predicate."""
    slots: list[tuple[str, int]] = []
    for collection in (
        "resolved_mentions",
        "resolved_events",
        "resolved_relations",
        "narrative_intents",
        "semantic_roles",
        "resolved_references",
        "resolved_overrides",
    ):
        slots.extend((collection, index) for index in range(len(base_core[collection])))
    satisfying = 0
    for mask in range(1 << len(slots)):
        candidate = copy.deepcopy(base_core)
        keep: dict[str, list[dict[str, Any]]] = {
            key: [] for key in (
                "resolved_mentions",
                "resolved_events",
                "resolved_relations",
                "narrative_intents",
                "semantic_roles",
                "resolved_references",
                "resolved_overrides",
            )
        }
        for bit, (collection, index) in enumerate(slots):
            if mask & (1 << bit):
                keep[collection].append(base_core[collection][index])
        candidate.update(keep)
        refresh_core_hashes(candidate)
        if not validate_semantic_authority(candidate, inputs, require_complete=True):
            satisfying += 1
    return satisfying


def validate_s3_assertion_authority(
    inputs: dict[str, Any], typed_assertions: list[dict[str, Any]]
) -> list[dict[str, str]]:
    required = ("NORMALIZED_REQUEST", "CLAUSE_AST", "EVENT_FRAME")
    if any(key not in inputs for key in required):
        return [
            error(
                "CNS-SOLVER-ASSERTION-DERIVATION",
                "ASSERTION_DERIVATION_MISMATCH",
                "/actual_input_objects",
            )
        ]
    _, errors = negation_semantic.validate_assertion_derivation(
        inputs["CLAUSE_AST"],
        inputs["NORMALIZED_REQUEST"],
        inputs["EVENT_FRAME"],
        typed_assertions,
        inputs.get("NEGATION_SURFACE_SCOPE_AUTHORITY", load_yaml(NEGATION_AUTHORITY)),
        inputs.get("SCOPE_AUTHORITY_RECORDS"),
        inputs.get("DECLARED_ASSERTION_DERIVATION"),
    )
    return errors


def validate_s3(
    typed: dict[str, Any] | None,
    inputs: dict[str, Any] | None = None,
    input_hashes: dict[str, str] | None = None,
    assertion_only: bool = False,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    inputs = inputs or {}
    if assertion_only:
        return ordered(
            validate_s3_assertion_authority(
                inputs, inputs.get("TYPED_SOLUTION_ASSERTIONS", [])
            )
        )
    if typed is None:
        return ordered(
            [
                error(
                    "CNS-SOLVER-HASH_BINDING", "INPUT_HASH_MISMATCH", "/"
                )
            ]
        )
    if not schema_valid("typed-constraint-result-schema-candidate.yml", typed):
        errors.append(error("CNS-SOLVER-HASH_BINDING", "INPUT_HASH_MISMATCH", "/"))
    input_hashes = input_hashes or {}
    registry_object = inputs.get("CONSTRAINT_REGISTRY", load_yaml(REGISTRY))
    registry_schema = inputs.get(
        "CONSTRAINT_REGISTRY_SCHEMA", load_yaml(CONSTRAINT_REGISTRY_SCHEMA)
    )
    constraint_set_schema = inputs.get(
        "CONSTRAINT_SET_SCHEMA", load_yaml(CONSTRAINT_SET_SCHEMA)
    )
    if (
        registry_schema != load_yaml(CONSTRAINT_REGISTRY_SCHEMA)
        or not schema_valid("constraint-id-registry-schema-candidate.yml", registry_object)
        or constraint_set_schema != load_yaml(CONSTRAINT_SET_SCHEMA)
    ):
        errors.append(error("CNS-SOLVER-REGISTRY_MEMBERSHIP", "UNKNOWN_CONSTRAINT_ID", "/constraint_registry"))
    registry_entries = registry_object["entries"]
    registry = {entry["id"] for entry in registry_entries}
    constraint_set = inputs.get("CONSTRAINT_SET", load_yaml(CONSTRAINT_SET))
    if not schema_valid("constraint-set-schema-candidate.yml", constraint_set):
        errors.append(error("CNS-SOLVER-REGISTRY_MEMBERSHIP", "UNKNOWN_CONSTRAINT_ID", "/constraint_set"))
    core = solution_core(typed)
    errors.extend(validate_s3_assertion_authority(inputs, core["resolved_events"]))
    unknown = set(core["satisfied_constraint_ids"]) - registry
    if unknown:
        errors.append(error("CNS-SOLVER-REGISTRY_MEMBERSHIP", "UNKNOWN_CONSTRAINT_ID", "/selected_solution/satisfied_constraint_ids"))
    if typed["status"] == "UNIQUE" and typed["solution_cardinality"] != "ONE":
        errors.append(error("CNS-SOLVER-SOLUTION_CARDINALITY", "SOLUTION_CARDINALITY_MISMATCH", "/solution_cardinality"))
    empty_unique = typed["status"] == "UNIQUE" and not any(core[key] for key in ("resolved_mentions", "resolved_events", "resolved_relations", "semantic_roles", "narrative_intents"))
    if empty_unique:
        errors.append(error("CNS-SOLVER-NONEMPTY_UNIQUE", "EMPTY_UNIQUE_SOLUTION", "/selected_solution"))
    expected_sequence = [
        entry["id"]
        for entry in registry_entries
        if entry["stage"]
        in {
            "S0_NORMALIZED_REQUEST",
            "S1_CLAUSE_AST",
            "S2_EVENT_FRAME",
            "S3_TYPED_SOLVER",
        }
    ]
    if (
        [entry["order"] for entry in registry_entries]
        != list(range(1, len(registry_entries) + 1))
        or constraint_set["selected_constraints"] != [entry["id"] for entry in registry_entries]
        or core["satisfied_constraint_ids"] != expected_sequence
    ):
        errors.append(error("CNS-SOLVER-REGISTRY_MEMBERSHIP", "UNKNOWN_CONSTRAINT_ID", "/selected_solution/satisfied_constraint_ids"))
    hash_bindings = {
        "NORMALIZED_REQUEST": "normalized_request_sha256",
        "CLAUSE_AST": "clause_ast_sha256",
        "EVENT_FRAME": "event_frame_sha256",
        "ENTITY_ONTOLOGY": "entity_ontology_sha256",
        "RELATION_ONTOLOGY": "relation_ontology_sha256",
        "PREDICATE_TYPE_MAPPING": "predicate_type_mapping_sha256",
        "EVENT_RELATION_MAPPING": "event_relation_mapping_sha256",
        "SEMANTIC_ROLE_MAPPING": "semantic_role_mapping_sha256",
        "CONSTRAINT_REGISTRY": "constraint_registry_sha256",
        "CONSTRAINT_SET": "constraint_set_sha256",
    }
    for object_kind, field in hash_bindings.items():
        if object_kind in input_hashes and typed[field] != input_hashes[object_kind]:
            errors.append(error("CNS-SOLVER-HASH_BINDING", "INPUT_HASH_MISMATCH", f"/{field}"))
    if typed["stage_validator_contract_sha256"] != sha_bytes(CONTRACT.read_bytes()):
        errors.append(error("CNS-SOLVER-HASH_BINDING", "INPUT_HASH_MISMATCH", "/stage_validator_contract_sha256"))
    if core["semantic_object_set_sha256"] != canonical_sha(semantic_object_set(core)):
        errors.append(error("CNS-SOLVER-HASH_BINDING", "INPUT_HASH_MISMATCH", "/selected_solution/semantic_object_set_sha256"))
    if core["solution_id"] != f"SOL-{core['semantic_object_set_sha256'][:24]}":
        errors.append(error("CNS-SOLVER-HASH_BINDING", "INPUT_HASH_MISMATCH", "/selected_solution/solution_id"))
    mention_by_key = {item["mention_key"]: item for item in core["resolved_mentions"]}
    core_event_by_key = {item["event_key"]: item for item in core["resolved_events"]}
    event_by_key = {item["event_key"]: item for item in core["resolved_events"]}
    relation_by_key = {item["relation_key"]: item for item in core["resolved_relations"]}
    for relation in core["resolved_relations"]:
        if any(root.startswith("RM") and root not in mention_by_key for root in relation["root_keys"]):
            errors.append(error("CNS-SOLVER-ENTITY_RESOLUTION", "SLOT_TYPE_MISMATCH", "/selected_solution/resolved_relations"))
        if any(root.startswith("RE") and root not in event_by_key for root in relation["root_keys"]):
            errors.append(error("CNS-SOLVER-EVENT_IDENTITY", "EVENT_IDENTITY_MISMATCH", "/selected_solution/resolved_relations"))
        if relation["derivation_mode"] == "DIRECT_MENTION_DERIVED":
            basis_entities = {mention_by_key[root]["entity_id"] for root in relation["root_keys"] if root in mention_by_key}
            selector_entities = set(relation["subject_selector"]["entity_ids"] + relation["object_selector"]["entity_ids"])
            if selector_entities - basis_entities or any(not root.startswith("RM") for root in relation["root_keys"]):
                errors.append(error("CNS-SOLVER-EVENT_RELATION_DERIVATION", "EVENT_RELATION_DERIVATION_MISMATCH", "/selected_solution/resolved_relations"))
        elif relation["derivation_mode"] == "EVENT_DERIVED":
            mapping = inputs.get("EVENT_RELATION_MAPPING", {}).get("event_mapping", {})
            if any(
                relation["predicate"] not in mapping.get(event_by_key[root]["event_type"], {}).get("predicates", {})
                for root in relation["root_keys"]
                if root in event_by_key
            ):
                errors.append(error("CNS-SOLVER-EVENT_RELATION_DERIVATION", "EVENT_RELATION_DERIVATION_MISMATCH", "/selected_solution/resolved_relations"))
        matrix = inputs.get("PREDICATE_TYPE_MAPPING", {}).get("predicate_type_matrix", {}).get(relation["predicate"])
        if matrix is None:
            errors.append(error("CNS-SOLVER-EVENT_RELATION_DERIVATION", "EVENT_RELATION_DERIVATION_MISMATCH", "/selected_solution/resolved_relations"))
        else:
            prefix_to_type = {config["id_prefix"]: name for name, config in inputs.get("ENTITY_ONTOLOGY", {}).get("entity_types", {}).items()}
            def selector_types(selector: dict[str, Any]) -> set[str]:
                concrete = {prefix_to_type.get(entity.split(".", 1)[0], "") for entity in selector["entity_ids"]}
                return concrete | set(selector["entity_types"])
            if selector_types(relation["subject_selector"]) - set(matrix["subject_types"]) or selector_types(relation["object_selector"]) - set(matrix["object_types"]):
                errors.append(error("CNS-SOLVER-EVENT_RELATION_DERIVATION", "EVENT_RELATION_DERIVATION_MISMATCH", "/selected_solution/resolved_relations"))
    for item in core["semantic_roles"] + core["narrative_intents"]:
        if any(root not in relation_by_key for root in item["root_keys"]):
            errors.append(error("CNS-SOLVER-ENTITY_RESOLUTION", "SLOT_TYPE_MISMATCH", "/selected_solution"))
    frames = {item["frame_id"]: item for item in inputs.get("EVENT_FRAME", {}).get("frames", [])}
    for event in core["resolved_events"]:
        frame = frames.get(event["frame_id"])
        if frame is None or event["event_type"] not in frame["normalized_identity"]["event_type_domain"] or event["assertion_status"] != frame["assertion"]["assertion_status"]:
            errors.append(error("CNS-SOLVER-EVENT_IDENTITY", "EVENT_IDENTITY_MISMATCH", "/selected_solution/resolved_events"))
    if typed["status"] == "UNIQUE" and typed["ambiguity_certificate"] is not None:
        errors.append(error("CNS-SOLVER-AMBIGUITY_CERTIFICATE", "AMBIGUITY_CERTIFICATE_INVALID", "/ambiguity_certificate"))
    emission = typed["selected_solution"]["queryir_emission_record"]
    projection_rules = inputs.get("PROJECTION_RULE_SET", load_yaml(PROJECTION_RULE_SET))
    expected_projection_sha = input_hashes.get(
        "PROJECTION_RULE_SET", sha_bytes(PROJECTION_RULE_SET.read_bytes())
    )
    if emission["projection_rule_set_sha256"] != expected_projection_sha:
        errors.append(error("CNS-SOLVER-HASH_BINDING", "INPUT_HASH_MISMATCH", "/selected_solution/queryir_emission_record/projection_rule_set_sha256"))
    if emission["semantic_solution_core_sha256"] != canonical_sha(core):
        errors.append(error("CNS-SOLVER-HASH_BINDING", "INPUT_HASH_MISMATCH", "/selected_solution/queryir_emission_record/semantic_solution_core_sha256"))
    core_failure = validate_core_minimality(core, emission)
    for constraint in core_failure:
        errors.append(
            error(constraint, registry_failure(constraint), "/selected_solution")
        )
    if not dag_valid(emission["license_dag"]) or not rooted_witness_paths_valid(emission):
        errors.append(error("CNS-SOLVER-LICENSE_DAG", "LICENSE_DAG_INVALID", "/selected_solution/queryir_emission_record/license_dag"))
    retained = set(emission["minimality_witness"]["retained_semantic_object_ids"])
    witnesses = {item["semantic_object_id"] for item in emission["minimality_witness"]["retained_object_witnesses"]}
    if retained != witnesses or retained != material_ids(core):
        errors.append(error("CNS-SOLVER-MINIMALITY", "MINIMALITY_WITNESS_INVALID", "/selected_solution/queryir_emission_record/minimality_witness"))
    semantic_errors = validate_semantic_authority(core, inputs, require_complete=True)
    errors.extend(semantic_errors)
    enumerated = 0 if semantic_errors else finite_solution_count(core, emission, inputs)
    if (not semantic_errors or empty_unique) and typed["solution_cardinality"] != ("ONE" if enumerated == 1 else "ZERO" if enumerated == 0 else "MULTIPLE"):
        errors.append(error("CNS-SOLVER-SOLUTION_CARDINALITY", "SOLUTION_CARDINALITY_MISMATCH", "/solution_cardinality"))
    return ordered(errors)


def validate_s4(
    typed: dict[str, Any],
    query_ir: dict[str, Any],
    inputs: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not schema_valid("query-ir-schema-candidate.yml", query_ir):
        errors.append(error("CNS-EMIT-QUERYIR_SCHEMA", "SCHEMA_INVALID", "/"))
    inputs = inputs or {}
    emission = typed["selected_solution"]["queryir_emission_record"]
    emitted = emission["query_ir"]
    if emission["query_ir_sha256"] != canonical_sha(emitted):
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/selected_solution/queryir_emission_record/query_ir_sha256"))
    if typed["status"] != "UNIQUE" or typed["solution_cardinality"] != "ONE" or emitted["interpretation_status"] != "VALID":
        errors.append(error("CNS-EMIT-VALID_STATUS", "QUERYIR_NOT_VALID", "/interpretation_status"))
    pointers = all_json_pointers(emitted)
    traces = emission["field_traces"]
    trace_pointers = [item["query_ir_json_pointer"] for item in traces]
    if len(trace_pointers) != len(set(trace_pointers)) or set(trace_pointers) != set(pointers):
        errors.append(error("CNS-EMIT-LEAF_TRACE_COVERAGE", "TRACE_COVERAGE_INCOMPLETE", "/selected_solution/queryir_emission_record/field_traces"))
    for index, trace in enumerate(traces):
        if trace["query_ir_json_pointer"] in set(pointers) and canonical_sha(pointer_get(emitted, trace["query_ir_json_pointer"])) != trace["emitted_value_sha256"]:
            errors.append(error("CNS-EMIT-TRACE_VALUE_HASH", "TRACE_VALUE_HASH_MISMATCH", f"/selected_solution/queryir_emission_record/field_traces/{index}"))
    core = solution_core(typed)
    core_ids = set()
    for collection, key in (
        ("resolved_mentions", "mention_key"),
        ("resolved_events", "event_key"),
        ("resolved_relations", "relation_key"),
        ("narrative_intents", "narrative_key"),
        ("semantic_roles", "role_key"),
        ("resolved_references", "reference_key"),
        ("resolved_overrides", "override_key"),
    ):
        core_ids.update(item[key] for item in core[collection])
    ast = inputs.get("CLAUSE_AST", {})
    ast_ids = {
        item[key]
        for collection, key in (
            ("nodes", "node_id"),
            ("surface_mentions", "surface_mention_id"),
            ("assertion_markers", "marker_id"),
            ("attachment_sets", "attachment_set_id"),
        )
        for item in ast.get(collection, [])
    }
    normalized = inputs.get("NORMALIZED_REQUEST", {})
    normalized_text = normalized.get("normalized_query_text", "")
    typed_core_hash = canonical_sha(core)
    ast_hash = canonical_sha(ast) if ast else None
    if inputs:
        for index, trace in enumerate(traces):
            for binding in trace["source_bindings"]:
                expected_ids = core_ids if binding["object_kind"] == "TYPED_SOLUTION" else ast_ids
                expected_hash = typed_core_hash if binding["object_kind"] == "TYPED_SOLUTION" else ast_hash
                if expected_hash is None or binding["object_sha256"] != expected_hash or any(source_id not in expected_ids for source_id in binding["source_ids"]):
                    errors.append(error("CNS-EMIT-TRACE_VALUE_HASH", "TRACE_VALUE_HASH_MISMATCH", f"/selected_solution/queryir_emission_record/field_traces/{index}"))
                for span in binding["source_spans"]:
                    if normalized_text[span["start_char"] : span["end_char"]] != span["text"]:
                        errors.append(error("CNS-EMIT-TRACE_VALUE_HASH", "TRACE_VALUE_HASH_MISMATCH", f"/selected_solution/queryir_emission_record/field_traces/{index}"))
    if query_ir != emitted:
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/"))
    errors.extend(validate_queryir_projection(core, emitted, inputs))
    minimality = emission["minimality_witness"]
    retained_ids = minimality["retained_semantic_object_ids"]
    witness_ids = [
        witness["semantic_object_id"]
        for witness in minimality["retained_object_witnesses"]
    ]
    witness_payload = {
        key: value for key, value in minimality.items() if key != "witness_sha256"
    }
    minimality_witness_valid = (
        len(witness_ids) == len(set(witness_ids))
        and len(retained_ids) == len(witness_ids)
        and set(retained_ids) == set(witness_ids)
        and minimality["witness_sha256"] == canonical_sha(witness_payload)
    )
    registered_constraints = set(registry_failure_map())
    for witness in minimality["retained_object_witnesses"]:
        probe_path = resolve_review_path(witness["removal_probe_path"])
        if not probe_path.exists():
            minimality_witness_valid = False
            continue
        probe = load_json(probe_path)
        minimality_witness_valid &= (
            resolved_object_hash(probe_path)[0] == witness["removal_probe_sha256"]
            and probe["removed_semantic_object_id"] == witness["semantic_object_id"]
            and probe["removed_query_ir_json_pointer"]
            == witness["query_ir_json_pointer"]
            and set(witness["supporting_constraint_ids"])
            <= registered_constraints
            and set(witness["removal_unsatisfied_constraint_ids"])
            <= registered_constraints
        )
    if not minimality_witness_valid:
        errors.append(error("CNS-EMIT-MINIMALITY_WITNESS", "MINIMALITY_WITNESS_INVALID", "/selected_solution/queryir_emission_record/minimality_witness"))
    if not rooted_witness_paths_valid(emission) or material_ids(core) != set(emission["minimality_witness"]["retained_semantic_object_ids"]):
        errors.append(error("CNS-EMIT-LICENSE_COVERAGE", "LICENSE_DAG_INVALID", "/selected_solution/queryir_emission_record/minimality_witness"))
    return ordered(errors)


def resolved_object_hash(path: Path) -> tuple[str, int]:
    raw = path.read_bytes()
    if path.suffix == ".json" and FIXTURES in path.parents:
        value = json.loads(raw)
        canonical = canonical_bytes(value)
        if raw != canonical:
            return "NONCANONICAL", len(raw)
        return sha_bytes(raw), len(raw)
    return sha_bytes(raw), len(raw)


def run_schema_gate() -> dict[str, Any]:
    global _SCHEMA_GATE_CACHE
    if _SCHEMA_GATE_CACHE is not None:
        return copy.deepcopy(_SCHEMA_GATE_CACHE)
    completed = subprocess.run(
        ["node", str(SCHEMA_GATE)],
        cwd=HERE,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"AJV strict schema gate failed: {completed.stderr.strip()}")
    result = json.loads(completed.stdout)
    if (
        result.get("result") != "PASS"
        or not isinstance(result.get("compiled_schema_count"), int)
        or not isinstance(result.get("fixture_pair_count"), int)
        or result.get("valid_fixture_count") != result.get("fixture_pair_count")
    ):
        raise RuntimeError("AJV strict schema gate discovery/result mismatch")
    _SCHEMA_GATE_CACHE = copy.deepcopy(result)
    return result


def schema_valid(schema_name: str, value: Any) -> bool:
    cache_key = (schema_name, canonical_sha(value))
    if cache_key in _SCHEMA_VALID_CACHE:
        return _SCHEMA_VALID_CACHE[cache_key]
    completed = subprocess.run(
        ["node", str(SCHEMA_GATE), "--validate-schema", schema_name],
        cwd=HERE,
        input=canonical_bytes(value),
        check=False,
        capture_output=True,
    )
    valid = completed.returncode == 0
    _SCHEMA_VALID_CACHE[cache_key] = valid
    return valid


def semantic_object_set(core: dict[str, Any]) -> dict[str, Any]:
    return {
        key: core[key]
        for key in (
            "resolved_mentions",
            "resolved_events",
            "resolved_relations",
            "semantic_roles",
            "narrative_intents",
            "resolved_references",
            "resolved_overrides",
        )
    }


def refresh_core_hashes(core: dict[str, Any]) -> None:
    core["semantic_object_set_sha256"] = canonical_sha(semantic_object_set(core))
    core["solution_id"] = f"SOL-{core['semantic_object_set_sha256'][:24]}"


def _entity_type_lookup(inputs: dict[str, Any]) -> dict[str, str]:
    """Return only entity/type pairs carried by content-addressed compiler inputs."""
    result: dict[str, str] = {}
    ast = inputs.get("CLAUSE_AST", {})
    for mention in ast.get("surface_mentions", []):
        if len(mention["candidate_entity_ids"]) == 1 and len(mention["candidate_entity_types"]) == 1:
            result[mention["candidate_entity_ids"][0]] = mention["candidate_entity_types"][0]
    for frame in inputs.get("EVENT_FRAME", {}).get("frames", []):
        for slot in frame.get("participant_slots", []):
            domain = slot["domain"]
            if len(domain["entity_ids"]) == 1 and len(domain["entity_types"]) == 1:
                result[domain["entity_ids"][0]] = domain["entity_types"][0]
    return result


def _mention_assertion(ast: dict[str, Any], surface_mention_id: str) -> str:
    mentions = {item["surface_mention_id"]: item for item in ast.get("surface_mentions", [])}
    mention = mentions[surface_mention_id]
    containing = mention["containing_node_id"]
    applicable = [
        marker
        for marker in ast.get("assertion_markers", [])
        if surface_mention_id in marker["scope_target_candidate_ids"]
        or containing in marker["scope_target_candidate_ids"]
    ]
    if any(marker["marker_kind"] == "EXCLUSION" for marker in applicable):
        return "EXCLUDED"
    if any(marker["marker_kind"] == "HYPOTHETICAL" for marker in applicable):
        return "HYPOTHETICAL"
    if sum(marker["marker_kind"] == "NEGATOR" for marker in applicable) % 2:
        return "NEGATED"
    return "AFFIRMED"


def _expected_fixed_mentions(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ast = inputs.get("CLAUSE_AST", {})
    expected: dict[str, dict[str, Any]] = {}
    for item in ast.get("surface_mentions", []):
        if len(item["candidate_entity_ids"]) != 1 or len(item["candidate_entity_types"]) != 1:
            continue
        expected[item["surface_mention_id"]] = {
            "entity_id": item["candidate_entity_ids"][0],
            "entity_type": item["candidate_entity_types"][0],
            "assertion_status": _mention_assertion(ast, item["surface_mention_id"]),
            "temporal_scope": "GENERAL",
        }
    return expected


def _expected_fixed_events(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    event_frame = inputs.get("EVENT_FRAME", {})
    specimens = {
        item["specimen_slot_id"]: item
        for item in event_frame.get("specimen_slots", [])
    }
    expected: dict[str, dict[str, Any]] = {}
    for frame in event_frame.get("frames", []):
        if frame["frame_status"] != "FIXED" or len(frame["event_type_domain"]) != 1:
            continue
        slots = {item["slot_id"]: item for item in frame["participant_slots"]}

        def fixed_entities(slot_ids: list[str]) -> list[str]:
            values: list[str] = []
            for slot_id in slot_ids:
                slot = slots[slot_id]
                if slot["binding_status"] != "FIXED" or len(slot["domain"]["entity_ids"]) != 1:
                    return []
                values.append(slot["domain"]["entity_ids"][0])
            return values

        identity = frame["normalized_identity"]
        method_id = None
        if identity["method_slot_id"] is not None:
            method = fixed_entities([identity["method_slot_id"]])
            method_id = method[0] if len(method) == 1 else None
        specimen_code = "NOT_APPLICABLE"
        if identity["specimen_slot_ids"]:
            specimen = specimens[identity["specimen_slot_ids"][0]]
            if specimen["binding_status"] == "FIXED" and len(specimen["specimen_code_domain"]) == 1:
                specimen_code = specimen["specimen_code_domain"][0]
        expected[frame["frame_id"]] = {
            "event_type": frame["event_type_domain"][0],
            "actor_entity_ids": fixed_entities(identity["actor_slot_ids"]),
            "target_entity_ids": fixed_entities(identity["target_slot_ids"]),
            "method_entity_id": method_id,
            "specimen_code": specimen_code,
            "assertion_status": frame["assertion"]["assertion_status"],
            "finding_polarity": frame["assertion"]["finding_polarity"],
            "temporal_scope": frame["assertion"]["temporal_scope"],
        }
    return expected


def normalized_event_identity(event: dict[str, Any]) -> tuple[Any, ...]:
    """Execute EVENT_IDENTITY_SIGNATURE without consulting frame/event IDs."""
    contract = load_yaml(EVENT_IDENTITY_CONTRACT)
    values = {
        "EVENT_TYPE": event.get("event_type"),
        "ACTOR_ENTITY_IDS": tuple(sorted(set(event.get("actor_entity_ids", [])))),
        "METHOD_ENTITY_ID": event.get("method_entity_id"),
        "SPECIMEN_CODE": event.get("specimen_code", "NOT_APPLICABLE"),
        "TARGET_ENTITY_IDS": tuple(sorted(set(event.get("target_entity_ids", [])))),
        "ANATOMICAL_SITE_ENTITY_IDS": tuple(
            sorted(set(event.get("anatomical_site_entity_ids", [])))
        ),
    }
    return tuple(values[name] for name in contract["comparison_order"])


def event_identity_contract_valid() -> bool:
    contract = load_yaml(EVENT_IDENTITY_CONTRACT)
    return (
        contract.get("comparison_order")
        == ["EVENT_TYPE", "ACTOR_ENTITY_IDS", "METHOD_ENTITY_ID", "SPECIMEN_CODE", "TARGET_ENTITY_IDS", "ANATOMICAL_SITE_ENTITY_IDS"]
        and set(contract.get("identity_dimensions", {})) == set(contract["comparison_order"])
        and set(contract.get("override_dimensions", {})) == {"ASSERTION_STATUS", "FINDING_POLARITY", "TEMPORAL_SCOPE"}
        and contract.get("same_event") == "ALL_NORMALIZED_IDENTITY_DIMENSIONS_EQUAL"
        and contract.get("distinct_event") == "AT_LEAST_ONE_NORMALIZED_IDENTITY_DIMENSION_DIFFERS"
        and contract.get("override", {}).get("undeclared_dimension_drift") == "REJECT"
        and {"event_key", "frame_id"} <= set(contract.get("stable_ids", {}).get("semantic_judgment_must_not_use", []))
    )


def event_state(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "ASSERTION_STATUS": event.get("assertion_status"),
        "FINDING_POLARITY": event.get("finding_polarity"),
        "TEMPORAL_SCOPE": event.get("temporal_scope"),
    }


def same_event(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return normalized_event_identity(left) == normalized_event_identity(right)


def override_pair_valid(
    earlier: dict[str, Any], later: dict[str, Any], dimension: str
) -> bool:
    allowed = set(load_yaml(EVENT_IDENTITY_CONTRACT)["override_dimensions"])
    if dimension not in allowed or not same_event(earlier, later):
        return False
    earlier_state, later_state = event_state(earlier), event_state(later)
    return (
        earlier_state[dimension] != later_state[dimension]
        and all(
            earlier_state[name] == later_state[name]
            for name in allowed - {dimension}
        )
    )


def validate_reference_override_semantics(
    core: dict[str, Any], inputs: dict[str, Any], require_complete: bool = True
) -> list[dict[str, str]]:
    """Bind Event Frame hypotheses to typed objects and execute identity rules."""
    errors: list[dict[str, str]] = []
    frame_object = inputs.get("EVENT_FRAME", {})
    hypotheses = {
        item["reference_hypothesis_id"]: item
        for item in frame_object.get("reference_hypotheses", [])
    }
    overrides = {
        item["override_hypothesis_id"]: item
        for item in frame_object.get("override_hypotheses", [])
    }
    event_by_key = {item["event_key"]: item for item in core["resolved_events"]}
    event_by_frame = {item["frame_id"]: item for item in core["resolved_events"]}
    mention_by_key = {item["mention_key"]: item for item in core["resolved_mentions"]}
    ast_ids = {
        item[key]
        for collection, key in (("nodes", "node_id"), ("surface_mentions", "surface_mention_id"))
        for item in inputs.get("CLAUSE_AST", {}).get(collection, [])
    }

    actual_reference_hypotheses: set[str] = set()
    for index, resolved in enumerate(core["resolved_references"]):
        hypothesis = hypotheses.get(resolved["hypothesis_id"])
        actual_reference_hypotheses.add(resolved["hypothesis_id"])
        anaphor = event_by_key.get(resolved["anaphor_key"]) or mention_by_key.get(
            resolved["anaphor_key"]
        )
        referent = event_by_key.get(resolved["referent_key"]) or mention_by_key.get(
            resolved["referent_key"]
        )
        valid = hypothesis is not None and anaphor is not None and referent is not None
        if valid:
            valid = hypothesis["anaphor_source_id"] in ast_ids
            valid = valid and (
                hypothesis["anaphor_frame_id"] is None
                or (
                    resolved["anaphor_key"].startswith("RE")
                    and anaphor["frame_id"] == hypothesis["anaphor_frame_id"]
                )
            )
            candidate_frame = referent.get("frame_id") if resolved["referent_key"].startswith("RE") else None
            valid = valid and candidate_frame in hypothesis["candidate_referent_ids"]
            valid = valid and resolved["identity_relation"] in hypothesis["identity_relation_domain"]
            if resolved["identity_relation"] != "NOT_APPLICABLE":
                valid = valid and resolved["anaphor_key"].startswith("RE") and resolved["referent_key"].startswith("RE")
                if valid:
                    observed = "SAME_EVENT" if same_event(anaphor, referent) else "DISTINCT_EVENT"
                    valid = observed == resolved["identity_relation"]
        if not valid:
            errors.append(error("CNS-SOLVER-EVENT_IDENTITY", "EVENT_IDENTITY_MISMATCH", f"/selected_solution/resolved_references/{index}"))
            break
    expected_refs = {
        key for key, value in hypotheses.items() if value["status"] == "UNIQUE"
    }
    if require_complete and actual_reference_hypotheses != expected_refs:
        errors.append(error("CNS-SOLVER-EVENT_IDENTITY", "EVENT_IDENTITY_MISMATCH", "/selected_solution/resolved_references"))

    actual_override_hypotheses: set[str] = set()
    for index, resolved in enumerate(core["resolved_overrides"]):
        hypothesis = overrides.get(resolved["hypothesis_id"])
        actual_override_hypotheses.add(resolved["hypothesis_id"])
        earlier = event_by_key.get(resolved["earlier_event_key"])
        later = event_by_key.get(resolved["later_event_key"])
        valid = hypothesis is not None and earlier is not None and later is not None
        if valid:
            valid = (
                earlier["frame_id"] in hypothesis["earlier_frame_ids"]
                and later["frame_id"] in hypothesis["later_frame_ids"]
                and resolved["overridden_dimension"] in hypothesis["overridden_dimension_domain"]
                and override_pair_valid(earlier, later, resolved["overridden_dimension"])
            )
        if not valid:
            errors.append(error("CNS-SOLVER-EVENT_IDENTITY", "EVENT_IDENTITY_MISMATCH", f"/selected_solution/resolved_overrides/{index}"))
            break
    expected_overrides = {
        key for key, value in overrides.items() if value["status"] == "UNIQUE"
    }
    if require_complete and actual_override_hypotheses != expected_overrides:
        errors.append(error("CNS-SOLVER-EVENT_IDENTITY", "EVENT_IDENTITY_MISMATCH", "/selected_solution/resolved_overrides"))
    return ordered(errors)


def _selector_types(selector: dict[str, Any], entity_types: dict[str, str]) -> set[str]:
    return set(selector["entity_types"]) | {
        entity_types[entity_id]
        for entity_id in selector["entity_ids"]
        if entity_id in entity_types
    }


def _event_relation_sources(
    event: dict[str, Any], source_rules: list[str], entity_types: dict[str, str]
) -> set[str]:
    """Resolve frozen subject_from/object_from tokens against one actual event."""
    event_entities = set(event["actor_entity_ids"] + event["target_entity_ids"])
    if event["method_entity_id"] is not None:
        event_entities.add(event["method_entity_id"])
    resolved: set[str] = set()
    for source in source_rules:
        if source == "method_entity_id" and event["method_entity_id"] is not None:
            resolved.add(event["method_entity_id"])
        else:
            resolved.update(
                entity_id
                for entity_id in event_entities
                if entity_types.get(entity_id) == source
            )
    return resolved


def _relation_is_bound_to_event(
    relation: dict[str, Any],
    event: dict[str, Any],
    event_mapping: dict[str, Any],
    entity_types: dict[str, str],
    basis_mentions: list[dict[str, Any]],
    frame_by_id: dict[str, dict[str, Any]],
    ast_mentions: dict[str, dict[str, Any]],
) -> bool:
    mapping = event_mapping.get(event["event_type"], {}).get("predicates", {}).get(
        relation["predicate"]
    )
    if mapping is None:
        return False
    subject_ids = set(relation["subject_selector"]["entity_ids"])
    object_ids = set(relation["object_selector"]["entity_ids"])
    basis_ids = {item["entity_id"] for item in basis_mentions}
    basis_by_type = {
        entity_type: {item["entity_id"] for item in basis_mentions if item["entity_type"] == entity_type}
        for entity_type in {item["entity_type"] for item in basis_mentions}
    }
    if relation["derivation_mode"] == "EVENT_DERIVED":
        return (
            subject_ids
            == _event_relation_sources(event, mapping["subject_from"], entity_types)
            and object_ids
            == _event_relation_sources(event, mapping["object_from"], entity_types)
        )

    def direct_allowed(selector_ids: set[str], rules: list[str]) -> bool:
        allowed: set[str] = set()
        for source in rules:
            if source == "method_entity_id" and event["method_entity_id"] is not None:
                allowed.add(event["method_entity_id"])
            else:
                allowed.update(basis_by_type.get(source, set()))
        return bool(selector_ids) and selector_ids <= allowed

    if not (
        (subject_ids | object_ids) == basis_ids
        and direct_allowed(subject_ids, mapping["subject_from"])
        and direct_allowed(object_ids, mapping["object_from"])
    ):
        return False
    frame = frame_by_id.get(event["frame_id"], {})
    slot_by_id = {item["slot_id"]: item for item in frame.get("participant_slots", [])}
    target_source_ids = {
        source_id
        for slot_id in frame.get("normalized_identity", {}).get("target_slot_ids", [])
        for source_id in slot_by_id.get(slot_id, {}).get("source_ids", [])
    }
    target_entities = {
        entity_id
        for source_id in target_source_ids
        for entity_id in ast_mentions.get(source_id, {}).get("candidate_entity_ids", [])
    }
    basis_surface_ids = {item["surface_mention_id"] for item in basis_mentions}
    return (
        target_source_ids <= basis_surface_ids
        and object_ids == target_entities == set(event["target_entity_ids"])
    )


def _matching_projection_profiles(
    core: dict[str, Any], inputs: dict[str, Any]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    projection = inputs.get("PROJECTION_RULE_SET", load_yaml(PROJECTION_RULE_SET))
    entity_types = _entity_type_lookup(inputs)
    mention_by_key = {item["mention_key"]: item for item in core["resolved_mentions"]}
    frame_by_id = {item["frame_id"]: item for item in inputs.get("EVENT_FRAME", {}).get("frames", [])}
    ast_mentions = {item["surface_mention_id"]: item for item in inputs.get("CLAUSE_AST", {}).get("surface_mentions", [])}
    event_mapping = inputs.get("EVENT_RELATION_MAPPING", {}).get("event_mapping", {})
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for relation in core["resolved_relations"]:
        subject_types = _selector_types(relation["subject_selector"], entity_types)
        object_types = _selector_types(relation["object_selector"], entity_types)
        for profile in projection.get("semantic_projection_profiles", []):
            when = profile["when"]
            if relation["predicate"] != when["predicate"]:
                continue
            if subject_types != {when["subject_entity_type"]} or object_types != {when["object_entity_type"]}:
                continue
            compatible_events = [
                event
                for event in core["resolved_events"]
                if event["event_type"] == when["event_type"]
                and event["assertion_status"] == when["assertion_status"]
                and (
                    not when.get("event_target_equals_relation_object")
                    or set(event["target_entity_ids"]) == set(relation["object_selector"]["entity_ids"])
                )
                and _relation_is_bound_to_event(
                    relation,
                    event,
                    event_mapping,
                    entity_types,
                    [mention_by_key[root] for root in relation["root_keys"] if root in mention_by_key],
                    frame_by_id,
                    ast_mentions,
                )
            ]
            if compatible_events:
                matches.append((relation, profile))
    return matches


def validate_semantic_authority(
    core: dict[str, Any], inputs: dict[str, Any], require_complete: bool = True
) -> list[dict[str, str]]:
    """Recompute semantic authorization from actual AST/frame/mapping inputs."""
    errors: list[dict[str, str]] = []
    expected_mentions = _expected_fixed_mentions(inputs)
    actual_mentions = {item["surface_mention_id"]: item for item in core["resolved_mentions"]}
    for surface_id, mention in actual_mentions.items():
        expected = expected_mentions.get(surface_id)
        if expected is None or any(
            mention[key] != expected[key] for key in ("entity_id", "entity_type")
        ):
            errors.append(error("CNS-SOLVER-ENTITY_RESOLUTION", "SLOT_TYPE_MISMATCH", "/selected_solution/resolved_mentions"))
            break
        if any(
            mention[key] != expected[key]
            for key in ("assertion_status", "temporal_scope")
        ):
            errors.append(error("CNS-SOLVER-ASSERTION_SCOPE", "SCOPE_TARGET_INVALID", "/selected_solution/resolved_mentions"))
            break
    if require_complete and set(actual_mentions) != set(expected_mentions):
        errors.append(error("CNS-SOLVER-ENTITY_RESOLUTION", "SLOT_TYPE_MISMATCH", "/selected_solution/resolved_mentions"))

    expected_events = _expected_fixed_events(inputs)
    actual_events = {item["frame_id"]: item for item in core["resolved_events"]}
    for frame_id, event in actual_events.items():
        expected = expected_events.get(frame_id)
        compared = {key: event[key] for key in expected} if expected else None
        if expected is None or compared != expected:
            errors.append(error("CNS-SOLVER-EVENT_IDENTITY", "EVENT_IDENTITY_MISMATCH", "/selected_solution/resolved_events"))
            break
    if require_complete and set(actual_events) != set(expected_events):
        errors.append(error("CNS-SOLVER-EVENT_IDENTITY", "EVENT_IDENTITY_MISMATCH", "/selected_solution/resolved_events"))

    mention_by_key = {item["mention_key"]: item for item in core["resolved_mentions"]}
    event_by_key = {item["event_key"]: item for item in core["resolved_events"]}
    entity_types = _entity_type_lookup(inputs)
    predicate_matrix = inputs.get("PREDICATE_TYPE_MAPPING", {}).get("predicate_type_matrix", {})
    event_mapping = inputs.get("EVENT_RELATION_MAPPING", {}).get("event_mapping", {})
    frame_by_id = {
        item["frame_id"]: item
        for item in inputs.get("EVENT_FRAME", {}).get("frames", [])
    }
    ast_mentions = {
        item["surface_mention_id"]: item
        for item in inputs.get("CLAUSE_AST", {}).get("surface_mentions", [])
    }
    for relation in core["resolved_relations"]:
        roots = relation["root_keys"]
        basis_mentions = [mention_by_key[root] for root in roots if root in mention_by_key]
        basis_events = [event_by_key[root] for root in roots if root in event_by_key]
        selector_ids = set(relation["subject_selector"]["entity_ids"] + relation["object_selector"]["entity_ids"])
        if relation["derivation_mode"] == "DIRECT_MENTION_DERIVED" and (
            any(not root.startswith("RM") for root in roots)
            or selector_ids != {item["entity_id"] for item in basis_mentions}
        ):
            errors.append(error("CNS-SOLVER-EVENT_RELATION_DERIVATION", "EVENT_RELATION_DERIVATION_MISMATCH", "/selected_solution/resolved_relations"))
        matrix = predicate_matrix.get(relation["predicate"])
        if matrix is None or _selector_types(relation["subject_selector"], entity_types) - set(matrix["subject_types"]) or _selector_types(relation["object_selector"], entity_types) - set(matrix["object_types"]):
            errors.append(error("CNS-SOLVER-EVENT_RELATION_DERIVATION", "EVENT_RELATION_DERIVATION_MISMATCH", "/selected_solution/resolved_relations"))
        candidate_events = (
            basis_events
            if relation["derivation_mode"] == "EVENT_DERIVED"
            else list(event_by_key.values())
        )
        if relation["derivation_mode"] == "EVENT_DERIVED" and (
            not basis_events or any(not root.startswith("RE") for root in roots)
        ):
            errors.append(error("CNS-SOLVER-EVENT_RELATION_DERIVATION", "EVENT_RELATION_DERIVATION_MISMATCH", "/selected_solution/resolved_relations"))
        if not any(
            _relation_is_bound_to_event(
                relation,
                event,
                event_mapping,
                entity_types,
                basis_mentions,
                frame_by_id,
                ast_mentions,
            )
            for event in candidate_events
        ):
            errors.append(error("CNS-SOLVER-EVENT_RELATION_DERIVATION", "EVENT_RELATION_DERIVATION_MISMATCH", "/selected_solution/resolved_relations"))

    profiles = _matching_projection_profiles(core, inputs)
    wh_present = any(item["marker_kind"] == "WH_FOCUS" for item in inputs.get("CLAUSE_AST", {}).get("assertion_markers", []))
    if require_complete and wh_present and len(profiles) != 1:
        errors.append(error("CNS-SOLVER-EVENT_RELATION_DERIVATION", "EVENT_RELATION_DERIVATION_MISMATCH", "/selected_solution/resolved_relations"))
    if len(profiles) == 1:
        relation, profile = profiles[0]
        expected_roles = {
            (item["role_namespace"], item["role_value"], "REQUIRED")
            for item in profile["required_roles"]
        }
        actual_roles = {
            (item["role_namespace"], item["role_value"], item["activation_policy"])
            for item in core["semantic_roles"]
        }
        if require_complete and actual_roles != expected_roles:
            errors.append(error("CNS-SOLVER-ASSERTION_SCOPE", "SCOPE_TARGET_INVALID", "/selected_solution/semantic_roles"))
        relation_subject = relation["subject_selector"]
        expected_narratives = {
            (
                item["topic_scope"],
                item["semantic_role"],
                tuple(item["required_anchor_predicates"]),
                canonical_sha(relation_subject),
                "REQUIRED",
            )
            for item in profile["required_narrative_intents"]
        }
        actual_narratives = {
            (
                item["topic_scope"],
                item["semantic_role"],
                tuple(item["required_anchor_predicates"]),
                canonical_sha(item["entity_selector"]),
                item["activation_policy"],
            )
            for item in core["narrative_intents"]
        }
        if require_complete and actual_narratives != expected_narratives:
            errors.append(error("CNS-SOLVER-ASSERTION_SCOPE", "SCOPE_TARGET_INVALID", "/selected_solution/narrative_intents"))
        relation_key = relation["relation_key"]
        if any(item["root_keys"] != [relation_key] for item in core["semantic_roles"] + core["narrative_intents"]):
            errors.append(error("CNS-SOLVER-LICENSE_DAG", "LICENSE_DAG_INVALID", "/selected_solution"))
    errors.extend(
        validate_reference_override_semantics(core, inputs, require_complete=require_complete)
    )
    return ordered(errors)


def _queryir_id(identifier: str) -> str:
    prefixes = {
        "RREF": "REF",
        "ROV": "OVR",
        "RM": "M",
        "RE": "E",
        "RR": "R",
        "RN": "N",
        "RQ": "Q",
    }
    for source, target in prefixes.items():
        if identifier.startswith(source):
            return f"{target}{int(identifier[len(source):]):02d}"
    raise ValueError(identifier)


def derive_queryir_projection(
    core: dict[str, Any], inputs: dict[str, Any]
) -> dict[str, Any]:
    """Deterministically emit every QueryIR field from bound upstream objects."""
    normalized = inputs["NORMALIZED_REQUEST"]
    ast = inputs["CLAUSE_AST"]
    frame_object = inputs["EVENT_FRAME"]
    proposition_nodes = sorted(
        (item for item in ast["nodes"] if item["node_kind"] == "PROPOSITION"),
        key=lambda item: (item["source_span"]["start_char"], item["source_span"]["end_char"]),
    )
    clause_by_node = {
        item["node_id"]: f"C{index:02d}"
        for index, item in enumerate(proposition_nodes, 1)
    }
    clause_order = {clause_id: index for index, clause_id in enumerate(clause_by_node.values(), 1)}
    clauses = [
        {
            "alternative_group_id": None,
            "clause_id": f"C{index:02d}",
            "discourse_operator": "ROOT" if index == 1 else "AND",
            "order": index,
            "parent_clause_id": None if index == 1 else "C01",
            "source_span": copy.deepcopy(node["source_span"]),
        }
        for index, node in enumerate(proposition_nodes, 1)
    ]
    ast_mentions = {item["surface_mention_id"]: item for item in ast["surface_mentions"]}
    mention_id_by_surface = {
        item["surface_mention_id"]: _queryir_id(item["mention_key"])
        for item in core["resolved_mentions"]
    }
    mentions = []
    for item in core["resolved_mentions"]:
        source = ast_mentions[item["surface_mention_id"]]
        mentions.append(
            {
                "assertion_status": item["assertion_status"],
                "clause_id": clause_by_node[source["containing_node_id"]],
                "entity_id": item["entity_id"],
                "entity_type": item["entity_type"],
                "mention_id": _queryir_id(item["mention_key"]),
                "reference_ids": [],
                "source_span": copy.deepcopy(source["source_span"]),
                "temporal_scope": item["temporal_scope"],
            }
        )
    frame_by_id = {item["frame_id"]: item for item in frame_object["frames"]}
    events = []
    event_clause_by_key: dict[str, str] = {}
    for item in core["resolved_events"]:
        frame = frame_by_id[item["frame_id"]]
        clause_id = clause_by_node[frame["source_ast_node_ids"][0]]
        event_clause_by_key[item["event_key"]] = clause_id
        source_ids = {
            source_id
            for slot in frame["participant_slots"]
            for source_id in slot["source_ids"]
        }
        events.append(
            {
                "actor_entity_ids": item["actor_entity_ids"],
                "assertion_status": item["assertion_status"],
                "clause_id": clause_id,
                "event_id": _queryir_id(item["event_key"]),
                "event_type": item["event_type"],
                "finding_polarity": item["finding_polarity"],
                "mention_ids": sorted(mention_id_by_surface[source] for source in source_ids),
                "method_entity_id": item["method_entity_id"],
                "reference_ids": [],
                "source_span": copy.deepcopy(frame["source_spans"][0]),
                "specimen_code": item["specimen_code"],
                "target_entity_id": item["target_entity_ids"][0] if len(item["target_entity_ids"]) == 1 else None,
                "temporal_scope": item["temporal_scope"],
            }
        )
    mention_by_key = {item["mention_key"]: item for item in core["resolved_mentions"]}
    core_event_by_key = {item["event_key"]: item for item in core["resolved_events"]}
    relation_metadata: dict[str, dict[str, Any]] = {}
    relation_intents = []
    for item in core["resolved_relations"]:
        basis_ids = [_queryir_id(root) for root in item["root_keys"]]
        clause_ids = sorted(
            {
                next(mention["clause_id"] for mention in mentions if mention["mention_id"] == basis_id)
                for basis_id in basis_ids
                if basis_id.startswith("M")
            },
            key=clause_order.get,
        )
        if not clause_ids:
            clause_ids = sorted(
                {event_clause_by_key[root] for root in item["root_keys"] if root in event_clause_by_key},
                key=clause_order.get,
            )
        spans = [copy.deepcopy(clauses[clause_order[cid] - 1]["source_span"]) for cid in clause_ids]
        assertions = {
            source["assertion_status"]
            for root in item["root_keys"]
            for source in ([mention_by_key[root]] if root in mention_by_key else [core_event_by_key[root]] if root in core_event_by_key else [])
        }
        temporals = {
            source["temporal_scope"]
            for root in item["root_keys"]
            for source in ([mention_by_key[root]] if root in mention_by_key else [core_event_by_key[root]] if root in core_event_by_key else [])
        }
        assertion = next(iter(assertions)) if len(assertions) == 1 else "UNKNOWN"
        temporal = next(iter(temporals)) if len(temporals) == 1 else "UNKNOWN"
        relation_metadata[item["relation_key"]] = {
            "basis_ids": basis_ids,
            "clause_ids": clause_ids,
            "source_spans": spans,
            "assertion_status": assertion,
            "temporal_scope": temporal,
        }
        relation_intents.append(
            {
                "activation_policy": item["activation_policy"],
                "assertion_status": assertion,
                "basis_ids": basis_ids,
                "clause_ids": clause_ids,
                "derivation_mode": item["derivation_mode"],
                "intent_id": _queryir_id(item["relation_key"]),
                "object_selector": copy.deepcopy(item["object_selector"]),
                "predicate": item["predicate"],
                "source_spans": spans,
                "subject_selector": copy.deepcopy(item["subject_selector"]),
                "temporal_scope": temporal,
            }
        )
    required_roles = []
    for item in core["semantic_roles"]:
        metadata = relation_metadata[item["root_keys"][0]]
        event_clauses = sorted(set(event_clause_by_key.values()), key=clause_order.get)
        required_roles.append(
            {
                "activation_policy": item["activation_policy"],
                "basis_ids": sorted(metadata["basis_ids"]),
                "clause_ids": event_clauses,
                "role_id": _queryir_id(item["role_key"]),
                "role_namespace": item["role_namespace"],
                "role_value": item["role_value"],
            }
        )
    narrative_intents = []
    for item in core["narrative_intents"]:
        metadata = relation_metadata[item["root_keys"][0]]
        subject_ids = set(item["entity_selector"]["entity_ids"])
        subject_basis = sorted(
            _queryir_id(mention["mention_key"])
            for mention in core["resolved_mentions"]
            if mention["entity_id"] in subject_ids
        )
        narrative_intents.append(
            {
                "activation_policy": item["activation_policy"],
                "assertion_status": metadata["assertion_status"],
                "basis_ids": subject_basis,
                "clause_ids": metadata["clause_ids"],
                "derivation_mode": "DIRECT_MENTION_DERIVED",
                "entity_selector": copy.deepcopy(item["entity_selector"]),
                "narrative_intent_id": _queryir_id(item["narrative_key"]),
                "required_anchor_predicates": item["required_anchor_predicates"],
                "semantic_role": item["semantic_role"],
                "source_spans": metadata["source_spans"],
                "temporal_scope": metadata["temporal_scope"],
                "topic_scope": item["topic_scope"],
            }
        )
    node_by_id = {item["node_id"]: item for item in ast["nodes"]}
    hypothesis_by_id = {
        item["reference_hypothesis_id"]: item
        for item in frame_object["reference_hypotheses"]
    }
    override_by_id = {
        item["override_hypothesis_id"]: item
        for item in frame_object["override_hypotheses"]
    }

    def clause_and_span(source_id: str) -> tuple[str, dict[str, Any]]:
        if source_id in ast_mentions:
            mention = ast_mentions[source_id]
            return clause_by_node[mention["containing_node_id"]], copy.deepcopy(mention["source_span"])
        node = node_by_id[source_id]
        current = node
        while current["node_id"] not in clause_by_node:
            children = [node_by_id[value] for value in current["child_node_ids"]]
            if not children:
                raise ValueError(source_id)
            current = sorted(children, key=lambda value: value["source_span"]["start_char"])[0]
        return clause_by_node[current["node_id"]], copy.deepcopy(node["source_span"])

    resolved_references = []
    for item in core["resolved_references"]:
        hypothesis = hypothesis_by_id[item["hypothesis_id"]]
        clause_id, anaphor_span = clause_and_span(hypothesis["anaphor_source_id"])
        referent_kind = "EVENT" if item["referent_key"].startswith("RE") else "MENTION"
        reference_id = _queryir_id(item["reference_key"])
        resolved_references.append(
            {
                "reference_id": reference_id,
                "clause_id": clause_id,
                "anaphor_span": anaphor_span,
                "referent_kind": referent_kind,
                "referent_id": _queryir_id(item["referent_key"]),
                "resolution_status": "RESOLVED",
            }
        )
        target_id = _queryir_id(item["anaphor_key"])
        collection = events if target_id.startswith("E") else mentions
        target = next(value for value in collection if value.get("event_id", value.get("mention_id")) == target_id)
        target["reference_ids"].append(reference_id)

    resolved_overrides = []
    for item in core["resolved_overrides"]:
        hypothesis = override_by_id[item["hypothesis_id"]]
        clause_id, _ = clause_and_span(hypothesis["override_ast_node_id"])
        earlier = next(value for value in core["resolved_events"] if value["event_key"] == item["earlier_event_key"])
        later = next(value for value in core["resolved_events"] if value["event_key"] == item["later_event_key"])
        if not override_pair_valid(earlier, later, item["overridden_dimension"]):
            raise ValueError(item["override_key"])
        resolved_overrides.append(
            {
                "override_id": _queryir_id(item["override_key"]),
                "override_clause_id": clause_id,
                "earlier_event_id": _queryir_id(item["earlier_event_key"]),
                "later_event_id": _queryir_id(item["later_event_key"]),
                "same_normalized_event_identity": True,
                "resolution_status": "RESOLVED",
            }
        )
    return {
        "ambiguities": [],
        "clauses": clauses,
        "events": events,
        "forbidden_relation_intents": copy.deepcopy(core["forbidden_relations"]),
        "interpretation_status": "VALID",
        "knowledge_version": normalized["knowledge_version"],
        "mentions": mentions,
        "narrative_intents": narrative_intents,
        "producer": {
            "configuration_sha256": sha_bytes(PROJECTION_RULE_SET.read_bytes()),
            "implementation_kind": "DETERMINISTIC",
            "producer_id": "p9b1q-queryir-emitter",
            "producer_version": "0.1-fixture",
        },
        "query_ir_version": "0.3-candidate",
        "relation_intents": relation_intents,
        "request_id": normalized["request_id"],
        "request_sha256": normalized["request_sha256"],
        "required_roles": required_roles,
        "resolved_overrides": resolved_overrides,
        "resolved_references": resolved_references,
        "span_basis": ast["span_basis"],
    }


def validate_queryir_projection(
    core: dict[str, Any], query_ir: dict[str, Any], inputs: dict[str, Any]
) -> list[dict[str, str]]:
    """Compare every semantic QueryIR array with a deterministic core projection."""
    errors: list[dict[str, str]] = []
    try:
        expected_query_ir = derive_queryir_projection(core, inputs)
    except (KeyError, IndexError, StopIteration, ValueError):
        expected_query_ir = None
    if expected_query_ir is None or query_ir != expected_query_ir:
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/"))

    def translated(identifier: str) -> str:
        prefixes = {"RREF": "REF", "ROV": "OVR", "RM": "M", "RE": "E", "RR": "R", "RN": "N", "RQ": "Q"}
        for source, target in prefixes.items():
            if identifier.startswith(source):
                return f"{target}{int(identifier[len(source):]):02d}"
        raise ValueError(identifier)

    ast = inputs.get("CLAUSE_AST", {})
    frame_object = inputs.get("EVENT_FRAME", {})
    ast_mentions = {item["surface_mention_id"]: item for item in ast.get("surface_mentions", [])}
    frames = {item["frame_id"]: item for item in frame_object.get("frames", [])}
    material_nodes = sorted(
        (item for item in ast.get("nodes", []) if item["node_kind"] == "PROPOSITION"),
        key=lambda item: (item["source_span"]["start_char"], item["source_span"]["end_char"]),
    )
    expected_clause_spans = [item["source_span"] for item in material_nodes]
    actual_clause_spans = [item["source_span"] for item in query_ir["clauses"]]
    if actual_clause_spans != expected_clause_spans or [item["order"] for item in query_ir["clauses"]] != list(range(1, len(material_nodes) + 1)):
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/clauses"))

    core_mentions = {
        translated(item["mention_key"]): item for item in core["resolved_mentions"]
    }
    query_mentions = {item["mention_id"]: item for item in query_ir["mentions"]}
    if set(core_mentions) != set(query_mentions):
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/mentions"))
    for mention_id, core_item in core_mentions.items():
        output = query_mentions.get(mention_id, {})
        source = ast_mentions.get(core_item["surface_mention_id"], {})
        expected = {
            "entity_id": core_item["entity_id"],
            "entity_type": core_item["entity_type"],
            "assertion_status": core_item["assertion_status"],
            "temporal_scope": core_item["temporal_scope"],
            "source_span": source.get("source_span"),
        }
        if any(output.get(key) != value for key, value in expected.items()):
            errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/mentions"))
            break

    core_events = {translated(item["event_key"]): item for item in core["resolved_events"]}
    query_events = {item["event_id"]: item for item in query_ir["events"]}
    if set(core_events) != set(query_events):
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/events"))
    for event_id, core_item in core_events.items():
        output = query_events.get(event_id, {})
        frame = frames.get(core_item["frame_id"], {})
        expected = {
            "event_type": core_item["event_type"],
            "actor_entity_ids": core_item["actor_entity_ids"],
            "target_entity_id": core_item["target_entity_ids"][0] if len(core_item["target_entity_ids"]) == 1 else None,
            "method_entity_id": core_item["method_entity_id"],
            "specimen_code": core_item["specimen_code"],
            "assertion_status": core_item["assertion_status"],
            "finding_polarity": core_item["finding_polarity"],
            "temporal_scope": core_item["temporal_scope"],
            "source_span": frame.get("source_spans", [None])[0],
        }
        if any(output.get(key) != value for key, value in expected.items()):
            errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/events"))
            break

    core_relations = {translated(item["relation_key"]): item for item in core["resolved_relations"]}
    query_relations = {item["intent_id"]: item for item in query_ir["relation_intents"]}
    if set(core_relations) != set(query_relations):
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/relation_intents"))
    for intent_id, core_item in core_relations.items():
        output = query_relations.get(intent_id, {})
        expected = {
            "predicate": core_item["predicate"],
            "subject_selector": core_item["subject_selector"],
            "object_selector": core_item["object_selector"],
            "activation_policy": core_item["activation_policy"],
            "derivation_mode": core_item["derivation_mode"],
            "basis_ids": sorted(translated(root) for root in core_item["root_keys"]),
        }
        actual_basis = sorted(output.get("basis_ids", []))
        if any(output.get(key) != value for key, value in expected.items() if key != "basis_ids") or actual_basis != expected["basis_ids"]:
            errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/relation_intents"))
            break

    core_roles = {
        translated(item["role_key"]): (
            item["role_namespace"], item["role_value"], item["activation_policy"]
        )
        for item in core["semantic_roles"]
    }
    query_roles = {
        item["role_id"]: (
            item["role_namespace"], item["role_value"], item["activation_policy"]
        )
        for item in query_ir["required_roles"]
    }
    if core_roles != query_roles:
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/required_roles"))

    core_narratives = {
        translated(item["narrative_key"]): (
            item["topic_scope"], item["semantic_role"], item["entity_selector"],
            item["required_anchor_predicates"], item["activation_policy"],
        )
        for item in core["narrative_intents"]
    }
    query_narratives = {
        item["narrative_intent_id"]: (
            item["topic_scope"], item["semantic_role"], item["entity_selector"],
            item["required_anchor_predicates"], item["activation_policy"],
        )
        for item in query_ir["narrative_intents"]
    }
    if core_narratives != query_narratives:
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/narrative_intents"))
    if query_ir["forbidden_relation_intents"] != core["forbidden_relations"]:
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/forbidden_relation_intents"))
    projection_hash = sha_bytes(PROJECTION_RULE_SET.read_bytes())
    if query_ir["producer"]["configuration_sha256"] != projection_hash:
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/producer/configuration_sha256"))
    return ordered(errors)


def validate_actual_reference(reference: dict[str, Any]) -> bool:
    path = resolve_review_path(reference.get("content_path", reference.get("path", "")))
    if not path.is_file():
        return False
    actual_hash, actual_length = resolved_object_hash(path)
    return actual_hash == reference["canonical_sha256"] and (
        "byte_length" not in reference or actual_length == reference["byte_length"]
    )


def stage_actual_input_errors(result: dict[str, Any]) -> list[dict[str, str]]:
    """Fail closed on absent, duplicate, or content-mismatched actual inputs."""
    if result.get("stage") != "S2_EVENT_FRAME":
        return []
    contract = load_yaml(CONTRACT)
    validator_contract = contract["validators"].get(result.get("stage"), {})
    required = validator_contract.get("required_actual_inputs", [])
    references = result.get("actual_input_objects", [])
    actual_kinds = [reference.get("object_kind") for reference in references]
    missing_or_duplicate = (
        not isinstance(required, list)
        or not set(required) <= set(actual_kinds)
        or len(actual_kinds) != len(set(actual_kinds))
    )
    invalid_reference = any(
        not isinstance(reference, dict) or not validate_actual_reference(reference)
        for reference in references
    )
    if not missing_or_duplicate and not invalid_reference:
        return []
    if result.get("stage") == "S2_EVENT_FRAME":
        return [
            error(
                "CNS-EF-REF_INTEGRITY",
                "DANGLING_REFERENCE",
                "/actual_input_objects",
            )
        ]
    registered = validator_contract.get("registered_constraints", [])
    constraint_id = registered[0] if registered else "CNS-NORM-REQUEST_BINDING"
    return [error(constraint_id, registry_failure(constraint_id), "/actual_input_objects")]


def load_stage_result(stage: str, fixture_suffix: str | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    name = f"stage-validation-{stage.lower()}-{fixture_suffix}-positive.json" if fixture_suffix else f"stage-validation-{stage.lower()}-positive.json"
    result = load_json(FIXTURES / name)
    body = copy.deepcopy(result)
    declared = body.pop("result_sha256")
    if canonical_sha(body) != declared:
        raise RuntimeError(f"{stage} validation result self hash mismatch")
    if result["validator"]["executable_sha256"] != sha_bytes(Path(__file__).read_bytes()):
        raise RuntimeError(f"{stage} executable binding mismatch")
    if result["validator"]["configuration_sha256"] != sha_bytes(CONTRACT.read_bytes()):
        raise RuntimeError(f"{stage} contract binding mismatch")
    references = result["actual_input_objects"] + [result["actual_output_object"]]
    if stage_actual_input_errors(result) or not all(
        validate_actual_reference(reference) for reference in references
    ):
        raise RuntimeError(f"{stage} actual object binding mismatch")
    inputs = {
        reference["object_kind"]: pointer_get(
            load_json(resolve_review_path(reference["content_path"]))
            if resolve_review_path(reference["content_path"]).suffix == ".json"
            else load_yaml(resolve_review_path(reference["content_path"])),
            reference["content_json_pointer"],
        )
        for reference in result["actual_input_objects"]
        if resolve_review_path(reference["content_path"]).suffix in (".json", ".yml", ".yaml")
    }
    output_ref = result["actual_output_object"]
    output = load_json(resolve_review_path(output_ref["content_path"]))
    return result, inputs, output


def stage_record_errors(result: dict[str, Any], observed: list[dict[str, str]]) -> list[dict[str, str]]:
    contract = load_yaml(CONTRACT)
    expected = contract["validators"][result["stage"]]["registered_constraints"]
    actual_input_errors = stage_actual_input_errors(result)
    if actual_input_errors:
        return actual_input_errors
    if result["result"] != ("PASS" if not observed else "FAIL_CLOSED") or result["errors"] != observed:
        return [error(expected[0], registry_failure(expected[0]), "/result")]
    if result["verified_constraint_ids"] != expected:
        return [error(expected[0], registry_failure(expected[0]), "/verified_constraint_ids")]
    return observed


def validate_s5(
    sidecar: dict[str, Any],
    object_store_index: dict[str, Any] | None = None,
    actual_object_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not schema_valid("execution-binding-sidecar-architecture-schema-candidate.yml", sidecar):
        errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", "/"))
    parsed: dict[str, list[Any]] = {}
    actual_object_overrides = actual_object_overrides or {}
    for index, reference in enumerate(sidecar["actual_objects"]):
        path = resolve_review_path(reference["path"])
        if not path.is_file():
            errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", f"/actual_objects/{index}/path"))
            continue
        override = actual_object_overrides.get(reference["path"])
        if override is None:
            actual_hash, actual_length = resolved_object_hash(path)
        else:
            actual_hash = canonical_sha(override)
            actual_length = len(canonical_bytes(override))
        if actual_hash != reference["canonical_sha256"] or reference.get("byte_length") != actual_length:
            errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", f"/actual_objects/{index}/canonical_sha256"))
        if path.suffix == ".json":
            parsed.setdefault(reference["object_kind"], []).append(
                override if override is not None else load_json(path)
            )
    body = dict(sidecar)
    declared = body.pop("sidecar_sha256")
    if canonical_sha(body) != declared:
        errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", "/sidecar_sha256"))
    actual_sidecar_canonical_sha256 = canonical_sha(sidecar)
    index = (
        object_store_index
        if object_store_index is not None
        else load_json(FIXTURES / "object-store-index-positive.json")
    )
    index_objects = index.get("objects") if isinstance(index, dict) else None
    if not isinstance(index_objects, list):
        errors.append(
            error(
                "CNS-BIND-ACTUAL_OBJECT_HASH",
                "ACTUAL_OBJECT_BINDING_MISMATCH",
                "/object_store_index/objects",
            )
        )
        index_objects = []

    sidecar_index: list[tuple[int, dict[str, Any]]] = []
    non_sidecar_index: list[tuple[int, dict[str, Any]]] = []
    for item_index, item in enumerate(index_objects):
        if not isinstance(item, dict):
            errors.append(
                error(
                    "CNS-BIND-ACTUAL_OBJECT_HASH",
                    "ACTUAL_OBJECT_BINDING_MISMATCH",
                    f"/object_store_index/objects/{item_index}",
                )
            )
            continue
        destination = (
            sidecar_index
            if item.get("object_kind") == "EXECUTION_BINDING_SIDECAR"
            else non_sidecar_index
        )
        destination.append((item_index, item))

    expected_by_path: dict[str, dict[str, Any]] = {}
    for reference in sidecar["actual_objects"]:
        path = reference["path"]
        if path in expected_by_path:
            errors.append(
                error(
                    "CNS-BIND-ACTUAL_OBJECT_HASH",
                    "ACTUAL_OBJECT_BINDING_MISMATCH",
                    "/actual_objects",
                )
            )
        expected_by_path[path] = reference

    indexed_by_path: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for item_index, item in non_sidecar_index:
        indexed_by_path.setdefault(item.get("path"), []).append((item_index, item))

    expected_entries = {
        (reference["path"], reference["object_kind"], reference["canonical_sha256"])
        for reference in sidecar["actual_objects"]
    }
    indexed_entries = {
        (item.get("path"), item.get("object_kind"), item.get("canonical_sha256"))
        for _, item in non_sidecar_index
    }
    if (
        len(non_sidecar_index) != len(sidecar["actual_objects"])
        or len(indexed_entries) != len(non_sidecar_index)
        or indexed_entries != expected_entries
    ):
        errors.append(
            error(
                "CNS-BIND-ACTUAL_OBJECT_HASH",
                "ACTUAL_OBJECT_BINDING_MISMATCH",
                "/object_store_index/objects",
            )
        )

    for path, reference in expected_by_path.items():
        matches = indexed_by_path.get(path, [])
        if len(matches) != 1:
            errors.append(
                error(
                    "CNS-BIND-ACTUAL_OBJECT_HASH",
                    "ACTUAL_OBJECT_BINDING_MISMATCH",
                    "/object_store_index/objects",
                )
            )
            continue
        item_index, item = matches[0]
        if item.get("object_kind") != reference["object_kind"]:
            errors.append(
                error(
                    "CNS-BIND-ACTUAL_OBJECT_HASH",
                    "ACTUAL_OBJECT_BINDING_MISMATCH",
                    f"/object_store_index/objects/{item_index}/object_kind",
                )
            )
        if item.get("canonical_sha256") != reference["canonical_sha256"]:
            errors.append(
                error(
                    "CNS-BIND-ACTUAL_OBJECT_HASH",
                    "ACTUAL_OBJECT_BINDING_MISMATCH",
                    f"/object_store_index/objects/{item_index}/canonical_sha256",
                )
            )

    for path, matches in indexed_by_path.items():
        if path not in expected_by_path or len(matches) != 1:
            errors.append(
                error(
                    "CNS-BIND-ACTUAL_OBJECT_HASH",
                    "ACTUAL_OBJECT_BINDING_MISMATCH",
                    "/object_store_index/objects",
                )
            )

    expected_sidecar_path = "fixtures/execution-binding-sidecar-positive.json"
    top_level_sidecar_binding_valid = (
        index.get("sidecar_sha256") == actual_sidecar_canonical_sha256
    )
    if len(sidecar_index) == 1:
        top_level_sidecar_binding_valid = (
            top_level_sidecar_binding_valid
            and index.get("sidecar_sha256")
            == sidecar_index[0][1].get("canonical_sha256")
        )
    if not top_level_sidecar_binding_valid:
        errors.append(
            error(
                "CNS-BIND-ACTUAL_OBJECT_HASH",
                "ACTUAL_OBJECT_BINDING_MISMATCH",
                "/object_store_index/sidecar_sha256",
            )
        )
    if len(sidecar_index) != 1:
        errors.append(
            error(
                "CNS-BIND-ACTUAL_OBJECT_HASH",
                "ACTUAL_OBJECT_BINDING_MISMATCH",
                "/object_store_index/objects",
            )
        )
    else:
        item_index, item = sidecar_index[0]
        if item.get("path") != expected_sidecar_path:
            errors.append(
                error(
                    "CNS-BIND-ACTUAL_OBJECT_HASH",
                    "ACTUAL_OBJECT_BINDING_MISMATCH",
                    f"/object_store_index/objects/{item_index}/path",
                )
            )
        if item.get("canonical_sha256") != actual_sidecar_canonical_sha256:
            errors.append(
                error(
                    "CNS-BIND-ACTUAL_OBJECT_HASH",
                    "ACTUAL_OBJECT_BINDING_MISMATCH",
                    f"/object_store_index/objects/{item_index}/canonical_sha256",
                )
            )
    if sidecar["canonicalization_profile_sha256"] != sha_bytes((HERE / "object-canonicalization-and-hash-chain.yml").read_bytes()):
        errors.append(error("CNS-BIND-CANONICAL_PROFILE", "ACTUAL_OBJECT_BINDING_MISMATCH", "/canonicalization_profile_sha256"))
    request = parsed.get("P9A_REQUEST", [{}])[0]
    request_hash = canonical_sha(request) if request else None
    request_id = request.get("request_id")
    chain_objects = [
        item
        for values in parsed.values()
        for item in values
        if isinstance(item, dict) and "request_id" in item
    ]
    if not request or any(item["request_id"] != request_id for item in chain_objects):
        errors.append(error("CNS-BIND-REQUEST_CHAIN", "ACTUAL_OBJECT_BINDING_MISMATCH", "/request_id"))
    for item in chain_objects:
        if "request_sha256" in item and item["request_sha256"] != request_hash:
            errors.append(error("CNS-BIND-REQUEST_CHAIN", "ACTUAL_OBJECT_BINDING_MISMATCH", "/request_sha256"))
    stage_results = parsed.get("STAGE_SEMANTIC_VALIDATION_RESULT", [])
    if len(stage_results) != 5 or any(item["result"] != "PASS" or item["errors"] for item in stage_results):
        errors.append(error("CNS-BIND-REQUEST_CHAIN", "ACTUAL_OBJECT_BINDING_MISMATCH", "/stage_validation_result_paths"))
    sidecar_refs = {
        (reference["path"], reference["canonical_sha256"])
        for reference in sidecar["actual_objects"]
    }
    for stage_result in stage_results:
        nested = stage_result["actual_input_objects"] + [stage_result["actual_output_object"]]
        for reference in nested:
            relative = reference["content_path"]
            prefix = "phase9/clonorchis-sinensis/p9b1q-architecture-review/"
            if relative.startswith(prefix):
                relative = relative[len(prefix) :]
            if (relative, reference["canonical_sha256"]) not in sidecar_refs:
                errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", "/actual_objects"))
    query_ir = parsed.get("QUERY_IR", [{}])[0]
    retrieval = parsed.get("RETRIEVAL_RESULT", [])
    response = parsed.get("P9A_RESPONSE", [])
    audit = parsed.get("P9A_AUDIT_RECORD", [])
    if (
        query_ir.get("interpretation_status") != "VALID"
        or sidecar["retrieval_executed"] != bool(retrieval)
        or sidecar["response_present"] != bool(response)
        or not retrieval
        or retrieval[0].get("status") != "RETRIEVED"
    ):
        errors.append(error("CNS-BIND-RETRIEVAL_CHAIN", "ACTUAL_OBJECT_BINDING_MISMATCH", "/retrieval_executed"))
    if not response or not audit or audit[0].get("response_sha256") != canonical_sha(response[0]):
        errors.append(error("CNS-BIND-RESPONSE_AUDIT_CHAIN", "REQUEST_RESPONSE_AUDIT_MISMATCH", "/response_present"))
    return ordered(errors)


def negative_mutation_model() -> dict[str, Any]:
    global _NEGATIVE_MUTATION_MODEL_CACHE
    if _NEGATIVE_MUTATION_MODEL_CACHE is None:
        _NEGATIVE_MUTATION_MODEL_CACHE = load_yaml(NEGATIVE_MUTATION_MODEL)
    return _NEGATIVE_MUTATION_MODEL_CACHE


def validate_mutation_isolation(
    case: dict[str, Any], *, expected_target_object: str | None = None
) -> dict[str, Any]:
    """Fail closed unless a fixture declares exactly one semantic target.

    RFC6902 is only a transport.  This function binds the sole semantic target
    to exactly one allowed patch channel, while derived fields remain runner
    owned and are checked against the frozen recomputation allowlist.
    """
    model = negative_mutation_model()
    fixture_id = case.get("fixture_id", "<unknown>")
    if case.get("semantic_mutation_target_count") != model["semantic_mutation_target_cardinality"]:
        raise RuntimeError(f"{fixture_id}: semantic mutation target count must be one")
    mutation = case.get("semantic_mutation")
    required = set(model["required_semantic_declaration_fields"])
    if not isinstance(mutation, dict) or not required <= set(mutation):
        raise RuntimeError(f"{fixture_id}: incomplete semantic mutation declaration")
    if mutation["expected_constraint_id"] != case.get("expected_constraint_id"):
        raise RuntimeError(f"{fixture_id}: semantic expected constraint mismatch")
    if mutation["expected_constraint_id"] not in registry_order():
        raise RuntimeError(f"{fixture_id}: semantic expected constraint is unregistered")
    canonical_failure_code = registry_failure(mutation["expected_constraint_id"])
    fixture_failure_code = case.get("expected_failure_code")
    if not isinstance(fixture_failure_code, str) or not fixture_failure_code:
        raise RuntimeError(f"{fixture_id}: fixture failure code is required")
    if fixture_failure_code != canonical_failure_code:
        raise RuntimeError(
            f"{fixture_id}: fixture failure code is not registry canonical"
        )
    if expected_target_object is not None and mutation["target_object"] != expected_target_object:
        raise RuntimeError(f"{fixture_id}: semantic target object mismatch")
    if not isinstance(mutation["target_path"], str) or not mutation["target_path"].startswith("/"):
        raise RuntimeError(f"{fixture_id}: semantic target path is not a JSON pointer")

    mechanism = mutation["mechanism"]
    allowed = model["allowed_mechanisms"]
    if mechanism not in allowed:
        raise RuntimeError(f"{fixture_id}: undeclared semantic mutation mechanism")
    main_patch = case.get("patch", [])
    actual_patch = case.get("actual_input_mutation", {}).get("patch", [])
    index_patch = case.get("object_store_index_patch", [])
    channels = {
        "RFC6902": main_patch,
        "CROSS_OBJECT_RFC6902": actual_patch,
        "OBJECT_STORE_INDEX_RFC6902": index_patch,
    }
    if mechanism in channels:
        active = channels[mechanism]
        if len(active) != 1 or active[0].get("path") != mutation["target_path"]:
            raise RuntimeError(f"{fixture_id}: semantic patch count or target mismatch")
        if sum(len(value) for value in (main_patch, actual_patch, index_patch)) != 1:
            raise RuntimeError(f"{fixture_id}: undeclared extra semantic patch")
        if mechanism == "CROSS_OBJECT_RFC6902" and (
            case.get("actual_input_mutation", {}).get("object_kind") != mutation["target_object"]
        ):
            raise RuntimeError(f"{fixture_id}: cross-object target mismatch")
        if mechanism == "OBJECT_STORE_INDEX_RFC6902" and mutation["target_object"] != "OBJECT_STORE_INDEX":
            raise RuntimeError(f"{fixture_id}: object-store index target mismatch")
    else:
        transform = mutation.get("transform")
        if transform not in allowed[mechanism]["allowed_transforms"]:
            raise RuntimeError(f"{fixture_id}: undeclared deterministic transform")
        if any((main_patch, actual_patch, index_patch)):
            raise RuntimeError(f"{fixture_id}: deterministic transform has an extra patch")

    allowed_rules = model["allowed_derived_rules"]
    seen_updates: set[tuple[str, str, str]] = set()
    for update in case.get("derived_updates", []):
        required_update = {"target_object", "target_path", "derivation_rule"}
        if not isinstance(update, dict) or not required_update <= set(update):
            raise RuntimeError(f"{fixture_id}: incomplete derived update declaration")
        rule_name = update["derivation_rule"]
        rule = allowed_rules.get(rule_name)
        if rule is None or update["target_path"] != rule["target_path"]:
            raise RuntimeError(f"{fixture_id}: derived rule or target is not allowlisted")
        if update["target_object"] != "STAGE_BASE_OBJECT":
            raise RuntimeError(f"{fixture_id}: derived update is not runner-owned")
        if rule.get("source_object") != update.get("source_object"):
            raise RuntimeError(f"{fixture_id}: derived source object mismatch")
        identity = (update["target_object"], update["target_path"], rule_name)
        if identity in seen_updates or update["target_path"] == mutation["target_path"]:
            raise RuntimeError(f"{fixture_id}: duplicate or overlapping derived update")
        seen_updates.add(identity)
        for operation in main_patch + actual_patch + index_patch:
            if operation["path"] == update["target_path"]:
                raise RuntimeError(f"{fixture_id}: fixture supplies a derived value")
    return mutation


def apply_declared_semantic_mutation(value: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    mutation = case["semantic_mutation"]
    if mutation["mechanism"] == "RFC6902":
        return apply_patch(value, case["patch"])
    output = copy.deepcopy(value)
    if mutation["mechanism"] == "DETERMINISTIC_TRANSFORM":
        if mutation["transform"] != "CLEAR_MATERIAL_SEMANTIC_COLLECTIONS":
            raise RuntimeError(f"{case['fixture_id']}: unsupported deterministic transform")
        selected = output["selected_solution"]
        for field in (
            "resolved_mentions",
            "resolved_events",
            "resolved_relations",
            "semantic_roles",
            "narrative_intents",
        ):
            selected[field] = []
    return output


def recompute_declared_derived(
    value: dict[str, Any],
    updates: list[dict[str, Any]],
    source_objects: dict[str, Any] | None = None,
) -> None:
    selected = value.get("selected_solution")
    source_objects = source_objects or {}
    for update in updates:
        rule = update["derivation_rule"]
        if rule == "RECOMPUTE_SEMANTIC_SOLUTION_CORE_SHA256" and selected is not None:
            selected["queryir_emission_record"]["semantic_solution_core_sha256"] = canonical_sha(solution_core(value))
        elif rule == "RECOMPUTE_SEMANTIC_OBJECT_IDENTITY" and selected is not None:
            core = solution_core(value)
            selected["semantic_object_set_sha256"] = canonical_sha(semantic_object_set(core))
            selected["solution_id"] = f"SOL-{selected['semantic_object_set_sha256'][:24]}"
        elif rule == "RECOMPUTE_LICENSE_DAG_SHA256" and selected is not None:
            dag = selected["queryir_emission_record"]["license_dag"]
            body = dict(dag)
            body.pop("dag_sha256", None)
            dag["dag_sha256"] = canonical_sha(body)
        elif rule == "RECOMPUTE_MINIMALITY_WITNESS_SHA256" and selected is not None:
            witness = selected["queryir_emission_record"]["minimality_witness"]
            body = dict(witness)
            body.pop("witness_sha256", None)
            witness["witness_sha256"] = canonical_sha(body)
        elif rule == "RECOMPUTE_QUERY_IR_SHA256" and selected is not None:
            emission = selected["queryir_emission_record"]
            emission["query_ir_sha256"] = canonical_sha(emission["query_ir"])
        elif rule == "RECOMPUTE_ALL_FIELD_TRACE_VALUE_SHA256" and selected is not None:
            emission = selected["queryir_emission_record"]
            for trace in emission["field_traces"]:
                trace["emitted_value_sha256"] = canonical_sha(
                    pointer_get(emission["query_ir"], trace["query_ir_json_pointer"])
                )
        elif rule == "RECOMPUTE_NORMALIZED_SURFACE_FROM_SOURCE_SPAN":
            value["surface_mentions"][0]["normalized_surface"] = value["surface_mentions"][0]["source_span"]["text"]
        elif rule == "RECOMPUTE_CONSTRAINT_REGISTRY_SHA256":
            value["constraint_registry_sha256"] = canonical_sha(source_objects["CONSTRAINT_REGISTRY"])
        elif rule == "RECOMPUTE_S5_ACTUAL_OBJECT_BINDING_CHAIN":
            object_kind = update["source_object"]
            actual_object = source_objects[object_kind]
            actual_path = source_objects["S5_MUTATED_ACTUAL_OBJECT_PATH"]
            object_store_index = source_objects["OBJECT_STORE_INDEX"]
            actual_hash = canonical_sha(actual_object)
            actual_length = len(canonical_bytes(actual_object))
            sidecar_matches = [
                item
                for item in value["actual_objects"]
                if item["path"] == actual_path and item["object_kind"] == object_kind
            ]
            index_matches = [
                item
                for item in object_store_index["objects"]
                if item.get("path") == actual_path
                and item.get("object_kind") == object_kind
            ]
            if len(sidecar_matches) != 1 or len(index_matches) != 1:
                raise RuntimeError("S5 mutated actual object is not uniquely bound")
            sidecar_matches[0]["canonical_sha256"] = actual_hash
            sidecar_matches[0]["byte_length"] = actual_length
            index_matches[0]["canonical_sha256"] = actual_hash
            sidecar_body = dict(value)
            sidecar_body.pop("sidecar_sha256", None)
            value["sidecar_sha256"] = canonical_sha(sidecar_body)
            sidecar_index_matches = [
                item
                for item in object_store_index["objects"]
                if item.get("object_kind") == "EXECUTION_BINDING_SIDECAR"
            ]
            if len(sidecar_index_matches) != 1:
                raise RuntimeError("S5 sidecar index binding is not unique")
            recomputed_sidecar_canonical_sha256 = canonical_sha(value)
            sidecar_index_matches[0]["canonical_sha256"] = (
                recomputed_sidecar_canonical_sha256
            )
            object_store_index["sidecar_sha256"] = (
                recomputed_sidecar_canonical_sha256
            )
        else:
            raise RuntimeError(f"unsupported or inapplicable derived rule: {rule}")


def normalized_by_request_id() -> dict[str, dict[str, Any]]:
    result = {}
    for path in FIXTURES.glob("normalized-request-*-positive.json"):
        item = load_json(path)
        result[item["request_id"]] = item
    return result


def run_positive() -> list[dict[str, Any]]:
    require_failure_code_governance()
    schema_gate = run_schema_gate()
    results: list[dict[str, Any]] = []
    normalized = normalized_by_request_id()
    explicit_diagnostic_binding = load_json(DIAGNOSTIC_ARGUMENT_BINDING_FIXTURE)
    for suffix in ("exposure", "diagnostic", "diagnostic-role-catalog"):
        request = load_json(FIXTURES / f"request-{suffix}-positive.json")
        norm = load_json(FIXTURES / f"normalized-request-{suffix}-positive.json")
        ast = load_json(FIXTURES / f"clause-ast-{suffix}-positive.json")
        frame = load_json(FIXTURES / f"event-frame-{suffix}-positive.json")
        s0_errors = validate_s0(norm, request)
        if suffix == "exposure":
            s1_record, s1_inputs, _ = load_stage_result("S1")
            s1_errors = validate_s1(
                ast,
                norm,
                alias_authority=s1_inputs.get("ENTITY_ALIAS_AUTHORITY"),
                negation_authority=s1_inputs.get(
                    "NEGATION_SURFACE_SCOPE_AUTHORITY"
                ),
            )
        else:
            s1_errors = validate_s1(ast, norm)
        s2_errors = validate_s2(
            frame,
            norm,
            ast,
            diagnostic_argument_binding=explicit_diagnostic_binding,
        )
        if suffix == "exposure":
            s0_record, _, _ = load_stage_result("S0")
            s2_record, _, _ = load_stage_result("S2")
            s0_errors = stage_record_errors(s0_record, s0_errors)
            s1_errors = stage_record_errors(s1_record, s1_errors)
            s2_errors = stage_record_errors(s2_record, s2_errors)
        elif suffix == "diagnostic-role-catalog":
            s2_record, s2_inputs, _ = load_stage_result(
                "S2", "diagnostic-role-catalog"
            )
            s2_errors = validate_s2(
                frame,
                norm,
                ast,
                s2_inputs.get("QUERY_INTERPRETER_CONFIG"),
                s2_inputs.get("ENTITY_ONTOLOGY"),
                s2_inputs.get("EVENT_RELATION_MAPPING"),
                s2_inputs.get("DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING"),
            )
            s2_errors = stage_record_errors(s2_record, s2_errors)
        results.extend([
            {"case": f"POS-S0-{suffix}", "errors": s0_errors},
            {"case": f"POS-S1-{suffix}", "errors": s1_errors},
            {"case": f"POS-S2-{suffix}", "errors": s2_errors},
        ])
    shared_request = load_json(FIXTURES / "request-shared-argument-positive.json")
    shared_norm = load_json(FIXTURES / "normalized-request-shared-argument-positive.json")
    shared_ast = load_json(FIXTURES / "clause-ast-shared-argument-positive.json")
    shared_record, _, _ = load_stage_result("S1", "shared-argument")
    results.extend([
        {"case": "POS-S0-shared-argument", "errors": validate_s0(shared_norm, shared_request)},
        {"case": "POS-S1-shared-argument", "errors": stage_record_errors(shared_record, validate_s1(shared_ast, shared_norm))},
    ])
    s3_record, s3_inputs, typed = load_stage_result("S3")
    s3_hashes = {
        item["object_kind"]: item["canonical_sha256"]
        for item in load_json(FIXTURES / "stage-validation-s3-positive.json")["actual_input_objects"]
    }
    s4_record, s4_inputs, query_ir = load_stage_result("S4")
    sidecar = load_json(FIXTURES / "execution-binding-sidecar-positive.json")
    results.extend(
        [
            {"case": "POS-S3-exposure", "errors": stage_record_errors(s3_record, validate_s3(typed, s3_inputs, s3_hashes))},
            {"case": "POS-S4-exposure", "errors": stage_record_errors(s4_record, validate_s4(typed, query_ir, s4_inputs))},
            {"case": "POS-S5-exposure", "errors": validate_s5(sidecar)},
        ]
    )
    if schema_gate["result"] != "PASS":
        results[0]["errors"].append(error("CNS-NORM-REQUEST_BINDING", "INPUT_HASH_MISMATCH", "/schema_gate"))
    return results


def run_minimality() -> list[dict[str, Any]]:
    require_failure_code_governance()
    core = load_json(FIXTURES / "typed-solution-exposure-positive.json")
    emission = load_json(FIXTURES / "queryir-emission-record-exposure-positive.json")
    _, inputs, _ = load_stage_result("S3")
    results = []
    for path in sorted(FIXTURES.glob("minimality-removal-probe-*.json")):
        probe = load_json(path)
        candidate = apply_patch(core, probe["mutation"])
        refresh_core_hashes(candidate)
        semantic_errors = validate_semantic_authority(
            candidate, inputs, require_complete=True
        )
        observed = (
            [semantic_errors[0]["constraint_id"]] if semantic_errors else []
        )
        enumerated_after_removal = finite_solution_count(candidate, emission, inputs)
        results.append(
            {
                "probe_id": probe["probe_id"],
                "candidate_sha256": canonical_sha(candidate),
                "observed_unsatisfied_constraint_ids": observed,
                "passed": canonical_sha(candidate) == probe["candidate_typed_solution_sha256"]
                and candidate["semantic_object_set_sha256"] == probe["candidate_semantic_object_set_sha256"]
                and probe["recomputed_derived_hashes"] == ["semantic_object_set_sha256"]
                and enumerated_after_removal == probe["enumerated_solution_count_after_removal"]
                and observed == probe["expected_unsatisfied_constraint_ids"],
            }
        )
    return results


def run_negative() -> list[dict[str, Any]]:
    require_failure_code_governance()
    manifest = load_yaml(NEGATIVE)
    if manifest.get("mutation_model_path") != "../negative-fixture-semantic-mutation-model.yml":
        raise RuntimeError("stage negative fixture manifest is not bound to the R3-D2 mutation model")
    normalized = normalized_by_request_id()
    explicit_diagnostic_binding = load_json(DIAGNOSTIC_ARGUMENT_BINDING_FIXTURE)
    results = []
    for case in manifest["cases"]:
        mutation = validate_mutation_isolation(case)
        base = load_json(resolve_review_path(case["valid_base_object_path"]))
        stage = case["stage"]
        base_index: dict[str, Any] | None = None
        base_errors: list[dict[str, str]]
        if stage == "S0_NORMALIZED_REQUEST":
            base_request = load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
            base_errors = validate_s0(base, base_request)
        elif stage == "S1_CLAUSE_AST":
            base_errors = validate_s1(base, normalized[base["request_id"]])
        elif stage == "S2_EVENT_FRAME":
            base_ast = (
                load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
                if case.get("paired_actual_object_paths")
                and "clause-ast" in case["paired_actual_object_paths"][0]
                else None
            )
            base_errors = validate_s2(
                base,
                normalized[base["request_id"]],
                base_ast,
                diagnostic_argument_binding=explicit_diagnostic_binding,
            )
        elif stage == "S3_TYPED_SOLVER":
            s3_record, s3_inputs, _ = load_stage_result("S3")
            s3_hashes = {item["object_kind"]: item["canonical_sha256"] for item in s3_record["actual_input_objects"]}
            base_errors = validate_s3(base, s3_inputs, s3_hashes)
        elif stage == "S4_QUERYIR_EMISSION":
            _, s4_inputs, _ = load_stage_result("S4")
            if "solver_result_version" in base:
                base_query = load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
                base_errors = validate_s4(base, base_query, s4_inputs)
            else:
                base_typed = load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
                base_errors = validate_s4(base_typed, base, s4_inputs)
        elif stage == "S5_RUNTIME_BINDING":
            base_index = (
                load_json(resolve_review_path(case["object_store_index_path"]))
                if case.get("object_store_index_path")
                else None
            )
            base_errors = validate_s5(base, base_index)
        else:
            raise ValueError(stage)
        if base_errors:
            raise RuntimeError(f"negative fixture base failed before mutation: {case['fixture_id']}")

        mutated = apply_declared_semantic_mutation(base, case)
        mutated_s3_inputs: dict[str, Any] | None = None
        mutated_s3_hashes: dict[str, str] | None = None
        mutated_s2_event_mapping: dict[str, Any] | None = None
        mutated_s2_query_config: dict[str, Any] | None = None
        mutated_s2_diagnostic_argument_binding: dict[str, Any] | None = (
            copy.deepcopy(explicit_diagnostic_binding)
            if stage == "S2_EVENT_FRAME"
            else None
        )
        mutated_s5_index: dict[str, Any] | None = None
        s5_actual_overrides: dict[str, dict[str, Any]] = {}
        derived_source_objects: dict[str, Any] | None = None
        if stage == "S2_EVENT_FRAME" and case.get("actual_input_mutation"):
            input_mutation = case["actual_input_mutation"]
            object_kind = input_mutation["object_kind"]
            if object_kind == "EVENT_RELATION_MAPPING":
                mutated_s2_event_mapping = apply_patch(
                    load_json(FIXTURES / "authority-event-relation-mapping.json"),
                    input_mutation["patch"],
                )
            elif object_kind == "QUERY_INTERPRETER_CONFIG":
                mutated_s2_query_config = apply_patch(
                    load_yaml(QUERY_INTERPRETER_CONFIG), input_mutation["patch"]
                )
            elif object_kind == "DIAGNOSTIC_PREDICATE_ARGUMENT_BINDING":
                mutated_s2_diagnostic_argument_binding = apply_patch(
                    load_json(DIAGNOSTIC_ARGUMENT_BINDING_FIXTURE),
                    input_mutation["patch"],
                )
            else:
                raise RuntimeError(
                    f"unsupported S2 actual input mutation: {object_kind}"
                )
        elif stage == "S3_TYPED_SOLVER":
            s3_record, mutated_s3_inputs, _ = load_stage_result("S3")
            mutated_s3_hashes = {
                item["object_kind"]: item["canonical_sha256"]
                for item in s3_record["actual_input_objects"]
            }
            if case.get("actual_input_mutation"):
                input_mutation = case["actual_input_mutation"]
                object_kind = input_mutation["object_kind"]
                mutated_s3_inputs = copy.deepcopy(mutated_s3_inputs)
                mutated_s3_inputs[object_kind] = apply_patch(
                    mutated_s3_inputs[object_kind], input_mutation["patch"]
                )
                mutated_s3_hashes[object_kind] = canonical_sha(mutated_s3_inputs[object_kind])
            derived_source_objects = mutated_s3_inputs
        elif stage == "S5_RUNTIME_BINDING":
            mutated_s5_index = (
                apply_patch(
                    copy.deepcopy(base_index),
                    case.get("object_store_index_patch", []),
                )
                if base_index is not None
                else None
            )
            if case.get("actual_input_mutation"):
                input_mutation = case["actual_input_mutation"]
                actual_path = input_mutation["path"]
                object_kind = input_mutation["object_kind"]
                actual_object = apply_patch(
                    load_json(resolve_review_path(actual_path)),
                    input_mutation["patch"],
                )
                if mutated_s5_index is None:
                    raise RuntimeError("S5 cross-object mutation requires object-store index")
                s5_actual_overrides[actual_path] = actual_object
                derived_source_objects = {
                    object_kind: actual_object,
                    "S5_MUTATED_ACTUAL_OBJECT_PATH": actual_path,
                    "OBJECT_STORE_INDEX": mutated_s5_index,
                }
        recompute_declared_derived(
            mutated, case.get("derived_updates", []), derived_source_objects
        )
        if stage == "S0_NORMALIZED_REQUEST":
            request = load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
            errors = validate_s0(mutated, request)
        elif stage == "S1_CLAUSE_AST":
            errors = validate_s1(mutated, normalized[mutated["request_id"]])
        elif stage == "S2_EVENT_FRAME":
            paired_ast = (
                load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
                if case.get("paired_actual_object_paths")
                and "clause-ast" in case["paired_actual_object_paths"][0]
                else None
            )
            errors = validate_s2(
                mutated,
                normalized[mutated["request_id"]],
                paired_ast,
                mutated_s2_query_config,
                None,
                mutated_s2_event_mapping,
                mutated_s2_diagnostic_argument_binding,
            )
        elif stage == "S3_TYPED_SOLVER":
            assert mutated_s3_inputs is not None and mutated_s3_hashes is not None
            errors = validate_s3(mutated, mutated_s3_inputs, mutated_s3_hashes)
        elif stage == "S4_QUERYIR_EMISSION":
            _, s4_inputs, _ = load_stage_result("S4")
            if "solver_result_version" in mutated:
                query_ir = (
                    copy.deepcopy(mutated["selected_solution"]["queryir_emission_record"]["query_ir"])
                    if case.get("query_ir_from_mutated_emission")
                    else load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
                )
                errors = validate_s4(mutated, query_ir, s4_inputs)
            else:
                typed = load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
                errors = validate_s4(typed, mutated, s4_inputs)
        elif stage == "S5_RUNTIME_BINDING":
            errors = validate_s5(
                mutated, mutated_s5_index, s5_actual_overrides
            )
        else:
            raise ValueError(stage)
        first = errors[0] if errors else None
        registry_failure_code = registry_failure(case["expected_constraint_id"])
        fixture_failure_code = case.get("expected_failure_code")
        results.append(
            {
                "fixture_id": case["fixture_id"],
                "observed_first_error": first,
                "expected_constraint_id": case["expected_constraint_id"],
                "registry_failure_code": registry_failure_code,
                "fixture_failure_code": fixture_failure_code,
                "semantic_mutation_target_count": case["semantic_mutation_target_count"],
                "semantic_mutation_target": {
                    "target_object": mutation["target_object"],
                    "target_path": mutation["target_path"],
                },
                "derived_update_count": len(case.get("derived_updates", [])),
                "passed": first is not None
                and first["constraint_id"] == case["expected_constraint_id"]
                and first["failure_code"] == registry_failure_code
                and fixture_failure_code == registry_failure_code,
            }
        )
    return results


def r3b_authoritative_case_errors(case: dict[str, Any]) -> list[dict[str, str]]:
    """Run an R3-B case through the authoritative stage validator functions."""
    authority = load_yaml(NEGATION_AUTHORITY)
    s0_errors = validate_s0(case["normalized_request"], case["request"])
    if s0_errors:
        return s0_errors
    s1_errors = validate_s1(
        case["clause_ast"],
        case["normalized_request"],
        negation_authority=authority,
        scope_authority_records=case["scope_authority_records"],
    )
    if s1_errors:
        return s1_errors
    s2_errors = validate_s2(
        case["event_frame"],
        case["normalized_request"],
        case["clause_ast"],
        diagnostic_argument_binding=load_json(DIAGNOSTIC_ARGUMENT_BINDING_FIXTURE),
    )
    if s2_errors:
        return s2_errors
    inputs = {
        "NORMALIZED_REQUEST": case["normalized_request"],
        "CLAUSE_AST": case["clause_ast"],
        "EVENT_FRAME": case["event_frame"],
        "NEGATION_SURFACE_SCOPE_AUTHORITY": authority,
        "SCOPE_AUTHORITY_RECORDS": case["scope_authority_records"],
        "DECLARED_ASSERTION_DERIVATION": case["assertion_derivation"],
        "TYPED_SOLUTION_ASSERTIONS": case["typed_solution_assertions"],
    }
    return validate_s3(None, inputs, assertion_only=True)


def run_r3b_authoritative() -> dict[str, list[dict[str, Any]]]:
    """Bind all four positives and fourteen mutations to the main entrypoint."""
    require_failure_code_governance()
    bundle = load_json(R3B_POSITIVE)
    by_id = {case["case_id"]: case for case in bundle["cases"]}
    positive = [
        {
            "case": f"POS-R3B-{case['case_id'].removeprefix('R3B-POS-')}",
            "errors": r3b_authoritative_case_errors(case),
        }
        for case in bundle["cases"]
    ]
    if any(item["errors"] for item in positive):
        return {"positive": positive, "negative": []}
    negative: list[dict[str, Any]] = []
    negative_manifest = load_yaml(R3B_NEGATIVE)
    if negative_manifest.get("mutation_model_path") != "../negative-fixture-semantic-mutation-model.yml":
        raise RuntimeError("R3-B negative fixture manifest is not bound to the R3-D2 mutation model")
    for fixture in negative_manifest["cases"]:
        mutation = validate_mutation_isolation(
            fixture, expected_target_object=fixture["target"]
        )
        candidate = copy.deepcopy(by_id[fixture["base_case_id"]])
        candidate[fixture["target"]] = apply_patch(
            candidate[fixture["target"]], fixture["patch"]
        )
        errors = r3b_authoritative_case_errors(candidate)
        first = errors[0] if errors else None
        registry_failure_code = registry_failure(fixture["expected_constraint_id"])
        negative.append(
            {
                "fixture_id": fixture["fixture_id"],
                "observed_first_error": first,
                "expected_constraint_id": fixture["expected_constraint_id"],
                "registry_failure_code": registry_failure_code,
                "fixture_failure_code": fixture.get("expected_failure_code"),
                "semantic_mutation_target_count": fixture["semantic_mutation_target_count"],
                "semantic_mutation_target": {
                    "target_object": mutation["target_object"],
                    "target_path": mutation["target_path"],
                },
                "derived_update_count": len(fixture.get("derived_updates", [])),
                "passed": first is not None
                and first["constraint_id"] == fixture["expected_constraint_id"]
                and first["failure_code"] == registry_failure_code
                and fixture.get("expected_failure_code") == registry_failure_code,
            }
        )
    return {"positive": positive, "negative": negative}


def r3a_inputs(objects: dict[str, Any]) -> dict[str, Any]:
    return {
        "NORMALIZED_REQUEST": objects["normalized_request"],
        "CLAUSE_AST": objects["clause_ast"],
        "EVENT_FRAME": objects["event_frame"],
        "ENTITY_ONTOLOGY": load_yaml(REPO / "schema/entity-types.yml"),
        "PREDICATE_TYPE_MAPPING": load_json(FIXTURES / "authority-predicate-type-mapping.json"),
        "EVENT_RELATION_MAPPING": load_json(FIXTURES / "authority-event-relation-mapping.json"),
        "PROJECTION_RULE_SET": load_yaml(PROJECTION_RULE_SET),
    }


def r3a_positive_checks(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    objects = bundle["objects"]
    core = objects["typed_solution_core"]
    query_ir = objects["query_ir"]
    inputs = r3a_inputs(objects)
    checks: list[dict[str, Any]] = []
    contract_pass = event_identity_contract_valid()
    checks.append({"check": "EVENT_IDENTITY_CONTRACT", "actual_count": 1, "pass_count": int(contract_pass), "passed": contract_pass})

    schema_pairs = (
        ("normalized-request-schema-candidate.yml", "normalized_request"),
        ("clause-ast-schema-candidate.yml", "clause_ast"),
        ("event-frame-schema-candidate.yml", "event_frame"),
        ("typed-solution-core-schema-candidate.yml", "typed_solution_core"),
        ("query-ir-schema-candidate.yml", "query_ir"),
    )
    schema_pass = sum(schema_valid(schema, objects[key]) for schema, key in schema_pairs)
    checks.append({"check": "DRAFT_2020_12_SCHEMA", "actual_count": len(schema_pairs), "pass_count": schema_pass, "passed": schema_pass == len(schema_pairs)})

    s2_errors = validate_s2(
        objects["event_frame"],
        objects["normalized_request"],
        objects["clause_ast"],
        diagnostic_argument_binding=load_json(DIAGNOSTIC_ARGUMENT_BINDING_FIXTURE),
    )
    semantic_errors = validate_semantic_authority(core, inputs, require_complete=True)
    projection_errors = validate_queryir_projection(core, query_ir, inputs)
    checks.extend([
        {"check": "S2_EVENT_FRAME", "actual_count": 1, "pass_count": int(not s2_errors), "passed": not s2_errors, "errors": s2_errors},
        {"check": "S3_REFERENCE_OVERRIDE_BINDING", "actual_count": len(core["resolved_references"]) + len(core["resolved_overrides"]), "pass_count": (len(core["resolved_references"]) + len(core["resolved_overrides"])) if not semantic_errors else 0, "passed": not semantic_errors, "errors": semantic_errors},
        {"check": "S4_QUERYIR_PROJECTION", "actual_count": len(query_ir["resolved_references"]) + len(query_ir["resolved_overrides"]), "pass_count": (len(query_ir["resolved_references"]) + len(query_ir["resolved_overrides"])) if not projection_errors else 0, "passed": not projection_errors, "errors": projection_errors},
    ])

    reference_by_key = {item["reference_key"]: item for item in core["resolved_references"]}
    event_by_key = {item["event_key"]: item for item in core["resolved_events"]}
    same_count = sum(item["identity_relation"] == "SAME_EVENT" and same_event(event_by_key[item["anaphor_key"]], event_by_key[item["referent_key"]]) for item in reference_by_key.values())
    distinct_count = sum(item["identity_relation"] == "DISTINCT_EVENT" and not same_event(event_by_key[item["anaphor_key"]], event_by_key[item["referent_key"]]) for item in reference_by_key.values())
    override_count = sum(override_pair_valid(event_by_key[item["earlier_event_key"]], event_by_key[item["later_event_key"]], item["overridden_dimension"]) for item in core["resolved_overrides"])
    checks.append({"check": "EVENT_IDENTITY_SAME_DISTINCT_OVERRIDE", "actual_count": 3, "pass_count": same_count + distinct_count + override_count, "same_event_count": same_count, "distinct_event_count": distinct_count, "override_count": override_count, "passed": same_count == distinct_count == override_count == 1})

    pointers = all_json_pointers(query_ir)
    traces = objects["field_traces"]
    core_ids = {
        item[key]
        for collection, key in (("resolved_mentions", "mention_key"), ("resolved_events", "event_key"), ("resolved_relations", "relation_key"), ("resolved_references", "reference_key"), ("resolved_overrides", "override_key"))
        for item in core[collection]
    }
    trace_pass = (
        len(traces) == len(pointers)
        and {item["query_ir_json_pointer"] for item in traces} == set(pointers)
        and all(item["emitted_value_sha256"] == canonical_sha(pointer_get(query_ir, item["query_ir_json_pointer"])) for item in traces)
        and all(
            any(binding["object_kind"] == "TYPED_SOLUTION" and binding["object_sha256"] == canonical_sha(core) and set(binding["source_ids"]) <= core_ids for binding in item["source_bindings"])
            for item in traces
        )
        and all(
            objects["normalized_request"]["normalized_query_text"][span["start_char"]:span["end_char"]] == span["text"]
            for item in traces for binding in item["source_bindings"] for span in binding["source_spans"]
        )
    )
    checks.append({"check": "TRACE_RESOLUTION", "actual_count": len(traces), "pass_count": len(traces) if trace_pass else 0, "passed": trace_pass})

    dag = objects["permission_dag"]
    dag_body = copy.deepcopy(dag)
    declared_dag_sha = dag_body.pop("dag_sha256")
    licensed = {item["semantic_object_id"] for item in objects["material_object_licenses"]}
    dag_ids = {item["semantic_object_id"] for item in dag["nodes"]}
    dag_pass = dag_valid(dag) and declared_dag_sha == canonical_sha(dag_body) and dag_ids == licensed == material_ids(core)
    checks.append({"check": "PERMISSION_DAG_AND_LICENSE", "actual_count": len(dag_ids), "pass_count": len(dag_ids) if dag_pass else 0, "passed": dag_pass})

    probe_results = []
    for probe in objects["minimality_probes"]:
        candidate = apply_patch(core, probe["operation"])
        refresh_core_hashes(candidate)
        errors = validate_reference_override_semantics(candidate, inputs, require_complete=True)
        observed = errors[0]["constraint_id"] if errors else None
        probe_results.append(observed == probe["expected_constraint_id"] and candidate["semantic_object_set_sha256"] == probe["candidate_semantic_object_set_sha256"])
    covered = {item["removed_semantic_object_id"] for item in objects["minimality_probes"]}
    required_coverage = {value for value in material_ids(core) if value.startswith("REF") or value.startswith("OVR")}
    minimality_pass = all(probe_results) and covered == required_coverage
    checks.append({"check": "REFERENCE_OVERRIDE_MINIMALITY", "actual_count": len(probe_results), "pass_count": sum(probe_results), "passed": minimality_pass})

    hashes = {item["object_name"]: item for item in bundle["object_hashes"]}
    canonical_pass = set(hashes) == set(objects) and all(hashes[name]["canonical_sha256"] == canonical_sha(value) and hashes[name]["byte_length"] == len(canonical_bytes(value)) for name, value in objects.items())
    previous = "0" * 64
    chain_pass = len(bundle["independent_hash_chain"]) == len(objects)
    for link in bundle["independent_hash_chain"]:
        body = copy.deepcopy(link)
        declared = body.pop("link_sha256")
        chain_pass &= body["previous_link_sha256"] == previous and body["object_sha256"] == hashes[body["object_name"]]["canonical_sha256"] and declared == canonical_sha(body)
        previous = declared
    checks.append({"check": "PER_OBJECT_CANONICALIZATION", "actual_count": len(objects), "pass_count": len(objects) if canonical_pass else 0, "passed": canonical_pass})
    checks.append({"check": "INDEPENDENT_HASH_CHAIN", "actual_count": len(bundle["independent_hash_chain"]), "pass_count": len(bundle["independent_hash_chain"]) if chain_pass else 0, "passed": chain_pass})

    builder_path = HERE / "build-r3a-reference-override-evidence.py"
    spec = importlib.util.spec_from_file_location("p9b1q_r3a_builder", builder_path)
    builder = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(builder)
    rebuilt = [builder.build() for _ in range(3)]
    determinism_pass = all(canonical_bytes(item) == canonical_bytes(bundle) for item in rebuilt)
    checks.append({"check": "DETERMINISTIC_REBUILD", "actual_count": 3, "pass_count": 3 if determinism_pass else 0, "passed": determinism_pass})
    return checks


def run_r3a() -> dict[str, Any]:
    require_failure_code_governance()
    bundle = load_json(R3A_POSITIVE)
    positive = r3a_positive_checks(bundle)
    if not all(item["passed"] for item in positive):
        return {"result": "FAIL_CLOSED", "positive": positive, "negative": []}
    manifest = load_yaml(R3A_NEGATIVE)
    if manifest.get("mutation_model_path") != "../negative-fixture-semantic-mutation-model.yml":
        raise RuntimeError("R3-A negative fixture manifest is not bound to the R3-D2 mutation model")
    negative = []
    for case in manifest["cases"]:
        objects = copy.deepcopy(bundle["objects"])
        mutation = validate_mutation_isolation(
            case, expected_target_object=case["target"]
        )
        objects[case["target"]] = apply_patch(objects[case["target"]], case["patch"])
        inputs = r3a_inputs(objects)
        if case["target"] == "typed_solution_core":
            errors = validate_semantic_authority(objects["typed_solution_core"], inputs, require_complete=True)
        elif case["target"] == "query_ir":
            if not schema_valid("query-ir-schema-candidate.yml", objects["query_ir"]):
                errors = [error("CNS-EMIT-QUERYIR_SCHEMA", "SCHEMA_INVALID", "/")]
            else:
                errors = validate_queryir_projection(objects["typed_solution_core"], objects["query_ir"], inputs)
        elif case["target"] == "permission_dag":
            ids = {item["semantic_object_id"] for item in objects["permission_dag"]["nodes"]}
            errors = [] if dag_valid(objects["permission_dag"]) and ids == material_ids(objects["typed_solution_core"]) else [error("CNS-SOLVER-LICENSE_DAG", "LICENSE_DAG_INVALID", "/permission_dag")]
        elif case["target"] == "minimality_probes":
            coverage = {item["removed_semantic_object_id"] for item in objects["minimality_probes"]}
            required = {value for value in material_ids(objects["typed_solution_core"]) if value.startswith("REF") or value.startswith("OVR")}
            errors = [] if coverage == required else [error("CNS-SOLVER-MINIMALITY", "MINIMALITY_WITNESS_INVALID", "/minimality_probes")]
        else:
            raise RuntimeError(case["target"])
        first = errors[0] if errors else None
        registry_failure_code = registry_failure(case["expected_constraint_id"])
        negative.append({
            "fixture_id": case["fixture_id"],
            "observed_first_error": first,
            "semantic_mutation_target_count": case["semantic_mutation_target_count"],
            "semantic_mutation_target": {
                "target_object": mutation["target_object"],
                "target_path": mutation["target_path"],
            },
            "derived_update_count": len(case.get("derived_updates", [])),
            "expected_constraint_id": case["expected_constraint_id"],
            "registry_failure_code": registry_failure_code,
            "fixture_failure_code": case.get("expected_failure_code"),
            "passed": first is not None
            and first["constraint_id"] == case["expected_constraint_id"]
            and first["failure_code"] == registry_failure_code
            and case.get("expected_failure_code") == registry_failure_code,
        })
    return {"result": "PASS" if all(item["passed"] for item in negative) else "FAIL_CLOSED", "positive": positive, "negative": negative, "positive_pass_count": sum(item["passed"] for item in positive), "negative_pass_count": sum(item["passed"] for item in negative)}


def one_run() -> dict[str, Any]:
    failure_code_governance = require_failure_code_governance()
    positive = run_positive()
    minimality = run_minimality()
    negative = run_negative()
    r3b = run_r3b_authoritative()
    positive.extend(r3b["positive"])
    negative.extend(r3b["negative"])
    return {
        "registry_failure_governance": failure_code_governance,
        "positive": positive,
        "minimality": minimality,
        "negative": negative,
        "positive_pass_count": sum(not item["errors"] for item in positive),
        "minimality_pass_count": sum(item["passed"] for item in minimality),
        "negative_pass_count": sum(item["passed"] for item in negative),
    }


def build_summary() -> dict[str, Any]:
    runs = [one_run() for _ in range(3)]
    encoded = [canonical_bytes(run) for run in runs]
    if len(set(encoded)) != 1:
        raise RuntimeError("repeat runs are not byte-identical")
    payload = runs[0]
    complete = (
        payload["registry_failure_governance"]["result"] == "PASS"
        and payload["positive_pass_count"] == len(payload["positive"])
        and payload["minimality_pass_count"] == len(payload["minimality"])
        and payload["negative_pass_count"] == len(payload["negative"])
    )
    schema_gate = run_schema_gate()
    return {
        "summary_version": "0.1-candidate",
        "validator_id": "p9b1q-reference-stage-semantic-validator",
        "validator_version": "0.1",
        "executable_sha256": sha_bytes(Path(__file__).read_bytes()),
        "configuration_path": "stage-semantic-validator-contract.yml",
        "configuration_sha256": sha_bytes(CONTRACT.read_bytes()),
        "repeat_runs": 3,
        "run_payload_sha256": sha_bytes(encoded[0]),
        "result": "PASS" if complete else "FAIL_CLOSED",
        "schema_gate": {
            key: schema_gate[key]
            for key in (
                "gate_id",
                "ajv_version",
                "strict",
                "compiled_schema_count",
                "fixture_pair_count",
                "valid_fixture_count",
                "result",
            )
        } | {
            "runner_sha256": sha_bytes(SCHEMA_GATE.read_bytes()),
            "lockfile_sha256": sha_bytes((HERE / "package-lock.json").read_bytes()),
        },
        **payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("all", "positive", "minimality", "negative", "r3a", "r3b"), default="all")
    args = parser.parse_args()
    if args.mode == "all":
        result: Any = build_summary()
    elif args.mode == "positive":
        result = run_positive()
    elif args.mode == "minimality":
        result = run_minimality()
    elif args.mode == "r3a":
        result = run_r3a()
    elif args.mode == "r3b":
        result = run_r3b_authoritative()
    else:
        result = run_negative()
    print(canonical_bytes(result).decode("utf-8"), end="")
    if args.mode == "r3b":
        complete = all(not item["errors"] for item in result["positive"]) and all(
            item["passed"] for item in result["negative"]
        )
        return 0 if complete else 1
    if args.mode in ("all", "r3a"):
        return 0 if result["result"] == "PASS" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
