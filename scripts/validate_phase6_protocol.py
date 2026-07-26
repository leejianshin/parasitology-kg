#!/usr/bin/env python3
"""Validate the Phase 6 Clonorchis student-RAG acceptance protocol."""

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
PHASE6_DIR = ROOT / "phase6" / "clonorchis-sinensis"
PLAN_PATH = PHASE6_DIR / "acceptance-plan.yml"
SUITE_PATH = PHASE6_DIR / "test-cases.yml"
RUBRIC_PATH = PHASE6_DIR / "teacher-rubric.yml"
PHASE5_PLAN_PATH = (
    ROOT / "phase5" / "clonorchis-sinensis" / "admission-plan.yml"
)
DERIVED_DIR = ROOT / "derived" / "clonorchis-sinensis" / "phase5-batch1"
RAG_CORPUS_DIR = (
    ROOT / "derived" / "clonorchis-sinensis" / "phase6-rag-corpus"
)
SOURCE_REGISTRY_PATH = ROOT / "sources" / "registry.yml"

EXPECTED_CATEGORY_COUNTS = {
    "basic_fact": 3,
    "relation_query": 3,
    "one_health": 3,
    "intervention": 2,
    "source_traceability": 1,
    "boundary_trap": 6,
}
EXPECTED_DISPOSITION_COUNTS = {
    "ANSWER": 11,
    "PARTIAL": 3,
    "ABSTAIN": 4,
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
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} must be an object")
        rows.append(row)
    return rows


def graph_context(root: Path = ROOT) -> dict[str, Any]:
    derived_dir = (
        root / "derived" / "clonorchis-sinensis" / "phase5-batch1"
    )
    nodes = load_jsonl(derived_dir / "nodes.jsonl")
    edges = load_jsonl(derived_dir / "edges.jsonl")
    manifest = load_yaml(derived_dir / "manifest.yml")
    rag_corpus_manifest = load_yaml(
        root
        / "derived"
        / "clonorchis-sinensis"
        / "phase6-rag-corpus"
        / "manifest.yml"
    )
    registry = load_yaml(root / "sources" / "registry.yml")
    phase5_plan = load_yaml(
        root / "phase5" / "clonorchis-sinensis" / "admission-plan.yml"
    )

    edge_by_atom: dict[str, dict[str, Any]] = {}
    for edge in edges:
        atom_id = edge["qualifiers"]["source_atom_id"]
        if atom_id in edge_by_atom:
            raise ValueError(f"duplicate derived atom: {atom_id}")
        edge_by_atom[atom_id] = edge

    later_batch_atoms: set[str] = set()
    for batch in phase5_plan["batches"]:
        if batch["batch_id"] == "P5-B1":
            continue
        later_batch_atoms.update(batch.get("edge_atom_ids", []))
        later_batch_atoms.update(batch.get("qualifier_atom_ids", []))

    return {
        "node_ids": {node["id"] for node in nodes},
        "edge_by_atom": edge_by_atom,
        "manifest": manifest,
        "rag_corpus_manifest": rag_corpus_manifest,
        "registered_source_ids": {
            item["source_id"] for item in registry["sources"]
        },
        "later_batch_atoms": later_batch_atoms,
        "phase5_plan": phase5_plan,
    }


def validate_protocol_data(
    plan: dict[str, Any],
    suite: dict[str, Any],
    rubric: dict[str, Any],
    root: Path = ROOT,
) -> dict[str, int]:
    context = graph_context(root)
    manifest = context["manifest"]
    rag_corpus_manifest = context["rag_corpus_manifest"]
    phase5_plan = context["phase5_plan"]

    if plan["status"] != "READY_FOR_REVIEW":
        raise ValueError("Phase 6 plan must remain READY_FOR_REVIEW")
    if suite["status"] != "FIXED_PENDING_REVIEW":
        raise ValueError("test suite must remain FIXED_PENDING_REVIEW")
    if rubric["status"] != "FIXED_PENDING_REVIEW":
        raise ValueError("teacher rubric must remain FIXED_PENDING_REVIEW")
    if suite["suite_id"] != "clonorchis_phase6_fixed_questions_v1":
        raise ValueError("unexpected suite_id")
    if plan["authority"]["test_suite"] != (
        "phase6/clonorchis-sinensis/test-cases.yml"
    ):
        raise ValueError("plan points to the wrong test suite")
    if plan["authority"]["teacher_rubric"] != (
        "phase6/clonorchis-sinensis/teacher-rubric.yml"
    ):
        raise ValueError("plan points to the wrong teacher rubric")

    baseline = plan["knowledge_baseline"]
    if baseline["admitted_batch_id"] != "P5-B1":
        raise ValueError("Phase 6 baseline is not P5-B1")
    if (
        baseline["canonical_input_sha256"]
        != manifest["canonical_input_sha256"]
    ):
        raise ValueError("Phase 6 canonical hash differs from derived manifest")
    if baseline["node_count"] != manifest["counts"]["nodes"]:
        raise ValueError("Phase 6 node count differs from derived manifest")
    if baseline["edge_count"] != manifest["counts"]["edges"]:
        raise ValueError("Phase 6 edge count differs from derived manifest")
    if (
        rag_corpus_manifest["canonical_input_sha256"]
        != manifest["canonical_input_sha256"]
    ):
        raise ValueError("Phase 6 RAG corpus uses a different canonical input")
    if rag_corpus_manifest["counts"] != {
        "documents": 14,
        "nodes": 14,
        "edges": 10,
        "sources": 6,
    }:
        raise ValueError("Phase 6 RAG corpus counts are unexpected")
    if rag_corpus_manifest["allowed_runtime_files"] != [
        "corpus.md",
        "source-catalog.yml",
    ]:
        raise ValueError("Phase 6 RAG runtime allowlist changed")

    if phase5_plan["approval_gate"]["batch_2_and_3_write"] != "NOT_AUTHORIZED":
        raise ValueError("later Phase 5 batches are not blocked")
    if (
        phase5_plan["approval_gate"]["student_rag_release"]
        != "NOT_AUTHORIZED_PENDING_PHASE6"
    ):
        raise ValueError("Phase 5 student RAG release boundary changed")
    authorization = plan["authorization"]
    if authorization["student_rag_release"] != "NOT_AUTHORIZED":
        raise ValueError("Phase 6 student release must remain unauthorized")
    if authorization["phase5_batch_2_and_3_write"] != "NOT_AUTHORIZED":
        raise ValueError("Phase 6 plan authorizes later Phase 5 batches")
    if plan["execution_design"]["web_access"] != "DISABLED":
        raise ValueError("web access must be disabled for paired runs")
    if plan["execution_design"]["external_memory"] != "DISABLED":
        raise ValueError("external memory must be disabled for paired runs")
    if plan["execution_design"]["clean_session_per_case"] is not True:
        raise ValueError("each Phase 6 question needs a clean session")
    if plan["execution_design"]["rag_context"] != (
        "PHASE6_ALLOWLIST_CORPUS_ONLY"
    ):
        raise ValueError("Phase 6 RAG context is not allowlisted")
    if plan["execution_design"]["rag_corpus_files"] != [
        "derived/clonorchis-sinensis/phase6-rag-corpus/corpus.md",
        "derived/clonorchis-sinensis/phase6-rag-corpus/source-catalog.yml",
    ]:
        raise ValueError("Phase 6 RAG corpus file allowlist changed")

    cases = suite["test_cases"]
    if suite["counts"]["total"] != len(cases) or len(cases) != 18:
        raise ValueError("test suite must contain exactly 18 cases")
    case_ids = [case["case_id"] for case in cases]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("duplicate Phase 6 case_id")
    if any(
        re.fullmatch(r"CS-RAG-[A-Z][0-9]{2}", case_id) is None
        for case_id in case_ids
    ):
        raise ValueError("invalid Phase 6 case_id format")
    questions = [case["question_zh"] for case in cases]
    if len(set(questions)) != len(questions):
        raise ValueError("duplicate Phase 6 question")

    category_counts = Counter(case["category"] for case in cases)
    disposition_counts = Counter(
        case["expected_disposition"] for case in cases
    )
    if dict(category_counts) != EXPECTED_CATEGORY_COUNTS:
        raise ValueError(
            f"unexpected category counts: {dict(category_counts)}"
        )
    if dict(disposition_counts) != EXPECTED_DISPOSITION_COUNTS:
        raise ValueError(
            f"unexpected disposition counts: {dict(disposition_counts)}"
        )
    if suite["counts"]["by_category"] != EXPECTED_CATEGORY_COUNTS:
        raise ValueError("declared category counts do not match contract")
    if suite["counts"]["expected_answer"] != 11:
        raise ValueError("declared ANSWER count must be 11")
    if suite["counts"]["expected_partial"] != 3:
        raise ValueError("declared PARTIAL count must be 3")
    if suite["counts"]["expected_abstain"] != 4:
        raise ValueError("declared ABSTAIN count must be 4")

    covered_entities: set[str] = set()
    covered_atoms: set[str] = set()
    edge_by_atom = context["edge_by_atom"]
    for case in cases:
        disposition = case["expected_disposition"]
        entity_ids = set(case["required_entity_ids"])
        atom_ids = set(case["required_relation_atom_ids"])
        if case["failure_severity"] not in {"critical", "major", "minor"}:
            raise ValueError(f"{case['case_id']} has invalid failure severity")

        if disposition in {"ANSWER", "PARTIAL"}:
            if not entity_ids or not atom_ids:
                raise ValueError(
                    f"{case['case_id']} needs entities and relations"
                )
            if case["citation_requirement"] != (
                "registered_support_for_each_atom"
            ):
                raise ValueError(
                    f"{case['case_id']} has weak citation requirement"
                )
            if disposition == "ANSWER" and case["coverage_gap"] is not None:
                raise ValueError(
                    f"{case['case_id']} ANSWER cannot declare a coverage gap"
                )
            if disposition == "PARTIAL" and not case["coverage_gap"]:
                raise ValueError(
                    f"{case['case_id']} PARTIAL needs a coverage gap"
                )
        elif disposition == "ABSTAIN":
            if entity_ids or atom_ids:
                raise ValueError(
                    f"{case['case_id']} ABSTAIN cannot require graph facts"
                )
            if case["citation_requirement"] != "none":
                raise ValueError(
                    f"{case['case_id']} ABSTAIN cannot require citations"
                )
            if not case["coverage_gap"]:
                raise ValueError(
                    f"{case['case_id']} ABSTAIN needs a coverage gap"
                )
        else:
            raise ValueError(
                f"{case['case_id']} has invalid expected disposition"
            )

        unknown_entities = entity_ids - context["node_ids"]
        if unknown_entities:
            raise ValueError(
                f"{case['case_id']} unknown entities: "
                f"{sorted(unknown_entities)}"
            )
        unknown_atoms = atom_ids - set(edge_by_atom)
        if unknown_atoms:
            raise ValueError(
                f"{case['case_id']} unknown atoms: {sorted(unknown_atoms)}"
            )
        leaked_atoms = atom_ids & context["later_batch_atoms"]
        if leaked_atoms:
            raise ValueError(
                f"{case['case_id']} later-batch leakage: "
                f"{sorted(leaked_atoms)}"
            )
        for atom_id in atom_ids:
            evidence_source_ids = {
                evidence["source_id"]
                for evidence in edge_by_atom[atom_id]["evidence"]
            }
            unknown_sources = (
                evidence_source_ids - context["registered_source_ids"]
            )
            if unknown_sources:
                raise ValueError(
                    f"{case['case_id']} atom {atom_id} has unknown sources: "
                    f"{sorted(unknown_sources)}"
                )
        covered_entities.update(entity_ids)
        covered_atoms.update(atom_ids)

    if covered_entities != context["node_ids"]:
        raise ValueError("fixed suite does not exercise every P5-B1 node")
    if covered_atoms != set(edge_by_atom):
        raise ValueError("fixed suite does not exercise every P5-B1 edge")

    criteria_points = sum(
        item["points"] for item in rubric["criteria"].values()
    )
    if criteria_points != rubric["maximum_score_per_case"]:
        raise ValueError("teacher rubric points do not sum to maximum")
    if rubric["maximum_score_per_case"] != 10:
        raise ValueError("teacher rubric maximum must be 10")
    thresholds = plan["pass_gate"]["thresholds"]
    if thresholds["rag_boundary_abstention_rate_min"] != 1.0:
        raise ValueError("boundary abstention threshold must be 100%")
    if thresholds["rag_traceability_rate_min"] != 1.0:
        raise ValueError("traceability threshold must be 100%")
    if thresholds["one_health_causal_overstatement_max"] != 0:
        raise ValueError("One Health causal overstatement threshold must be 0")
    if thresholds["unregistered_source_count_max"] != 0:
        raise ValueError("unregistered source threshold must be 0")

    serialized = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((root / "phase6").rglob("*"))
        if path.is_file()
    )
    serialized += (
        "\n"
        + (root / "templates" / "phase6-rag-run-template.yml").read_text(
            encoding="utf-8"
        )
    )
    private_path_patterns = [
        re.compile(r"[A-Za-z]:\\" + "Users" + r"\\", re.IGNORECASE),
        re.compile("parasitology-kg" + "-private", re.IGNORECASE),
        re.compile("chrome" + "download", re.IGNORECASE),
        re.compile("market" + "-lab", re.IGNORECASE),
    ]
    if any(pattern.search(serialized) for pattern in private_path_patterns):
        raise ValueError("Phase 6 protocol contains a private path")

    return {
        "cases": len(cases),
        "answer": disposition_counts["ANSWER"],
        "partial": disposition_counts["PARTIAL"],
        "abstain": disposition_counts["ABSTAIN"],
        "nodes": len(covered_entities),
        "edges": len(covered_atoms),
    }


def validate_run_structure(
    run_path: Path,
    suite: dict[str, Any],
    root: Path = ROOT,
) -> dict[str, int | str]:
    run = load_yaml(run_path)
    context = graph_context(root)
    cases = {case["case_id"]: case for case in suite["test_cases"]}
    if run["suite_id"] != suite["suite_id"]:
        raise ValueError("run suite_id does not match fixed suite")
    if run["status"] != "COMPLETED":
        raise ValueError("run status must be COMPLETED")
    if run["mode"] not in {"baseline", "rag"}:
        raise ValueError("run mode must be baseline or rag")

    metadata = run["run_metadata"]
    required_metadata = [
        "model_provider",
        "model_name",
        "model_version",
        "interface_or_tool",
        "generated_at",
    ]
    if any(not metadata.get(field) for field in required_metadata):
        raise ValueError("run is missing model or time metadata")
    if metadata["web_access"] != "DISABLED":
        raise ValueError("run used web access")
    if metadata["external_memory"] != "DISABLED":
        raise ValueError("run used external memory")
    if metadata["session_isolation"] != "one_clean_session_per_case":
        raise ValueError("run did not isolate every question in a clean session")
    if metadata["question_order"] != "as_listed_in_suite":
        raise ValueError("run changed the fixed question order")

    responses = run["responses"]
    response_ids = [response["case_id"] for response in responses]
    if len(responses) != len(cases) or set(response_ids) != set(cases):
        raise ValueError("run must contain every fixed case exactly once")
    if len(response_ids) != len(set(response_ids)):
        raise ValueError("run contains duplicate case responses")

    disposition_map = {
        "ANSWER": "answered",
        "PARTIAL": "partial",
        "ABSTAIN": "abstained",
    }
    disposition_matches = 0
    provenance_contract_matches = 0
    boundary_abstentions = 0
    for response in responses:
        case = cases[response["case_id"]]
        if response["disposition"] not in {
            "answered",
            "partial",
            "abstained",
        }:
            raise ValueError(
                f"{response['case_id']} has invalid run disposition"
            )
        if not response["answer_text"].strip():
            raise ValueError(f"{response['case_id']} has empty answer_text")
        entity_ids = set(response["retrieved_entity_ids"])
        atom_ids = set(response["used_relation_atom_ids"])
        source_ids = set(response["cited_source_ids"])
        if not entity_ids <= context["node_ids"]:
            raise ValueError(f"{response['case_id']} cites unknown entity IDs")
        if not atom_ids <= set(context["edge_by_atom"]):
            raise ValueError(f"{response['case_id']} cites unknown atom IDs")
        if atom_ids & context["later_batch_atoms"]:
            raise ValueError(f"{response['case_id']} leaks later-batch atoms")
        if not source_ids <= context["registered_source_ids"]:
            raise ValueError(f"{response['case_id']} cites unknown sources")

        expected_run_disposition = disposition_map[
            case["expected_disposition"]
        ]
        if response["disposition"] == expected_run_disposition:
            disposition_matches += 1
        if (
            case["expected_disposition"] == "ABSTAIN"
            and response["disposition"] == "abstained"
            and response["reason_code"] == "corpus_not_covered"
        ):
            boundary_abstentions += 1

        required_atoms = set(case["required_relation_atom_ids"])
        required_entities = set(case["required_entity_ids"])
        supported_atoms = 0
        for atom_id in required_atoms:
            accepted_sources = {
                evidence["source_id"]
                for evidence in context["edge_by_atom"][atom_id]["evidence"]
            }
            if accepted_sources & source_ids:
                supported_atoms += 1
        if (
            case["expected_disposition"] in {"ANSWER", "PARTIAL"}
            and required_atoms <= atom_ids
            and required_entities <= entity_ids
            and supported_atoms == len(required_atoms)
        ):
            provenance_contract_matches += 1

    return {
        "mode": run["mode"],
        "responses": len(responses),
        "disposition_matches": disposition_matches,
        "provenance_contract_matches": provenance_contract_matches,
        "boundary_abstentions": boundary_abstentions,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        type=Path,
        help="Optionally validate one completed baseline or RAG run record.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        plan = load_yaml(PLAN_PATH)
        suite = load_yaml(SUITE_PATH)
        rubric = load_yaml(RUBRIC_PATH)
        summary = validate_protocol_data(plan, suite, rubric, ROOT)
        print(
            "PHASE6_PROTOCOL_VALIDATION=PASS "
            f"cases={summary['cases']} answer={summary['answer']} "
            f"partial={summary['partial']} abstain={summary['abstain']} "
            f"nodes={summary['nodes']} edges={summary['edges']}"
        )
        if args.run:
            run_summary = validate_run_structure(
                args.run.resolve(), suite, ROOT
            )
            print(
                "PHASE6_RUN_STRUCTURE=PASS "
                f"mode={run_summary['mode']} "
                f"responses={run_summary['responses']} "
                f"disposition_matches="
                f"{run_summary['disposition_matches']}/18 "
                f"provenance_contract="
                f"{run_summary['provenance_contract_matches']}/14 "
                f"boundary_abstentions="
                f"{run_summary['boundary_abstentions']}/4"
            )
        return 0
    except (
        json.JSONDecodeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        yaml.YAMLError,
    ) as exc:
        print(f"PHASE6_PROTOCOL_VALIDATION=FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
