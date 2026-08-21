#!/usr/bin/env python3
"""Standalone harness over the shared R3-B semantic authority implementation."""

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

import negation_semantic_authority as semantic


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIX = HERE / "fixtures"
AUTHORITY_PATH = HERE / "negation-surface-scope-authority.yml"
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


def typed_assertions(case: dict[str, Any]) -> list[dict[str, Any]]:
    return case.get("typed_solution_assertions") or [
        {
            "frame_id": frame["frame_id"],
            "assertion_status": frame["assertion"]["assertion_status"],
            "finding_polarity": frame["assertion"]["finding_polarity"],
        }
        for frame in case["event_frame"]["frames"]
    ]


def validate_s1(case: dict[str, Any]) -> list[dict[str, str]]:
    return semantic.validate_surface_scope_target(
        case["clause_ast"], case["normalized_request"], load_yaml(AUTHORITY_PATH), case["scope_authority_records"]
    )


def validate_s2(case: dict[str, Any]) -> list[dict[str, str]]:
    return semantic.validate_target_binding(
        case["clause_ast"], case["event_frame"], load_yaml(AUTHORITY_PATH), case["scope_authority_records"]
    )


def independently_derive_assertion(case: dict[str, Any]) -> dict[str, Any]:
    return semantic.derive_assertion(
        case["clause_ast"], case["event_frame"], load_yaml(AUTHORITY_PATH), case["scope_authority_records"]
    )


def validate_s3(case: dict[str, Any]) -> list[dict[str, str]]:
    _, errors = semantic.validate_assertion_derivation(
        case["clause_ast"],
        case["normalized_request"],
        case["event_frame"],
        typed_assertions(case),
        load_yaml(AUTHORITY_PATH),
        case["scope_authority_records"],
        case["assertion_derivation"],
    )
    return errors


def case_errors(case: dict[str, Any]) -> list[dict[str, str]]:
    for validator in (validate_s1, validate_s2, validate_s3):
        errors = validator(case)
        if errors:
            return errors
    return []


def positive_checks(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    cases = bundle["cases"]
    schema_total = 1 + len(cases) * 3
    schema_pass = int(authority_schema_valid())
    for case in cases:
        schema_pass += int(external_schema_valid("normalized-request-schema-candidate.yml", case["normalized_request"]))
        schema_pass += int(external_schema_valid("clause-ast-schema-candidate.yml", case["clause_ast"]))
        schema_pass += int(external_schema_valid("event-frame-schema-candidate.yml", case["event_frame"]))
    checks: list[dict[str, Any]] = [{
        "check": "DRAFT_2020_12_SCHEMA", "actual_count": schema_total,
        "pass_count": schema_pass, "passed": schema_pass == schema_total,
    }]
    for stage, validator in (
        ("S1_SURFACE_SCOPE", validate_s1),
        ("S2_TARGET_BINDING", validate_s2),
        ("S3_ASSERTION_DERIVATION", validate_s3),
    ):
        results = [not validator(case) for case in cases]
        checks.append({"check": stage, "actual_count": len(results), "pass_count": sum(results), "passed": all(results)})
    expected_ids = {
        "R3B-POS-EVENT-NEGATION", "R3B-POS-OBJECT-NEGATION",
        "R3B-POS-DOUBLE-NEGATION", "R3B-POS-WH-CONTROL",
    }
    actual_ids = {case["case_id"] for case in cases}
    checks.append({
        "check": "POSITIVE_NEGATION_CHAINS", "actual_count": 4,
        "pass_count": len(expected_ids & actual_ids), "passed": actual_ids == expected_ids,
    })

    actual_objects: list[tuple[str, Any]] = [("authority", load_yaml(AUTHORITY_PATH))]
    for case in cases:
        for key in (
            "request", "normalized_request", "clause_ast", "event_frame",
            "scope_authority_records", "assertion_derivation", "typed_solution_assertions",
        ):
            actual_objects.append((f"{case['case_id']}.{key}", case[key]))
    hashes = {item["object_name"]: item for item in bundle["object_hashes"]}
    canonical_ok = set(hashes) == {name for name, _ in actual_objects} and all(
        hashes[name]["canonical_sha256"] == csha(value)
        and hashes[name]["byte_length"] == len(cbytes(value))
        for name, value in actual_objects
    )
    checks.append({
        "check": "PER_OBJECT_CANONICALIZATION", "actual_count": len(actual_objects),
        "pass_count": len(actual_objects) if canonical_ok else 0, "passed": canonical_ok,
    })
    previous = "0" * 64
    chain_ok = len(bundle["independent_hash_chain"]) == len(actual_objects)
    for link in bundle["independent_hash_chain"]:
        body = copy.deepcopy(link)
        declared = body.pop("link_sha256")
        chain_ok &= (
            body["previous_link_sha256"] == previous
            and body["object_sha256"] == hashes[body["object_name"]]["canonical_sha256"]
            and declared == csha(body)
        )
        previous = declared
    checks.append({
        "check": "INDEPENDENT_HASH_CHAIN", "actual_count": len(actual_objects),
        "pass_count": len(actual_objects) if chain_ok else 0, "passed": chain_ok,
    })
    builder_path = HERE / "build-r3b-negation-evidence.py"
    spec = importlib.util.spec_from_file_location("r3b_builder", builder_path)
    builder = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(builder)
    deterministic = all(cbytes(value) == cbytes(bundle) for value in [builder.build() for _ in range(3)])
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
        negative.append({
            "fixture_id": fixture["fixture_id"], "mutation_count": 1,
            "expected_constraint_id": fixture["expected_constraint_id"],
            "observed_first_constraint_id": observed,
            "passed": observed == fixture["expected_constraint_id"],
        })
    return {
        "result": "PASS" if all(item["passed"] for item in negative) else "FAIL_CLOSED",
        "positive": checks, "negative": negative,
        "positive_pass_count": sum(item["passed"] for item in checks),
        "negative_pass_count": sum(item["passed"] for item in negative),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("r3b",), default="r3b")
    parser.parse_args()
    result = run()
    print(cbytes(result).decode(), end="")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
