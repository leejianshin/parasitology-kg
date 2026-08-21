#!/usr/bin/env python3
"""Executable R3-B source, scope-path, target, and assertion authority."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIX = HERE / "fixtures"
AUTHORITY_PATH = HERE / "negation-surface-scope-authority.yml"
AUTHORITY_SCHEMA_PATH = HERE / "negation-surface-scope-authority-schema-candidate.yml"
POSITIVE_PATH = FIX / "r3b-negation-scope-positive.json"
NEGATIVE_PATH = FIX / "r3b-negation-scope-negative-fixtures.yml"
SCHEMA_GATE = HERE / "strict-schema-gate.mjs"
R3B_SCHEMA_GATE = HERE / "r3b-strict-schema-gate.mjs"


def cbytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def csha(value: Any) -> str:
    return hashlib.sha256(cbytes(value)).hexdigest()


def raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def pointer_parent(value: Any, pointer: str) -> tuple[Any, str]:
    tokens = pointer.lstrip("/").split("/")
    parent = value
    for token in tokens[:-1]:
        parent = parent[int(token)] if isinstance(parent, list) else parent[token]
    return parent, tokens[-1]


def apply_patch(value: Any, operations: list[dict[str, Any]]) -> Any:
    result = copy.deepcopy(value)
    for operation in operations:
        parent, token = pointer_parent(result, operation["path"])
        key: Any = int(token) if isinstance(parent, list) else token
        if operation["op"] == "replace":
            parent[key] = copy.deepcopy(operation["value"])
        elif operation["op"] == "remove":
            parent.pop(key)
        else:
            raise ValueError(operation["op"])
    return result


def error(constraint: str, code: str, pointer: str) -> dict[str, str]:
    return {"constraint_id": constraint, "failure_code": code, "json_pointer": pointer}


def ordered(errors: list[dict[str, str]]) -> list[dict[str, str]]:
    order = {value: index for index, value in enumerate(load_yaml(AUTHORITY_PATH)["constraint_order"])}
    return sorted(errors, key=lambda item: (order[item["constraint_id"]], item["json_pointer"]))


def external_schema_valid(schema_name: str, value: Any) -> bool:
    completed = subprocess.run(
        ["node", str(SCHEMA_GATE), "--validate-schema", schema_name],
        cwd=HERE,
        input=cbytes(value),
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def authority_schema_valid() -> bool:
    completed = subprocess.run(["node", str(R3B_SCHEMA_GATE)], cwd=HERE, capture_output=True, check=False)
    return completed.returncode == 0 and json.loads(completed.stdout).get("result") == "PASS"


def node_path(nodes: dict[str, dict[str, Any]], start: str, target: str) -> list[str] | None:
    pending: list[tuple[str, list[str]]] = [(start, [start])]
    while pending:
        node_id, path = pending.pop(0)
        if node_id == target:
            return path
        pending.extend((child, path + [child]) for child in nodes[node_id]["child_node_ids"])
    return None


def source_proposition(ast: dict[str, Any], marker: dict[str, Any]) -> str | None:
    span = marker["source_span"]
    candidates = [
        node for node in ast["nodes"]
        if node["node_kind"] == "PROPOSITION"
        and node["source_span"]["start_char"] <= span["start_char"]
        and span["end_char"] <= node["source_span"]["end_char"]
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda node: node["source_span"]["end_char"] - node["source_span"]["start_char"])["node_id"]


def target_type(case: dict[str, Any], target_id: str) -> str | None:
    ast, frame = case["clause_ast"], case["event_frame"]
    nodes = {item["node_id"]: item for item in ast["nodes"]}
    mentions = {item["surface_mention_id"]: item for item in ast["surface_mentions"]}
    if target_id in nodes and nodes[target_id]["node_kind"] == "PROPOSITION":
        return "EVENT_PROPOSITION"
    if target_id in mentions and any(
        target_id in slot["source_ids"]
        for event in frame["frames"] for slot in event["participant_slots"]
    ):
        return "PARTICIPANT_MENTION"
    return None


def derive_scope(case: dict[str, Any], marker: dict[str, Any]) -> dict[str, Any] | None:
    ast = case["clause_ast"]
    nodes = {item["node_id"]: item for item in ast["nodes"]}
    mentions = {item["surface_mention_id"]: item for item in ast["surface_mentions"]}
    if marker["containing_node_id"] not in nodes or len(marker["scope_target_candidate_ids"]) != 1:
        return None
    target = marker["scope_target_candidate_ids"][0]
    containing = marker["containing_node_id"]
    source_node = source_proposition(ast, marker)
    if target in nodes:
        path = node_path(nodes, containing, target)
        if path is None:
            return None
        if target == containing and nodes[target]["node_kind"] == "PROPOSITION":
            relation = "SELF_PROPOSITION"
        elif source_node == target and nodes[containing]["node_kind"] == "QUESTION":
            relation = "QUESTION_FOCUS_TO_SOURCE_PROPOSITION"
        else:
            return None
        return {"path_node_ids": path, "path_relation": relation, "target_semantic_type": target_type(case, target)}
    if target in mentions:
        mention_node = mentions[target]["containing_node_id"]
        path = node_path(nodes, containing, mention_node)
        if path is None:
            return None
        return {"path_node_ids": path + [target], "path_relation": "DESCENDANT_MENTION", "target_semantic_type": target_type(case, target)}
    return None


def record_by_marker(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["marker_id"]: item for item in case["scope_authority_records"]}


def validate_s1(case: dict[str, Any]) -> list[dict[str, str]]:
    authority = load_yaml(AUTHORITY_PATH)
    ast = case["clause_ast"]
    text = case["normalized_request"]["normalized_query_text"]
    nodes = {item["node_id"]: item for item in ast["nodes"]}
    records = record_by_marker(case)
    errors: list[dict[str, str]] = []
    for index, marker in enumerate(ast["assertion_markers"]):
        pointer = f"/assertion_markers/{index}"
        span = marker["source_span"]
        surface = span["text"]
        classification = authority["source_classification"].get(surface)
        exact_span = 0 <= span["start_char"] < span["end_char"] <= len(text) and text[span["start_char"]:span["end_char"]] == surface
        if classification is None or not exact_span or classification["marker_kind"] != marker["marker_kind"]:
            errors.append(error("CNS-AST-MARKER-SURFACE-AUTHORITY", "MARKER_SURFACE_UNLICENSED", pointer))
            continue
        containing = nodes.get(marker["containing_node_id"])
        member = containing is not None and marker["marker_id"] in containing["assertion_marker_ids"]
        inside = containing is not None and containing["source_span"]["start_char"] <= span["start_char"] and span["end_char"] <= containing["source_span"]["end_char"]
        derived = derive_scope(case, marker)
        record = records.get(marker["marker_id"])
        if not member or not inside or derived is None or record is None:
            errors.append(error("CNS-AST-SCOPE-PATH-AUTHORITY", "SCOPE_PATH_INVALID", pointer))
            continue
        if record["grammar_class"] != classification["grammar_class"]:
            errors.append(error("CNS-AST-MARKER-SURFACE-AUTHORITY", "MARKER_SURFACE_UNLICENSED", pointer))
            continue
        grammar = authority["grammar_classes"][classification["grammar_class"]]
        if derived["target_semantic_type"] not in grammar["allowable_target_types"] or record["target_semantic_type"] != derived["target_semantic_type"]:
            errors.append(error("CNS-AST-TARGET-TYPE-AUTHORITY", "TARGET_TYPE_INVALID", pointer))
            continue
        if derived["path_relation"] not in grammar["allowable_path_relations"] or record["path_relation"] != derived["path_relation"] or record["path_node_ids"] != derived["path_node_ids"]:
            errors.append(error("CNS-AST-SCOPE-PATH-AUTHORITY", "SCOPE_PATH_INVALID", pointer))
    if set(records) != {item["marker_id"] for item in ast["assertion_markers"]}:
        errors.append(error("CNS-AST-SCOPE-PATH-AUTHORITY", "SCOPE_PATH_INVALID", "/scope_authority_records"))
    return ordered(errors)


def validate_s2(case: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    ast, frame = case["clause_ast"], case["event_frame"]
    marker_by_id = {item["marker_id"]: item for item in ast["assertion_markers"]}
    for index, record in enumerate(case["scope_authority_records"]):
        marker = marker_by_id.get(record["marker_id"])
        if marker is None:
            errors.append(error("CNS-AST-SCOPE-PATH-AUTHORITY", "SCOPE_PATH_INVALID", f"/scope_authority_records/{index}"))
            continue
        target = marker["scope_target_candidate_ids"][0]
        if record["target_semantic_type"] == "EVENT_PROPOSITION":
            bound = sum(target in event["source_ast_node_ids"] for event in frame["frames"])
        else:
            bound = sum(target in slot["source_ids"] for event in frame["frames"] for slot in event["participant_slots"])
        if bound != 1:
            errors.append(error("CNS-AST-TARGET-TYPE-AUTHORITY", "TARGET_TYPE_INVALID", f"/scope_authority_records/{index}"))
    return ordered(errors)


def independently_derive_assertion(case: dict[str, Any]) -> dict[str, Any]:
    authority = load_yaml(AUTHORITY_PATH)
    ast, frame = case["clause_ast"], case["event_frame"]
    records = record_by_marker(case)
    markers = sorted(ast["assertion_markers"], key=lambda item: (item["source_span"]["start_char"], item["source_span"]["end_char"], item["marker_id"]))
    event_sources = {source for event in frame["frames"] for source in event["source_ast_node_ids"]}
    event_negators: list[str] = []
    participant_counts: dict[str, int] = {}
    for marker in markers:
        classification = authority["source_classification"].get(marker["source_span"]["text"], {})
        target = marker["scope_target_candidate_ids"][0]
        if classification.get("semantic_effect") == "EVENT_NEGATION" and target in event_sources:
            event_negators.append(marker["marker_id"])
        elif classification.get("semantic_effect") == "PARTICIPANT_NEGATION":
            participant_counts[target] = participant_counts.get(target, 0) + 1
    event_assertion = "NEGATED" if len(event_negators) % 2 else "AFFIRMED"
    participant_assertions = {target: "NEGATED" if count % 2 else "AFFIRMED" for target, count in sorted(participant_counts.items())}
    event_type = frame["frames"][0]["event_type_domain"][0]
    finding = (
        "NEGATIVE"
        if participant_assertions and all(value == "NEGATED" for value in participant_assertions.values())
        else "POSITIVE" if event_type == "DIAGNOSTIC_FINDING" else "NOT_APPLICABLE"
    )
    return {
        "ordered_marker_ids": [item["marker_id"] for item in markers],
        "event_negator_count": len(event_negators),
        "derived_event_assertion": event_assertion,
        "participant_assertions": participant_assertions,
        "derived_finding_polarity": finding,
    }


def validate_s3(case: dict[str, Any]) -> list[dict[str, str]]:
    derived = independently_derive_assertion(case)
    declared = case["event_frame"]["frames"][0]["assertion"]
    errors: list[dict[str, str]] = []
    if case["assertion_derivation"] != derived or declared["assertion_status"] != derived["derived_event_assertion"] or declared["finding_polarity"] != derived["derived_finding_polarity"]:
        errors.append(error("CNS-SOLVER-ASSERTION-DERIVATION", "ASSERTION_DERIVATION_MISMATCH", "/assertion_derivation"))
    return errors


def case_errors(case: dict[str, Any]) -> list[dict[str, str]]:
    s1 = validate_s1(case)
    if s1:
        return s1
    s2 = validate_s2(case)
    if s2:
        return s2
    return validate_s3(case)


def positive_checks(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    cases = bundle["cases"]
    schema_total = 1 + len(cases) * 3
    schema_pass = int(authority_schema_valid())
    for case in cases:
        schema_pass += int(external_schema_valid("normalized-request-schema-candidate.yml", case["normalized_request"]))
        schema_pass += int(external_schema_valid("clause-ast-schema-candidate.yml", case["clause_ast"]))
        schema_pass += int(external_schema_valid("event-frame-schema-candidate.yml", case["event_frame"]))
    checks: list[dict[str, Any]] = [{"check": "DRAFT_2020_12_SCHEMA", "actual_count": schema_total, "pass_count": schema_pass, "passed": schema_pass == schema_total}]
    for stage, validator in (("S1_SURFACE_SCOPE", validate_s1), ("S2_TARGET_BINDING", validate_s2), ("S3_ASSERTION_DERIVATION", validate_s3)):
        results = [not validator(case) for case in cases]
        checks.append({"check": stage, "actual_count": len(results), "pass_count": sum(results), "passed": all(results)})
    expected_ids = {"R3B-POS-EVENT-NEGATION", "R3B-POS-OBJECT-NEGATION", "R3B-POS-DOUBLE-NEGATION", "R3B-POS-WH-CONTROL"}
    checks.append({"check": "POSITIVE_NEGATION_CHAINS", "actual_count": 4, "pass_count": len(expected_ids & {case["case_id"] for case in cases}), "passed": {case["case_id"] for case in cases} == expected_ids})

    actual_objects: list[tuple[str, Any]] = [("authority", load_yaml(AUTHORITY_PATH))]
    for case in cases:
        for key in ("request", "normalized_request", "clause_ast", "event_frame", "scope_authority_records", "assertion_derivation"):
            actual_objects.append((f"{case['case_id']}.{key}", case[key]))
    hashes = {item["object_name"]: item for item in bundle["object_hashes"]}
    canonical_ok = set(hashes) == {name for name, _ in actual_objects} and all(hashes[name]["canonical_sha256"] == csha(value) and hashes[name]["byte_length"] == len(cbytes(value)) for name, value in actual_objects)
    checks.append({"check": "PER_OBJECT_CANONICALIZATION", "actual_count": len(actual_objects), "pass_count": len(actual_objects) if canonical_ok else 0, "passed": canonical_ok})
    previous = "0" * 64
    chain_ok = len(bundle["independent_hash_chain"]) == len(actual_objects)
    for link in bundle["independent_hash_chain"]:
        body = copy.deepcopy(link)
        declared = body.pop("link_sha256")
        chain_ok &= body["previous_link_sha256"] == previous and body["object_sha256"] == hashes[body["object_name"]]["canonical_sha256"] and declared == csha(body)
        previous = declared
    checks.append({"check": "INDEPENDENT_HASH_CHAIN", "actual_count": len(actual_objects), "pass_count": len(actual_objects) if chain_ok else 0, "passed": chain_ok})
    builder_path = HERE / "build-r3b-negation-evidence.py"
    spec = importlib.util.spec_from_file_location("r3b_builder", builder_path)
    builder = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(builder)
    rebuilds = [builder.build() for _ in range(3)]
    deterministic = all(cbytes(value) == cbytes(bundle) for value in rebuilds)
    checks.append({"check": "DETERMINISTIC_REBUILD", "actual_count": 3, "pass_count": 3 if deterministic else 0, "passed": deterministic})
    return checks


def run() -> dict[str, Any]:
    bundle = load_json(POSITIVE_PATH)
    checks = positive_checks(bundle)
    if not all(item["passed"] for item in checks):
        return {"result": "FAIL_CLOSED", "positive": checks, "negative": []}
    by_id = {case["case_id"]: case for case in bundle["cases"]}
    negative = []
    for fixture in load_yaml(NEGATIVE_PATH)["cases"]:
        if len(fixture["patch"]) != 1:
            raise RuntimeError(fixture["fixture_id"])
        case = copy.deepcopy(by_id[fixture["base_case_id"]])
        case[fixture["target"]] = apply_patch(case[fixture["target"]], fixture["patch"])
        errors = case_errors(case)
        observed = errors[0]["constraint_id"] if errors else None
        negative.append({"fixture_id": fixture["fixture_id"], "mutation_count": 1, "expected_constraint_id": fixture["expected_constraint_id"], "observed_first_constraint_id": observed, "passed": observed == fixture["expected_constraint_id"]})
    return {"result": "PASS" if all(item["passed"] for item in negative) else "FAIL_CLOSED", "positive": checks, "negative": negative, "positive_pass_count": sum(item["passed"] for item in checks), "negative_pass_count": sum(item["passed"] for item in negative)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("r3b",), default="r3b")
    parser.parse_args()
    result = run()
    print(cbytes(result).decode(), end="")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
