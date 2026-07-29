#!/usr/bin/env python3
"""Validate the Phase 9-A controlled-RAG design contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


ROOT = Path(__file__).resolve().parents[1]
P9_DIR = ROOT / "phase9" / "clonorchis-sinensis"
RUNTIME_PATH = P9_DIR / "runtime-contract.yml"
RESPONSE_PATH = P9_DIR / "response-schema.yml"
AUDIT_PATH = P9_DIR / "audit-log-schema.yml"
REVIEW_PATH = P9_DIR / "reviewer-evidence-admission.yml"
RELEASE_PATH = P9_DIR / "release-boundary.yml"
PLAN_PATH = P9_DIR / "acceptance-cases" / "plan.yml"
BUNDLE_MANIFEST_PATH = P9_DIR / "runtime-bundle-manifest.yml"
ADJUDICATION_CASES_PATH = (
    P9_DIR / "acceptance-cases" / "adjudication-cases.yml"
)
ADJUDICATION_SCHEMA_PATH = (
    P9_DIR / "acceptance-cases" / "adjudication-record-schema.yml"
)
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
RUNTIME_BUNDLE_HASH = (
    "868abdbb5c619d87397167ebaeefe1b1d243a8124acf41e60114bda777187302"
)
RUNTIME_MANIFEST_HASH = (
    "67a57cc7791006c277e778a518d0c12f30aaf8ee9849fdef46932e412feb3ca8"
)
SOURCE_TREE_SHA1 = "b0e3ac1e4a40e541d0c621f98521b28b689989d6"
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
    "AUTHORITY_BUNDLE_MISMATCH",
    "NO_SAFE_ADMITTED_ANSWER",
    "UNREGISTERED_SOURCE",
    "UNKNOWN_ENTITY_ID",
    "UNKNOWN_CLAIM_ID",
    "UNREVIEWED_CLAIM",
    "MISSING_REQUIRED_QUALIFIER",
    "HIDDEN_STUDENT_CITATION",
    "CITATION_CLAIM_MISMATCH",
    "CITATION_LOCATOR_MISMATCH",
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
REQUIRED_QUALIFIER_DISPLAY = {
    "PCMS-029": (
        "限定：该结论适用于中国第10版教材及WS 309—2009语境；"
        "取材较复杂；不等同于所有患者的常规首选检查。"
    ),
    "PCMS-030": "限定：这是WHO的推荐用药表述。",
    "PCMS-031": "限定：这是美国CDC的替代药物表述。",
    "PCMS-032": (
        "限定：该分类表示致癌危害，不表示个体必然患癌或"
        "给出个体患癌概率。"
    ),
    "PCMS-035": "限定：进入淡水环境的虫卵不能直接感染人。",
    "PCMS-036": (
        "限定：综合防控建议不等同于在所有场景下必然消除传播。"
    ),
}
GAP_DISPLAY_TEXT = {
    "NOT_COVERED": "当前知识库未覆盖所请求的结论，不能给出确定回答。",
    "PARTIALLY_COVERED": "当前知识库仅部分覆盖所请求的结论。",
    "QUALIFIER_UNRESOLVED": "必要限定条件尚未解决，不能扩展现有结论。",
    "SOURCE_UNRESOLVED": "合法来源尚未解决，不能给出该结论。",
    "AUTHORITY_MISMATCH": "运行证据包未通过校验，当前拒绝回答。",
}
EXPECTED_REVIEW_RECORDS = {
    "P6-INDEPENDENT-R02": {
        "sha256": (
            "306f43902ecd83d14342155a99e3cd91"
            "cab1307df534bbff6812ff235dfd6048"
        ),
        "completion": "PROVISIONAL",
        "completion_detail": "INDEPENDENT_SENSITIVITY_REVIEW",
        "all_scores_present": True,
        "aggregation": "NOT_AUTHORIZED",
    },
    "P6-INDEPENDENT-R03": {
        "sha256": (
            "e4f54438153a13cc86c0900eb038221"
            "d3fa5d3604a912faed62094779efc3d4e"
        ),
        "completion": "INCOMPLETE",
        "completion_detail": "NOT_FOR_QUANTITATIVE_AGGREGATION",
        "all_scores_present": False,
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


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha1(path: Path) -> str:
    payload = path.read_bytes()
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def git_revision_value(root: Path, revision: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", revision],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def verify_runtime_bundle(
    root: Path = ROOT, verify_source_commit: bool = True
) -> dict[str, Any]:
    manifest_path = (
        root
        / "phase9"
        / "clonorchis-sinensis"
        / "runtime-bundle-manifest.yml"
    )
    manifest = load_yaml(manifest_path)
    if file_sha256(manifest_path) != RUNTIME_MANIFEST_HASH:
        raise ValueError("runtime bundle manifest file hash changed")
    if manifest["knowledge_version"] != "clonorchis_pcms_v1":
        raise ValueError("runtime bundle knowledge version changed")
    if manifest["source_commit"] != SOURCE_COMMIT:
        raise ValueError("runtime bundle source commit changed")
    if manifest["source_tree_sha1"] != SOURCE_TREE_SHA1:
        raise ValueError("runtime bundle source tree changed")
    digest_input = dict(manifest)
    declared_bundle_hash = digest_input.pop("bundle_sha256")
    actual_bundle_hash = canonical_sha256(digest_input)
    if declared_bundle_hash != actual_bundle_hash:
        raise ValueError("runtime bundle aggregate hash is invalid")
    if actual_bundle_hash != RUNTIME_BUNDLE_HASH:
        raise ValueError("runtime bundle aggregate hash changed")

    entries = manifest["files"]
    if [item["path"] for item in entries] != ALLOWED_RUNTIME_INPUTS:
        raise ValueError("runtime bundle file list changed")
    if verify_source_commit:
        actual_tree = git_revision_value(root, f"{SOURCE_COMMIT}^{{tree}}")
        if actual_tree != SOURCE_TREE_SHA1:
            raise ValueError(
                "source commit tree does not match runtime bundle"
            )
    for entry in entries:
        relative_path = entry["path"]
        path = root / relative_path
        if len(path.read_bytes()) != entry["size_bytes"]:
            raise ValueError(f"runtime bundle size mismatch: {relative_path}")
        if file_sha256(path) != entry["sha256"]:
            raise ValueError(
                f"runtime bundle SHA256 mismatch: {relative_path}"
            )
        local_blob = git_blob_sha1(path)
        if local_blob != entry["source_blob_sha1"]:
            raise ValueError(
                f"runtime bundle Git blob mismatch: {relative_path}"
            )
        if verify_source_commit:
            source_blob = git_revision_value(
                root, f"{SOURCE_COMMIT}:{relative_path}"
            )
            if source_blob != entry["source_blob_sha1"]:
                raise ValueError(
                    "runtime bundle source-commit mismatch: "
                    f"{relative_path}"
                )
    return manifest


def validate_schema_definition(
    schema: dict[str, Any], schema_name: str
) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"{schema_name} schema is invalid: {exc.message}")


def validate_schema_instance(
    instance: dict[str, Any],
    schema: dict[str, Any],
    instance_name: str,
) -> None:
    validator = Draft202012Validator(
        schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda item: [str(part) for part in item.absolute_path],
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path)
        raise ValueError(
            f"{instance_name} schema validation failed at "
            f"{location or '<root>'}: {first.message}"
        )


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
    narrative_entities = {
        item["claim_id"]: item["entity_id"]
        for item in manifest["narrative_claims"]
    }
    claim_records: dict[str, dict[str, Any]] = {}
    for claim_id, edge in edge_by_claim.items():
        claim_records[claim_id] = {
            "entity_ids": {edge["subject"], edge["object"]},
            "evidence": edge["evidence"],
            "qualifiers": edge["qualifiers"],
            "render_text": edge["statement_zh"],
        }
    for claim_id, claim in narrative_by_claim.items():
        claim_records[claim_id] = {
            "entity_ids": {narrative_entities[claim_id]},
            "evidence": claim["evidence"],
            "qualifiers": {},
            "render_text": claim["claim"],
        }
    for claim_id, edge in supporting_narrative_by_claim.items():
        claim_records[claim_id] = {
            "entity_ids": {edge["subject"], edge["object"]},
            "evidence": edge["evidence"],
            "qualifiers": {},
            "render_text": edge["statement_zh"],
        }

    return {
        "manifest": manifest,
        "nodes": nodes,
        "node_ids": node_ids,
        "edges": edges,
        "edge_by_claim": edge_by_claim,
        "narrative_by_claim": narrative_by_claim,
        "supporting_narrative_by_claim": supporting_narrative_by_claim,
        "all_claims": all_claims,
        "claim_records": claim_records,
        "registered_sources": registered_sources,
        "suite": suite,
    }


def render_response_text(
    instance: dict[str, Any],
    root: Path = ROOT,
    context: dict[str, Any] | None = None,
) -> str:
    """Render student-visible text only from validated structured units."""
    authority = context or contract_context(root)
    rendered: list[str] = []
    for unit in instance["answer_units"]:
        if unit["unit_type"] == "MATERIAL_CLAIM":
            claim_id = unit["claim_id"]
            record = authority["claim_records"].get(claim_id)
            if record is None:
                raise ValueError(
                    f"answer unit references unknown claim: {claim_id}"
                )
            rendered.append(record["render_text"])
            qualifier_notice = REQUIRED_QUALIFIER_DISPLAY.get(claim_id)
            if qualifier_notice is not None:
                rendered.append(qualifier_notice)
        else:
            rendered.append(GAP_DISPLAY_TEXT[unit["gap_code"]])
    return "\n".join(rendered)


def validate_response_instance(
    instance: dict[str, Any],
    root: Path = ROOT,
    schema: dict[str, Any] | None = None,
) -> None:
    response_schema = schema or load_yaml(
        root
        / "phase9"
        / "clonorchis-sinensis"
        / "response-schema.yml"
    )
    validate_schema_instance(instance, response_schema, "response")
    context = contract_context(root)

    material_claims = instance["material_claims"]
    material_ids = [item["claim_id"] for item in material_claims]
    if len(set(material_ids)) != len(material_ids):
        raise ValueError("response contains duplicate material claim IDs")
    unknown_claims = set(material_ids) - context["all_claims"]
    if unknown_claims:
        raise ValueError(
            f"response contains unknown claim IDs: {sorted(unknown_claims)}"
        )

    for item in material_claims:
        claim_id = item["claim_id"]
        record = context["claim_records"][claim_id]
        if set(item["entity_ids"]) != record["entity_ids"]:
            raise ValueError(
                f"{claim_id} response entity IDs do not match authority"
            )
        expected_qualifiers = EXPECTED_REQUIRED_QUALIFIERS.get(
            claim_id, {}
        )
        if item["qualifiers"] != expected_qualifiers:
            raise ValueError(
                f"{claim_id} response required qualifiers do not match"
            )

    citations_by_claim: dict[str, list[dict[str, Any]]] = {}
    citation_ids: list[str] = []
    for citation in instance["citations"]:
        citation_ids.append(citation["citation_id"])
        claim_id = citation["claim_id"]
        if claim_id not in material_ids:
            raise ValueError(
                f"citation {citation['citation_id']} does not reference "
                "a material claim"
            )
        citations_by_claim.setdefault(claim_id, []).append(citation)
        source_id = citation["source_id"]
        source = context["registered_sources"].get(source_id)
        if source is None:
            raise ValueError(
                f"citation {citation['citation_id']} uses unregistered source"
            )
        if citation["source_label"] != source["title"]:
            raise ValueError(
                f"citation {citation['citation_id']} source label mismatch"
            )
        allowed_pairs = {
            (item["source_id"], item["locator"])
            for item in context["claim_records"][claim_id]["evidence"]
        }
        if (source_id, citation["locator"]) not in allowed_pairs:
            raise ValueError(
                f"citation {citation['citation_id']} locator does not "
                f"support {claim_id}"
            )

    missing_citations = set(material_ids) - set(citations_by_claim)
    if missing_citations:
        raise ValueError(
            "material claims lack student-visible citations: "
            f"{sorted(missing_citations)}"
        )
    if len(set(citation_ids)) != len(citation_ids):
        raise ValueError("response contains duplicate citation IDs")

    units = instance["answer_units"]
    unit_ids = [unit["unit_id"] for unit in units]
    if len(set(unit_ids)) != len(unit_ids):
        raise ValueError("response contains duplicate answer unit IDs")
    claim_units = [
        unit for unit in units if unit["unit_type"] == "MATERIAL_CLAIM"
    ]
    unit_claim_ids = [unit["claim_id"] for unit in claim_units]
    if Counter(unit_claim_ids) != Counter(material_ids):
        raise ValueError(
            "answer units do not bind every material claim exactly once"
        )
    citations_by_id = {
        citation["citation_id"]: citation for citation in instance["citations"]
    }
    bound_citation_ids: list[str] = []
    for unit in claim_units:
        claim_id = unit["claim_id"]
        for citation_id in unit["citation_ids"]:
            citation = citations_by_id.get(citation_id)
            if citation is None:
                raise ValueError(
                    f"answer unit references unknown citation: {citation_id}"
                )
            if citation["claim_id"] != claim_id:
                raise ValueError(
                    "answer unit citation does not support its bound claim"
                )
            bound_citation_ids.append(citation_id)
    if Counter(bound_citation_ids) != Counter(citation_ids):
        raise ValueError(
            "answer units do not bind every citation exactly once"
        )

    gap_units = [
        unit for unit in units if unit["unit_type"] == "COVERAGE_GAP"
    ]
    unit_gap_codes = [unit["gap_code"] for unit in gap_units]
    declared_gap_codes = [
        item["gap_code"] for item in instance["coverage_gaps"]
    ]
    if Counter(unit_gap_codes) != Counter(declared_gap_codes):
        raise ValueError(
            "answer units do not bind every coverage gap exactly once"
        )
    rendered_text = render_response_text(instance, root, context)
    if instance["answer_text"] != rendered_text:
        raise ValueError(
            "answer text is not the deterministic rendering of answer units"
        )


def validate_audit_instance(
    instance: dict[str, Any],
    root: Path = ROOT,
    schema: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
) -> None:
    audit_schema = schema or load_yaml(
        root
        / "phase9"
        / "clonorchis-sinensis"
        / "audit-log-schema.yml"
    )
    validate_schema_instance(instance, audit_schema, "audit")
    context = contract_context(root)

    retrieval = instance["retrieval"]
    candidate_ids = set(retrieval["candidate_claim_ids"])
    admitted_ids = set(retrieval["admitted_claim_ids"])
    if not admitted_ids.issubset(candidate_ids):
        raise ValueError("audit admitted claims are not candidate claims")
    unknown_admitted = admitted_ids - context["all_claims"]
    if unknown_admitted:
        raise ValueError(
            f"audit admits unknown claim IDs: {sorted(unknown_admitted)}"
        )
    material_ids = set(instance["decision"]["material_claim_ids"])
    if not material_ids.issubset(admitted_ids):
        raise ValueError("audit material claims are not admitted claims")

    disposition = instance["decision"]["disposition"]
    if response is None and (
        disposition in {"ANSWER", "PARTIAL"}
        or instance["response_sha256"] is not None
    ):
        raise ValueError(
            "audit requires the actual response object for binding"
        )
    citation_count = instance["output_validation"][
        "student_visible_citation_count"
    ]
    if disposition in {"ANSWER", "PARTIAL"} and (
        citation_count < len(material_ids)
    ):
        raise ValueError(
            "audit citation count cannot cover every material claim"
        )

    if response is not None:
        validate_response_instance(response, root)
        if instance["response_sha256"] != canonical_sha256(response):
            raise ValueError("audit response hash does not match response")
        if instance["request_id"] != response["request_id"]:
            raise ValueError("audit and response request IDs differ")
        if disposition != response["disposition"]:
            raise ValueError("audit and response dispositions differ")
        if material_ids != {
            item["claim_id"] for item in response["material_claims"]
        }:
            raise ValueError("audit and response material claims differ")
        if citation_count != len(response["citations"]):
            raise ValueError("audit and response citation counts differ")
        if instance["knowledge_authority"][
            "runtime_bundle_sha256"
        ] != response["runtime_bundle_sha256"]:
            raise ValueError("audit and response runtime bundles differ")


def validate_adjudication_record_instance(
    instance: dict[str, Any],
    root: Path = ROOT,
    schema: dict[str, Any] | None = None,
) -> None:
    adjudication_schema = schema or load_yaml(
        root
        / "phase9"
        / "clonorchis-sinensis"
        / "acceptance-cases"
        / "adjudication-record-schema.yml"
    )
    validate_schema_instance(
        instance, adjudication_schema, "adjudication record"
    )


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
    runtime_bundle = verify_runtime_bundle(root)

    if runtime["status"] != "P9A_SECOND_REVISION_PENDING_REREVIEW":
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
    runtime_manifest = authority["runtime_bundle_manifest"]
    if runtime_manifest != {
        "path": (
            "phase9/clonorchis-sinensis/runtime-bundle-manifest.yml"
        ),
        "sha256": RUNTIME_MANIFEST_HASH,
        "bundle_sha256": RUNTIME_BUNDLE_HASH,
        "startup_verification": "REQUIRED_BEFORE_ANY_RETRIEVAL",
    }:
        raise ValueError("runtime bundle manifest trust root changed")
    if runtime_bundle["bundle_sha256"] != RUNTIME_BUNDLE_HASH:
        raise ValueError("runtime bundle verification result changed")
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
    if (
        execution["schema_validation_required_before_semantic_validation"]
        is not True
    ):
        raise ValueError("schema validation must precede semantic validation")
    if (
        execution["semantic_post_validation_required_before_serving"]
        is not True
    ):
        raise ValueError("semantic validation must precede serving")
    if execution["structured_answer_units_required"] is not True:
        raise ValueError("structured answer units must remain mandatory")
    if execution["student_display_text_generation"] != (
        "DETERMINISTIC_FROM_VALIDATED_ANSWER_UNITS"
    ):
        raise ValueError("student display text must be deterministic")
    if execution["free_form_final_answer"] != "PROHIBITED":
        raise ValueError("free-form final answer must remain prohibited")

    disposition = runtime["disposition_policy"]
    if disposition["allowed"] != ["ANSWER", "PARTIAL", "ABSTAIN"]:
        raise ValueError("answer disposition enum changed")
    visible = runtime["student_visible_provenance"]
    if visible["hard_gate"] is not True:
        raise ValueError("student-visible provenance must be a hard gate")
    if visible["backend_trace_is_not_sufficient"] is not True:
        raise ValueError("backend trace cannot substitute for visible sources")
    if set(visible["each_material_answer_unit_must_bind"]) != {
        "claim_id",
        "citation_ids",
    }:
        raise ValueError("material answer-unit bindings changed")
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
    if runtime["determinism"]["stylistic_variation_allowed"] is not False:
        raise ValueError("validated display text cannot vary stylistically")
    if not {"answer_units", "answer_text"}.issubset(
        runtime["determinism"]["same_request_and_authority_must_preserve"]
    ):
        raise ValueError("deterministic response fields are not frozen")

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
        validate_schema_definition(schema, schema_name)
    adjudication_schema = load_yaml(
        root
        / "phase9"
        / "clonorchis-sinensis"
        / "acceptance-cases"
        / "adjudication-record-schema.yml"
    )
    validate_schema_definition(adjudication_schema, "adjudication record")

    response_props = response_schema["properties"]
    if response_props["schema_version"].get("const") != "1.2":
        raise ValueError("response schema version is not frozen")
    if "answer_units" not in response_schema["required"]:
        raise ValueError("response schema does not require answer units")
    if response_props["knowledge_version"].get("const") != (
        "clonorchis_pcms_v1"
    ):
        raise ValueError("response knowledge version is not frozen")
    if response_props["source_commit"].get("const") != SOURCE_COMMIT:
        raise ValueError("response source commit is not frozen")
    if response_props["runtime_bundle_sha256"].get("const") != (
        RUNTIME_BUNDLE_HASH
    ):
        raise ValueError("response runtime bundle hash is not frozen")
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
    if audit_props["schema_version"].get("const") != "1.2":
        raise ValueError("audit schema version is not frozen")
    if audit_props["response_schema_version"].get("const") != "1.2":
        raise ValueError("audit response schema version is not frozen")
    if audit_props["knowledge_authority"]["properties"][
        "source_commit"
    ].get("const") != SOURCE_COMMIT:
        raise ValueError("audit schema source commit is not frozen")
    if audit_props["knowledge_authority"]["properties"][
        "runtime_bundle_sha256"
    ].get("const") != RUNTIME_BUNDLE_HASH:
        raise ValueError("audit runtime bundle hash is not frozen")
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
        if record["completion_detail"] != expected["completion_detail"]:
            raise ValueError(f"{reviewer_id} completion detail changed")
        if record["quantitative_aggregation"] != expected["aggregation"]:
            raise ValueError(f"{reviewer_id} aggregation rule changed")
        if record["top_level_conclusion"] != "PENDING":
            raise ValueError(f"{reviewer_id} conclusion was invented")
        if record["release_recommendation"] != "PENDING":
            raise ValueError(
                f"{reviewer_id} release recommendation was invented"
            )
        if record["metadata_valid"] is not False:
            raise ValueError(f"{reviewer_id} malformed metadata was accepted")
        if record["all_required_case_scores_present"] is not expected[
            "all_scores_present"
        ]:
            raise ValueError(f"{reviewer_id} case-score completeness changed")
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
    if intake["completion_status_enum"] != [
        "COMPLETE",
        "PROVISIONAL",
        "INCOMPLETE",
        "INVALID_FOR_AGGREGATION",
    ]:
        raise ValueError("review completion status enum changed")
    if intake["top_level_conclusion_enum"] != [
        "PASS",
        "CHANGES_REQUIRED",
        "FAIL",
        "PENDING",
    ]:
        raise ValueError("review conclusion enum changed")
    if intake["release_recommendation_enum"] != [
        "RECOMMEND_RELEASE",
        "DO_NOT_RELEASE",
        "PENDING",
    ]:
        raise ValueError("review release recommendation enum changed")
    aggregation_requires = intake["aggregation_requires"]
    if aggregation_requires != {
        "completion_status": "COMPLETE",
        "all_required_case_scores_present": True,
        "top_level_conclusion_allowed": [
            "PASS",
            "CHANGES_REQUIRED",
            "FAIL",
        ],
        "release_recommendation_allowed": [
            "RECOMMEND_RELEASE",
            "DO_NOT_RELEASE",
        ],
        "metadata_valid": True,
        "unresolved_critical_disagreement": False,
    }:
        raise ValueError("review aggregation requirements changed")
    for reviewer_id, record in records.items():
        aggregation_eligible = (
            record["completion_status"]
            == aggregation_requires["completion_status"]
            and record["all_required_case_scores_present"]
            is aggregation_requires["all_required_case_scores_present"]
            and record["top_level_conclusion"]
            in aggregation_requires["top_level_conclusion_allowed"]
            and record["release_recommendation"]
            in aggregation_requires["release_recommendation_allowed"]
            and record["metadata_valid"]
            is aggregation_requires["metadata_valid"]
            and "ALL_REQUIRED_CASE_SCORES_MISSING"
            not in record.get("defects", [])
            and "UNRESOLVED_REQUIRES_ADJUDICATION"
            != record.get("critical_disagreement", {}).get("status")
        )
        if aggregation_eligible:
            raise ValueError(
                f"{reviewer_id} unexpectedly became aggregation eligible"
            )
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
    if plan["source_suite"]["sha256"] != file_sha256(
        root
        / "phase7"
        / "clonorchis-sinensis"
        / "pilot-content-minimum-set-regression.yml"
    ):
        raise ValueError("acceptance source suite content changed")
    if plan["source_suite"]["source_blob_sha1"] != git_revision_value(
        root,
        (
            f"{SOURCE_COMMIT}:phase7/clonorchis-sinensis/"
            "pilot-content-minimum-set-regression.yml"
        ),
    ):
        raise ValueError("acceptance source suite commit blob changed")
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
        if item["source_case_sha256"] != canonical_sha256(source_case):
            raise ValueError(
                f"{item['p9_case_id']} complete source case changed"
            )
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

    adjudication_path = (
        root
        / "phase9"
        / "clonorchis-sinensis"
        / "acceptance-cases"
        / "adjudication-cases.yml"
    )
    adjudication = load_yaml(adjudication_path)
    if plan["adjudication_cases"] != {
        "path": (
            "phase9/clonorchis-sinensis/acceptance-cases/"
            "adjudication-cases.yml"
        ),
        "unresolved_count": 1,
        "release_effect": "BLOCK",
    }:
        raise ValueError("adjudication-case release contract changed")
    if adjudication["status"] != (
        "UNRESOLVED_COURSE_LEAD_ADJUDICATION_REQUIRED"
    ):
        raise ValueError("critical disagreement was silently resolved")
    phase6_path = (
        root / "phase6" / "clonorchis-sinensis" / "test-cases.yml"
    )
    if adjudication["source_suite"]["sha256"] != file_sha256(phase6_path):
        raise ValueError("adjudication source suite content changed")
    if adjudication["source_suite"]["source_blob_sha1"] != git_revision_value(
        root,
        f"{SOURCE_COMMIT}:phase6/clonorchis-sinensis/test-cases.yml",
    ):
        raise ValueError("adjudication source suite commit blob changed")
    phase6_suite = load_yaml(phase6_path)
    phase6_cases = {
        item["case_id"]: item for item in phase6_suite["test_cases"]
    }
    adjudication_cases = adjudication["cases"]
    if len(adjudication_cases) != 1:
        raise ValueError("exactly one critical adjudication case is required")
    adjudication_case = adjudication_cases[0]
    source_case = phase6_cases["CS-RAG-F03"]
    if adjudication_case["source_case_sha256"] != canonical_sha256(
        source_case
    ):
        raise ValueError("CS-RAG-F03 adjudication case content changed")
    if adjudication_case["required_claim_ids"] != [
        "W2-ATOM-022"
    ]:
        raise ValueError("CS-RAG-F03 required claim changed")
    if adjudication_case["disagreement_status"] != (
        "UNRESOLVED_REQUIRES_ADJUDICATION"
    ):
        raise ValueError("CS-RAG-F03 disagreement status changed")
    if adjudication_case["decision_authority"] != "COURSE_LEAD":
        raise ValueError("CS-RAG-F03 decision authority changed")
    if adjudication_case["adjudication_record_status"] != "NOT_CREATED":
        raise ValueError("unapproved adjudication record was introduced")

    fixture_dir = root / "tests" / "fixtures" / "phase9"
    valid_response = load_yaml(
        fixture_dir / "response-answer-valid.yml"
    )
    abstain_response = load_yaml(
        fixture_dir / "response-abstain-valid.yml"
    )
    answer_audit = load_yaml(fixture_dir / "audit-answer-valid.yml")
    unverified_audit = load_yaml(
        fixture_dir / "audit-unverified-valid.yml"
    )
    adjudication_fixtures = [
        load_yaml(fixture_dir / "adjudication-confirm-valid.yml"),
        load_yaml(fixture_dir / "adjudication-exclude-valid.yml"),
        load_yaml(fixture_dir / "adjudication-revise-valid.yml"),
    ]
    validate_response_instance(valid_response, root, response_schema)
    validate_response_instance(abstain_response, root, response_schema)
    validate_audit_instance(
        answer_audit, root, audit_schema, valid_response
    )
    validate_audit_instance(unverified_audit, root, audit_schema)
    for record in adjudication_fixtures:
        validate_adjudication_record_instance(
            record, root, adjudication_schema
        )

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
    except (
        KeyError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
        yaml.YAMLError,
    ) as exc:
        print(f"PHASE9_CONTRACT=FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
