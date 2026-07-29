#!/usr/bin/env python3
"""Validate the Phase 9-A controlled-RAG design contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
P9_DIR = ROOT / "phase9" / "clonorchis-sinensis"
RUNTIME_PATH = P9_DIR / "runtime-contract.yml"
RESPONSE_PATH = P9_DIR / "response-schema.yml"
AUDIT_PATH = P9_DIR / "audit-log-schema.yml"
REVIEW_PATH = P9_DIR / "reviewer-evidence-admission.yml"
RELEASE_PATH = P9_DIR / "release-boundary.yml"
PLAN_PATH = P9_DIR / "acceptance-cases" / "plan.yml"
PCMS_MANIFEST_PATH = (
    ROOT / "derived" / "clonorchis-sinensis" / "pcms-v1" / "manifest.yml"
)
PCMS_NODES_PATH = (
    ROOT / "derived" / "clonorchis-sinensis" / "pcms-v1" / "nodes.jsonl"
)
PCMS_EDGES_PATH = (
    ROOT / "derived" / "clonorchis-sinensis" / "pcms-v1" / "edges.jsonl"
)
PCMS_AUTHORITY_PATH = (
    ROOT
    / "phase7"
    / "clonorchis-sinensis"
    / "pilot-content-minimum-set-authority-review.yml"
)
PCMS_SUITE_PATH = (
    ROOT
    / "phase7"
    / "clonorchis-sinensis"
    / "pilot-content-minimum-set-regression.yml"
)
SOURCE_REGISTRY_PATH = ROOT / "sources" / "registry.yml"

SOURCE_COMMIT = "9a9ff5a17de0fc6d32595730f10dfbebd55d9897"
CANONICAL_HASH = (
    "3e83162b75bc0bfcf40b7fd67eba13c610d7050f9bc77f64baa008d664e4411f"
)
ALLOWED_RUNTIME_INPUTS = [
    "derived/clonorchis-sinensis/pcms-v1/nodes.jsonl",
    "derived/clonorchis-sinensis/pcms-v1/edges.jsonl",
    (
        "phase7/clonorchis-sinensis/"
        "pilot-content-minimum-set-authority-review.yml"
    ),
    "sources/registry.yml",
]
EXPECTED_DISPOSITIONS = {"ANSWER": 11, "PARTIAL": 3, "ABSTAIN": 2}
REQUIRED_HARD_FAILS = {
    "UNREGISTERED_SOURCE",
    "UNKNOWN_ENTITY_ID",
    "UNKNOWN_CLAIM_ID",
    "UNREVIEWED_CLAIM",
    "MISSING_REQUIRED_QUALIFIER",
    "HIDDEN_STUDENT_CITATION",
    "DIAGNOSTIC_CLUE_PROMOTED_TO_CONFIRMATION",
    "ASSOCIATION_PROMOTED_TO_CAUSALITY",
    "MODEL_MEMORY_GAP_FILL",
    "EXTERNAL_WEB_GAP_FILL",
    "STUDENT_DATA_IN_PUBLIC_ARTIFACT",
}
EXPECTED_REQUIRED_QUALIFIERS = {
    "PCMS-029": {
        "jurisdiction": "China",
        "routine_first_choice": False,
        "operational_note": "complex_sampling",
    },
    "PCMS-030": {
        "authority": "WHO",
        "recommendation_role": "recommended",
    },
    "PCMS-031": {
        "authority": "US_CDC",
        "recommendation_role": "alternative",
    },
    "PCMS-032": {
        "hazard_not_individual_probability": True,
        "individual_cancer_certainty": False,
    },
    "PCMS-035": {"direct_human_infectivity": False},
    "PCMS-036": {"universal_elimination_claim": False},
}
EXPECTED_REVIEW_RECORDS = {
    "P6-INDEPENDENT-R02": {
        "sha256": (
            "306f43902ecd83d14342155a99e3cd91"
            "cab1307df534bbff6812ff235dfd6048"
        ),
        "completion": "PROVISIONAL_INDEPENDENT_SENSITIVITY_REVIEW",
        "aggregation": "NOT_AUTHORIZED",
    },
    "P6-INDEPENDENT-R03": {
        "sha256": (
            "e4f54438153a13cc86c0900eb038221"
            "d3fa5d3604a912faed62094779efc3d4e"
        ),
        "completion": "INCOMPLETE_NOT_FOR_QUANTITATIVE_AGGREGATION",
        "aggregation": "PROHIBITED",
    },
}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be a mapping")
    return data


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} must be an object")
        rows.append(value)
    return rows


def contract_context(root: Path = ROOT) -> dict[str, Any]:
    manifest = load_yaml(
        root
        / "derived"
        / "clonorchis-sinensis"
        / "pcms-v1"
        / "manifest.yml"
    )
    nodes = load_jsonl(
        root
        / "derived"
        / "clonorchis-sinensis"
        / "pcms-v1"
        / "nodes.jsonl"
    )
    edges = load_jsonl(
        root
        / "derived"
        / "clonorchis-sinensis"
        / "pcms-v1"
        / "edges.jsonl"
    )
    authority = load_yaml(
        root
        / "phase7"
        / "clonorchis-sinensis"
        / "pilot-content-minimum-set-authority-review.yml"
    )
    suite = load_yaml(
        root
        / "phase7"
        / "clonorchis-sinensis"
        / "pilot-content-minimum-set-regression.yml"
    )
    registry = load_yaml(root / "sources" / "registry.yml")

    node_ids = {row["id"] for row in nodes}
    if len(node_ids) != len(nodes):
        raise ValueError("PCMS contains duplicate entity IDs")

    edge_by_claim: dict[str, dict[str, Any]] = {}
    supporting_narrative_by_claim: dict[str, dict[str, Any]] = {}
    for edge in edges:
        claim_id = edge["qualifiers"]["source_atom_id"]
        if claim_id in edge_by_claim:
            raise ValueError(f"duplicate relation claim ID: {claim_id}")
        edge_by_claim[claim_id] = edge
        for supporting_id in edge["qualifiers"].get(
            "supporting_narrative_atom_ids", []
        ):
            if supporting_id in supporting_narrative_by_claim:
                raise ValueError(
                    f"duplicate supporting narrative claim ID: {supporting_id}"
                )
            supporting_narrative_by_claim[supporting_id] = edge

    narrative_by_claim: dict[str, dict[str, Any]] = {}
    for group in authority["candidate_groups"]:
        for claim in group["claims"]:
            if claim.get("claim_role") != "narrative_fact":
                continue
            claim_id = claim["claim_id"]
            if claim_id in narrative_by_claim:
                raise ValueError(f"duplicate narrative claim ID: {claim_id}")
            narrative_by_claim[claim_id] = claim

    registered_sources = {
        source["source_id"]: source for source in registry["sources"]
    }
    all_claims = (
        set(edge_by_claim)
        | set(narrative_by_claim)
        | set(supporting_narrative_by_claim)
    )

    return {
        "manifest": manifest,
        "nodes": nodes,
        "node_ids": node_ids,
        "edges": edges,
        "edge_by_claim": edge_by_claim,
        "narrative_by_claim": narrative_by_claim,
        "supporting_narrative_by_claim": supporting_narrative_by_claim,
        "all_claims": all_claims,
        "registered_sources": registered_sources,
        "suite": suite,
    }


def validate_contract_data(
    runtime: dict[str, Any],
    response_schema: dict[str, Any],
    audit_schema: dict[str, Any],
    review: dict[str, Any],
    release: dict[str, Any],
    plan: dict[str, Any],
    root: Path = ROOT,
) -> dict[str, int]:
    context = contract_context(root)
    manifest = context["manifest"]

    if runtime["status"] != "P9A_CONTRACT_READY_FOR_REVIEW":
        raise ValueError("P9-A runtime contract has an invalid status")
    authority = runtime["authority"]
    if authority["knowledge_version"] != "clonorchis_pcms_v1":
        raise ValueError("runtime knowledge version is not PCMS v1")
    if authority["source_commit"] != SOURCE_COMMIT:
        raise ValueError("runtime source commit changed")
    if authority["canonical_input_sha256"] != CANONICAL_HASH:
        raise ValueError("runtime canonical hash changed")
    if manifest["canonical_input_sha256"] != CANONICAL_HASH:
        raise ValueError("PCMS manifest canonical hash changed")
    expected_counts = authority["expected_counts"]
    if expected_counts != {
        "entities": manifest["counts"]["nodes"],
        "relation_claims": manifest["counts"]["edges"],
        "narrative_claims": manifest["counts"]["narrative_claims"],
    }:
        raise ValueError("runtime PCMS counts differ from manifest")
    if authority["allowed_runtime_inputs"] != ALLOWED_RUNTIME_INPUTS:
        raise ValueError("runtime input allowlist changed")
    prohibited = set(authority["prohibited_runtime_inputs"])
    if not {
        "external_web",
        "model_memory",
        "raw_teacher_workbooks",
        "student_rosters_or_responses",
    }.issubset(prohibited):
        raise ValueError("runtime prohibited-input boundary is incomplete")
    execution = runtime["execution"]
    if execution["web_access"] != "DISABLED":
        raise ValueError("web access must remain disabled")
    if execution["external_memory"] != "DISABLED":
        raise ValueError("external memory must remain disabled")
    if execution["retrieval_mode"] != "ALLOWLIST_ONLY":
        raise ValueError("retrieval must remain allowlist-only")
    if execution["unverified_runtime_state"] != "REFUSE_TO_SERVE":
        raise ValueError("unverified runtime state must refuse service")

    disposition = runtime["disposition_policy"]
    if disposition["allowed"] != ["ANSWER", "PARTIAL", "ABSTAIN"]:
        raise ValueError("answer disposition enum changed")
    visible = runtime["student_visible_provenance"]
    if visible["hard_gate"] is not True:
        raise ValueError("student-visible provenance must be a hard gate")
    if visible["backend_trace_is_not_sufficient"] is not True:
        raise ValueError("backend trace cannot substitute for visible sources")
    if set(visible["each_material_claim_must_show"]) != {
        "claim_id",
        "source_id",
        "source_label",
        "locator",
    }:
        raise ValueError("student-visible citation fields changed")
    if visible["unresolved_or_hidden_citation"] != "ABSTAIN":
        raise ValueError("hidden citations must force abstention")
    if set(runtime["hard_fail_conditions"]) != REQUIRED_HARD_FAILS:
        raise ValueError("runtime hard-fail set changed")
    qualifier_controls = {
        item["claim_id"]: item["required"]
        for item in runtime["required_qualifier_controls"]
    }
    if qualifier_controls != EXPECTED_REQUIRED_QUALIFIERS:
        raise ValueError("required qualifier controls changed")
    for claim_id, required in qualifier_controls.items():
        actual = context["edge_by_claim"].get(claim_id)
        if actual is None:
            raise ValueError(f"{claim_id} qualifier control has no relation")
        for key, expected in required.items():
            if actual["qualifiers"].get(key) != expected:
                raise ValueError(
                    f"{claim_id} qualifier {key} differs from PCMS"
                )
    semantic_boundaries = runtime["semantic_boundaries"]
    if not all(semantic_boundaries.values()):
        raise ValueError("all semantic boundaries must remain enabled")
    if runtime["determinism"]["repeated_run_count_for_acceptance"] != 3:
        raise ValueError("acceptance must use three repeated runs")

    if len(context["nodes"]) != 31 or len(context["edges"]) != 40:
        raise ValueError("PCMS graph counts changed")
    if len(context["narrative_by_claim"]) != 6:
        raise ValueError("PCMS narrative claim count changed")
    if context["all_claims"] != (
        set(context["edge_by_claim"])
        | set(context["supporting_narrative_by_claim"])
        | {f"PCMS-{n:03d}" for n in range(1, 7)}
    ):
        raise ValueError("PCMS admitted claim set is inconsistent")
    for claim_id, edge in context["edge_by_claim"].items():
        if edge["relation_status"] != "reviewed":
            raise ValueError(f"{claim_id} is not reviewed")
        if edge["subject"] not in context["node_ids"]:
            raise ValueError(f"{claim_id} has unknown subject")
        if edge["object"] not in context["node_ids"]:
            raise ValueError(f"{claim_id} has unknown object")
        for evidence in edge["evidence"]:
            if evidence["source_id"] not in context["registered_sources"]:
                raise ValueError(f"{claim_id} has an unregistered source")
            if not evidence.get("locator"):
                raise ValueError(f"{claim_id} has evidence without locator")
    for claim_id, claim in context["narrative_by_claim"].items():
        for evidence in claim["evidence"]:
            if evidence["source_id"] not in context["registered_sources"]:
                raise ValueError(f"{claim_id} has an unregistered source")
            if not evidence.get("locator"):
                raise ValueError(f"{claim_id} has evidence without locator")

    for schema_name, schema in {
        "response": response_schema,
        "audit": audit_schema,
    }.items():
        if schema.get("$schema") != (
            "https://json-schema.org/draft/2020-12/schema"
        ):
            raise ValueError(f"{schema_name} schema is not draft 2020-12")
        if schema.get("type") != "object":
            raise ValueError(f"{schema_name} schema root is not an object")
        if schema.get("additionalProperties") is not False:
            raise ValueError(f"{schema_name} schema permits unknown fields")

    response_props = response_schema["properties"]
    if response_props["knowledge_version"].get("const") != (
        "clonorchis_pcms_v1"
    ):
        raise ValueError("response knowledge version is not frozen")
    if response_props["source_commit"].get("const") != SOURCE_COMMIT:
        raise ValueError("response source commit is not frozen")
    citation_props = response_props["citations"]["items"]["properties"]
    if citation_props["visible_to_student"].get("const") is not True:
        raise ValueError("response schema allows hidden citations")
    citation_required = set(
        response_props["citations"]["items"]["required"]
    )
    if not {
        "claim_id",
        "source_id",
        "source_label",
        "locator",
        "visible_to_student",
    }.issubset(citation_required):
        raise ValueError("response citations omit required visible fields")

    audit_props = audit_schema["properties"]
    if audit_props["knowledge_authority"]["properties"][
        "source_commit"
    ].get("const") != SOURCE_COMMIT:
        raise ValueError("audit schema source commit is not frozen")
    privacy_props = audit_props["privacy"]["properties"]
    if privacy_props["student_identifier_logged"].get("const") is not False:
        raise ValueError("audit schema permits student identifiers")
    if privacy_props["public_export_allowed"].get("const") is not False:
        raise ValueError("private audit records cannot be public exports")

    if review["status"] != "DEIDENTIFIED_PROCESS_EVIDENCE_ONLY":
        raise ValueError("review evidence status changed")
    records = {
        record["reviewer_id"]: record
        for record in review["review_records"]
    }
    if set(records) != set(EXPECTED_REVIEW_RECORDS):
        raise ValueError("unexpected reviewer records")
    for reviewer_id, expected in EXPECTED_REVIEW_RECORDS.items():
        record = records[reviewer_id]
        if record["private_workbook_sha256"] != expected["sha256"]:
            raise ValueError(f"{reviewer_id} workbook hash changed")
        if record["completion_status"] != expected["completion"]:
            raise ValueError(f"{reviewer_id} completion status changed")
        if record["quantitative_aggregation"] != expected["aggregation"]:
            raise ValueError(f"{reviewer_id} aggregation rule changed")
        if "FORMAL_RELEASE_APPROVAL" not in record["not_admissible_as"]:
            raise ValueError(f"{reviewer_id} can be misread as release approval")
    disagreement = records["P6-INDEPENDENT-R02"][
        "critical_disagreement"
    ]
    if disagreement["legacy_case_id"] != "CS-RAG-F03":
        raise ValueError("critical review disagreement changed")
    if disagreement["status"] != "UNRESOLVED_REQUIRES_ADJUDICATION":
        raise ValueError("critical disagreement was resolved without record")
    intake = review["review_intake_contract"]
    if intake["unresolved_critical_disagreement"]["release_effect"] != (
        "BLOCK"
    ):
        raise ValueError("critical reviewer disagreement must block release")

    if release["status"] != "DESIGN_ONLY_NOT_IMPLEMENTED":
        raise ValueError("P9-A release status changed")
    not_authorized = release["not_authorized"]
    for key in (
        "runtime_implementation",
        "model_api_calls",
        "web_deployment",
        "learning_platform_integration",
        "real_student_testing",
        "student_release",
        "changes_to_formal_pcms_knowledge",
        "public_raw_teacher_workbooks",
        "public_student_data",
    ):
        if not_authorized.get(key) is not True:
            raise ValueError(f"{key} must remain unauthorized")
    release_gates = {
        item["gate_id"]: item for item in release["release_gates"]
    }
    if release_gates["P9-G05"]["current"] != "BLOCKED_BY_CS-RAG-F03":
        raise ValueError("review disagreement release blocker changed")
    if release_gates["P9-G06"]["current"] != "NOT_AUTHORIZED":
        raise ValueError("student pilot received premature authorization")
    if release["learning_platform_role"]["prohibited_role"] != (
        "SOURCE_OF_CONTROLLED_RAG_MEDICAL_GENERATION"
    ):
        raise ValueError("learning platform generation boundary changed")

    if plan["status"] != "FIXED_FOR_CONTRACT_REVIEW":
        raise ValueError("P9-A acceptance plan status changed")
    source_suite = context["suite"]
    if plan["source_suite"]["path"] != (
        "phase7/clonorchis-sinensis/"
        "pilot-content-minimum-set-regression.yml"
    ):
        raise ValueError("acceptance source suite path changed")
    if plan["source_suite"]["suite_id"] != source_suite["suite_id"]:
        raise ValueError("acceptance source suite ID changed")
    source_cases = {
        case["case_id"]: case for case in source_suite["test_cases"]
    }
    migrations = plan["case_migrations"]
    if len(migrations) != 16:
        raise ValueError("P9-A acceptance plan must contain 16 cases")
    if len({item["p9_case_id"] for item in migrations}) != 16:
        raise ValueError("duplicate P9-A case IDs")
    if any(
        re.fullmatch(r"P9A-T[0-9]{2}", item["p9_case_id"]) is None
        for item in migrations
    ):
        raise ValueError("invalid P9-A case ID")
    if {item["source_case_id"] for item in migrations} != set(source_cases):
        raise ValueError("P9-A does not migrate every PCMS case exactly once")
    dispositions = Counter()
    for item in migrations:
        source_case = source_cases[item["source_case_id"]]
        if item["expected_disposition"] != source_case[
            "expected_disposition"
        ]:
            raise ValueError(
                f"{item['p9_case_id']} disposition differs from PCMS"
            )
        if item["severity"] not in {"critical", "major", "minor"}:
            raise ValueError(f"{item['p9_case_id']} has invalid severity")
        unknown_claims = (
            set(source_case["required_claim_ids"]) - context["all_claims"]
        )
        if unknown_claims:
            raise ValueError(
                f"{item['p9_case_id']} has unknown claims: "
                f"{sorted(unknown_claims)}"
            )
        dispositions[item["expected_disposition"]] += 1
    if dict(dispositions) != EXPECTED_DISPOSITIONS:
        raise ValueError("P9-A disposition counts changed")
    if plan["counts"] != {
        "total": 16,
        "answer": 11,
        "partial": 3,
        "abstain": 2,
        "repeated_runs_per_case": 3,
    }:
        raise ValueError("P9-A declared case counts changed")
    global_acceptance = plan["global_acceptance"]
    for key in (
        "unsupported_deterministic_answers",
        "non_allowlist_claims",
        "medical_hard_failures",
        "public_student_identifiers",
    ):
        if global_acceptance[key] != 0:
            raise ValueError(f"{key} acceptance threshold must remain zero")
    if global_acceptance["student_visible_claim_citations"] != "100%":
        raise ValueError("visible citation acceptance threshold changed")
    if plan["teacher_gate"]["unresolved_critical_disagreement"] != (
        "BLOCK_RELEASE"
    ):
        raise ValueError("teacher disagreement must block release")

    return {
        "entities": len(context["nodes"]),
        "relation_claims": len(context["edges"]),
        "narrative_claims": len(context["narrative_by_claim"]),
        "acceptance_cases": len(migrations),
        "review_records": len(records),
    }


def validate(root: Path = ROOT) -> dict[str, int]:
    p9_dir = root / "phase9" / "clonorchis-sinensis"
    return validate_contract_data(
        load_yaml(p9_dir / "runtime-contract.yml"),
        load_yaml(p9_dir / "response-schema.yml"),
        load_yaml(p9_dir / "audit-log-schema.yml"),
        load_yaml(p9_dir / "reviewer-evidence-admission.yml"),
        load_yaml(p9_dir / "release-boundary.yml"),
        load_yaml(p9_dir / "acceptance-cases" / "plan.yml"),
        root,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        counts = validate(args.root.resolve())
        print(
            "PHASE9_CONTRACT=PASS "
            f"entities={counts['entities']} "
            f"relation_claims={counts['relation_claims']} "
            f"narrative_claims={counts['narrative_claims']} "
            f"acceptance_cases={counts['acceptance_cases']} "
            f"review_records={counts['review_records']}"
        )
        return 0
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"PHASE9_CONTRACT=FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
