#!/usr/bin/env python3
"""Build deterministic positive evidence for the R3-B negation authority."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIX = HERE / "fixtures"
VALIDATOR_PATH = HERE / "negation-scope-authority-validator.py"
AUTHORITY_PATH = HERE / "negation-surface-scope-authority.yml"


def cbytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def csha(value: Any) -> str:
    return hashlib.sha256(cbytes(value)).hexdigest()


def raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_validator():
    spec = importlib.util.spec_from_file_location("r3b_validator", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def source_span(text: str, surface: str, occurrence: int = 0) -> dict[str, Any]:
    cursor = 0
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(surface, cursor)
        cursor = start + len(surface)
    return {"start_char": start, "end_char": start + len(surface), "text": surface}


def normalized_request(request: dict[str, Any], validator_sha: str, authority_sha: str) -> dict[str, Any]:
    text = request["query_text"]
    return {
        "knowledge_version": "clonorchis_pcms_v1",
        "locale": "zh-CN",
        "normalization_operations": ["NONE"],
        "normalized_query_text": text,
        "normalized_request_version": "0.1-candidate",
        "producer": {"configuration_sha256": authority_sha, "executable_sha256": validator_sha, "producer_id": "p9b1q-request-normalizer", "producer_version": "0.1-r3b-fixture"},
        "raw_query_text": text,
        "raw_to_normalized_spans": [{"normalized_end": len(text), "normalized_start": 0, "raw_end": len(text), "raw_start": 0}],
        "request_id": request["request_id"],
        "request_sha256": csha(request),
    }


def mention(identifier: str, text: str, surface: str, entity_id: str, entity_type: str, node_id: str, occurrence: int = 0) -> dict[str, Any]:
    return {"candidate_entity_ids": [entity_id], "candidate_entity_types": [entity_type], "candidate_origin": "FORMAL_ALIAS_EXACT", "containing_node_id": node_id, "normalized_surface": surface, "source_span": source_span(text, surface, occurrence), "surface_mention_id": identifier}


def simple_ast(case_id: str, request: dict[str, Any], normalized: dict[str, Any], mentions: list[dict[str, Any]], markers: list[dict[str, Any]], validator_sha: str, authority_sha: str) -> dict[str, Any]:
    text = request["query_text"]
    prop_span = {"start_char": 0, "end_char": len(text) - 1, "text": text[:-1]}
    return {
        "assertion_markers": markers,
        "attachment_sets": [],
        "canonicalization_profile_sha256": raw_sha(HERE / "object-canonicalization-and-hash-chain.yml"),
        "clause_ast_version": "0.2-candidate",
        "clause_grammar_config_sha256": authority_sha,
        "entity_ontology_sha256": raw_sha(REPO / "schema/entity-types.yml"),
        "knowledge_version": "clonorchis_pcms_v1",
        "nodes": [
            {"assertion_marker_ids": [], "child_node_ids": ["S001"], "node_id": "S000", "node_kind": "ROOT", "operator_span": None, "parent_node_id": None, "scope_role": "WHOLE_REQUEST", "source_span": {"start_char": 0, "end_char": len(text), "text": text}},
            {"assertion_marker_ids": [item["marker_id"] for item in markers], "child_node_ids": [], "node_id": "S001", "node_kind": "PROPOSITION", "operator_span": None, "parent_node_id": "S000", "scope_role": "MATERIAL_PROPOSITION", "source_span": prop_span},
        ],
        "normalized_request_sha256": csha(normalized),
        "producer": {"configuration_sha256": authority_sha, "executable_sha256": validator_sha, "producer_id": "p9b1q-clause-ast-compiler", "producer_version": "0.2-r3b-fixture"},
        "request_id": request["request_id"],
        "request_sha256": csha(request),
        "root_node_id": "S000",
        "span_basis": "REQUEST_QUERY_TEXT_UNICODE_CODEPOINT_ZERO_BASED_HALF_OPEN",
        "stage_validator_contract_sha256": authority_sha,
        "surface_mentions": mentions,
    }


def wh_ast(request: dict[str, Any], normalized: dict[str, Any], mentions: list[dict[str, Any]], marker: dict[str, Any], validator_sha: str, authority_sha: str) -> dict[str, Any]:
    text = request["query_text"]
    first = "生食淡水鱼可作为什么证据"
    second = "粪便检查检出虫卵"
    comma = text.index("，")
    second_start = comma + 1
    return {
        "assertion_markers": [marker], "attachment_sets": [],
        "canonicalization_profile_sha256": raw_sha(HERE / "object-canonicalization-and-hash-chain.yml"),
        "clause_ast_version": "0.2-candidate", "clause_grammar_config_sha256": authority_sha,
        "entity_ontology_sha256": raw_sha(REPO / "schema/entity-types.yml"), "knowledge_version": "clonorchis_pcms_v1",
        "nodes": [
            {"assertion_marker_ids": [], "child_node_ids": ["S001"], "node_id": "S000", "node_kind": "ROOT", "operator_span": None, "parent_node_id": None, "scope_role": "WHOLE_REQUEST", "source_span": {"start_char": 0, "end_char": len(text), "text": text}},
            {"assertion_marker_ids": ["K001"], "child_node_ids": ["S010"], "node_id": "S001", "node_kind": "QUESTION", "operator_span": marker["source_span"], "parent_node_id": "S000", "scope_role": "QUESTION_FOCUS", "source_span": {"start_char": 0, "end_char": len(text), "text": text}},
            {"assertion_marker_ids": [], "child_node_ids": ["S002", "S003"], "node_id": "S010", "node_kind": "COORDINATION", "operator_span": {"start_char": comma, "end_char": comma + 1, "text": "，"}, "parent_node_id": "S001", "scope_role": "MATERIAL_PROPOSITION", "source_span": {"start_char": 0, "end_char": len(text) - 1, "text": text[:-1]}},
            {"assertion_marker_ids": [], "child_node_ids": [], "node_id": "S002", "node_kind": "PROPOSITION", "operator_span": None, "parent_node_id": "S010", "scope_role": "COORDINATE_MEMBER", "source_span": {"start_char": 0, "end_char": len(first), "text": first}},
            {"assertion_marker_ids": [], "child_node_ids": [], "node_id": "S003", "node_kind": "PROPOSITION", "operator_span": None, "parent_node_id": "S010", "scope_role": "COORDINATE_MEMBER", "source_span": {"start_char": second_start, "end_char": second_start + len(second), "text": second}},
        ],
        "normalized_request_sha256": csha(normalized),
        "producer": {"configuration_sha256": authority_sha, "executable_sha256": validator_sha, "producer_id": "p9b1q-clause-ast-compiler", "producer_version": "0.2-r3b-fixture"},
        "request_id": request["request_id"], "request_sha256": csha(request), "root_node_id": "S000",
        "span_basis": "REQUEST_QUERY_TEXT_UNICODE_CODEPOINT_ZERO_BASED_HALF_OPEN", "stage_validator_contract_sha256": authority_sha,
        "surface_mentions": mentions,
    }


def exposure_frame(request: dict[str, Any], normalized: dict[str, Any], ast: dict[str, Any], source_node: str, mention_id: str, assertion: str, validator_sha: str, authority_sha: str) -> dict[str, Any]:
    mention_object = next(item for item in ast["surface_mentions"] if item["surface_mention_id"] == mention_id)
    node = next(item for item in ast["nodes"] if item["node_id"] == source_node)
    return {
        "canonicalization_profile_sha256": ast["canonicalization_profile_sha256"], "clause_ast_sha256": csha(ast), "entity_ontology_sha256": ast["entity_ontology_sha256"],
        "event_frame_version": "0.2-candidate", "event_relation_mapping_sha256": raw_sha(FIX / "authority-event-relation-mapping.json"),
        "frames": [{"assertion": {"assertion_status": assertion, "finding_polarity": "NOT_APPLICABLE", "governing_ast_node_ids": [source_node], "marker_ids": [item["marker_id"] for item in ast["assertion_markers"] if source_node in item["scope_target_candidate_ids"]], "temporal_scope": "GENERAL"}, "diagnostic_binding": None, "event_type_domain": ["EXPOSURE"], "frame_id": "EF001", "frame_status": "FIXED", "normalized_identity": {"actor_slot_ids": [], "anatomical_site_slot_ids": [], "event_type_domain": ["EXPOSURE"], "method_slot_id": None, "specimen_slot_ids": [], "target_slot_ids": ["V001"], "temporal_scope_domain": ["GENERAL"]}, "participant_slots": [{"binding_status": "FIXED", "domain": {"entity_ids": [mention_object["candidate_entity_ids"][0]], "entity_types": [mention_object["candidate_entity_types"][0]]}, "semantic_role": "TARGET", "slot_id": "V001", "source_ids": [mention_id]}], "source_ast_node_ids": [source_node], "source_spans": [node["source_span"]]}],
        "knowledge_version": "clonorchis_pcms_v1", "normalized_request_sha256": csha(normalized), "override_hypotheses": [],
        "producer": {"configuration_sha256": authority_sha, "executable_sha256": validator_sha, "producer_id": "p9b1q-event-frame-compiler", "producer_version": "0.2-r3b-fixture"},
        "reference_hypotheses": [], "request_id": request["request_id"], "request_sha256": csha(request), "specimen_slots": [], "stage_validator_contract_sha256": authority_sha,
    }


def diagnostic_frame(request: dict[str, Any], normalized: dict[str, Any], ast: dict[str, Any], validator_sha: str, authority_sha: str) -> dict[str, Any]:
    text = request["query_text"]
    node = next(item for item in ast["nodes"] if item["node_id"] == "S001")
    stool = source_span(text, "粪便")
    return {
        "canonicalization_profile_sha256": ast["canonicalization_profile_sha256"], "clause_ast_sha256": csha(ast), "entity_ontology_sha256": ast["entity_ontology_sha256"], "event_frame_version": "0.2-candidate", "event_relation_mapping_sha256": raw_sha(FIX / "authority-event-relation-mapping.json"),
        "frames": [{"assertion": {"assertion_status": "AFFIRMED", "finding_polarity": "NEGATIVE", "governing_ast_node_ids": ["S001"], "marker_ids": [], "temporal_scope": "GENERAL"}, "diagnostic_binding": {"method_slot_id": "V001", "polarity_source_ids": ["K001"], "specimen_slot_id": "SP001", "target_slot_ids": ["V002"]}, "event_type_domain": ["DIAGNOSTIC_FINDING"], "frame_id": "EF001", "frame_status": "FIXED", "normalized_identity": {"actor_slot_ids": [], "anatomical_site_slot_ids": [], "event_type_domain": ["DIAGNOSTIC_FINDING"], "method_slot_id": "V001", "specimen_slot_ids": ["SP001"], "target_slot_ids": ["V002"], "temporal_scope_domain": ["GENERAL"]}, "participant_slots": [{"binding_status": "FIXED", "domain": {"entity_ids": ["diagnostic.stool_egg_microscopy"], "entity_types": ["diagnostic_method"]}, "semantic_role": "METHOD", "slot_id": "V001", "source_ids": ["U001"]}, {"binding_status": "FIXED", "domain": {"entity_ids": ["stage.clonorchis_egg"], "entity_types": ["life_cycle_stage"]}, "semantic_role": "TARGET", "slot_id": "V002", "source_ids": ["U002"]}], "source_ast_node_ids": ["S001"], "source_spans": [node["source_span"]]}],
        "knowledge_version": "clonorchis_pcms_v1", "normalized_request_sha256": csha(normalized), "override_hypotheses": [], "producer": {"configuration_sha256": authority_sha, "executable_sha256": validator_sha, "producer_id": "p9b1q-event-frame-compiler", "producer_version": "0.2-r3b-fixture"}, "reference_hypotheses": [], "request_id": request["request_id"], "request_sha256": csha(request),
        "specimen_slots": [{"binding_status": "FIXED", "source_ids": ["U001"], "source_spans": [stool], "specimen_code_domain": ["STOOL"], "specimen_slot_id": "SP001"}], "stage_validator_contract_sha256": authority_sha,
    }


def build() -> dict[str, Any]:
    v = load_validator()
    validator_sha, authority_sha = raw_sha(VALIDATOR_PATH), raw_sha(AUTHORITY_PATH)
    cases: list[dict[str, Any]] = []

    request = {"knowledge_version": "clonorchis_pcms_v1", "locale": "zh-CN", "query_text": "未生食淡水鱼。", "request_id": "P9B1Q-R3B-EVENT-NEGATION-001", "schema_version": "1.0"}
    norm = normalized_request(request, validator_sha, authority_sha)
    mentions = [mention("U001", request["query_text"], "生食淡水鱼", "behavior.raw_undercooked_freshwater_fish_consumption", "behavior", "S001")]
    markers = [{"containing_node_id": "S001", "marker_id": "K001", "marker_kind": "NEGATOR", "scope_status": "UNIQUE", "scope_target_candidate_ids": ["S001"], "source_span": source_span(request["query_text"], "未")}]
    ast = simple_ast("event", request, norm, mentions, markers, validator_sha, authority_sha)
    frame = exposure_frame(request, norm, ast, "S001", "U001", "NEGATED", validator_sha, authority_sha)
    cases.append({"case_id": "R3B-POS-EVENT-NEGATION", "request": request, "normalized_request": norm, "clause_ast": ast, "event_frame": frame, "scope_authority_records": [{"grammar_class": "EVENT_PREDICATE_NEGATOR", "marker_id": "K001", "path_node_ids": ["S001"], "path_relation": "SELF_PROPOSITION", "target_semantic_type": "EVENT_PROPOSITION"}]})

    request = {"knowledge_version": "clonorchis_pcms_v1", "locale": "zh-CN", "query_text": "粪便检查未检出虫卵。", "request_id": "P9B1Q-R3B-OBJECT-NEGATION-001", "schema_version": "1.0"}
    norm = normalized_request(request, validator_sha, authority_sha)
    mentions = [mention("U001", request["query_text"], "粪便检查", "diagnostic.stool_egg_microscopy", "diagnostic_method", "S001"), mention("U002", request["query_text"], "虫卵", "stage.clonorchis_egg", "life_cycle_stage", "S001")]
    markers = [{"containing_node_id": "S001", "marker_id": "K001", "marker_kind": "NEGATOR", "scope_status": "UNIQUE", "scope_target_candidate_ids": ["U002"], "source_span": source_span(request["query_text"], "未检出")}]
    ast = simple_ast("object", request, norm, mentions, markers, validator_sha, authority_sha)
    frame = diagnostic_frame(request, norm, ast, validator_sha, authority_sha)
    cases.append({"case_id": "R3B-POS-OBJECT-NEGATION", "request": request, "normalized_request": norm, "clause_ast": ast, "event_frame": frame, "scope_authority_records": [{"grammar_class": "PARTICIPANT_ABSENCE_NEGATOR", "marker_id": "K001", "path_node_ids": ["S001", "U002"], "path_relation": "DESCENDANT_MENTION", "target_semantic_type": "PARTICIPANT_MENTION"}]})

    request = {"knowledge_version": "clonorchis_pcms_v1", "locale": "zh-CN", "query_text": "并非未生食淡水鱼。", "request_id": "P9B1Q-R3B-DOUBLE-NEGATION-001", "schema_version": "1.0"}
    norm = normalized_request(request, validator_sha, authority_sha)
    mentions = [mention("U001", request["query_text"], "生食淡水鱼", "behavior.raw_undercooked_freshwater_fish_consumption", "behavior", "S001")]
    markers = [{"containing_node_id": "S001", "marker_id": "K001", "marker_kind": "NEGATOR", "scope_status": "UNIQUE", "scope_target_candidate_ids": ["S001"], "source_span": source_span(request["query_text"], "并非")}, {"containing_node_id": "S001", "marker_id": "K002", "marker_kind": "NEGATOR", "scope_status": "UNIQUE", "scope_target_candidate_ids": ["S001"], "source_span": source_span(request["query_text"], "未")}]
    ast = simple_ast("double", request, norm, mentions, markers, validator_sha, authority_sha)
    frame = exposure_frame(request, norm, ast, "S001", "U001", "AFFIRMED", validator_sha, authority_sha)
    cases.append({"case_id": "R3B-POS-DOUBLE-NEGATION", "request": request, "normalized_request": norm, "clause_ast": ast, "event_frame": frame, "scope_authority_records": [{"grammar_class": "SENTENTIAL_NEGATOR", "marker_id": "K001", "path_node_ids": ["S001"], "path_relation": "SELF_PROPOSITION", "target_semantic_type": "EVENT_PROPOSITION"}, {"grammar_class": "EVENT_PREDICATE_NEGATOR", "marker_id": "K002", "path_node_ids": ["S001"], "path_relation": "SELF_PROPOSITION", "target_semantic_type": "EVENT_PROPOSITION"}]})

    request = {"knowledge_version": "clonorchis_pcms_v1", "locale": "zh-CN", "query_text": "生食淡水鱼可作为什么证据，粪便检查检出虫卵？", "request_id": "P9B1Q-R3B-WH-CONTROL-001", "schema_version": "1.0"}
    norm = normalized_request(request, validator_sha, authority_sha)
    mentions = [mention("U001", request["query_text"], "生食淡水鱼", "behavior.raw_undercooked_freshwater_fish_consumption", "behavior", "S002"), mention("U002", request["query_text"], "粪便检查", "diagnostic.stool_egg_microscopy", "diagnostic_method", "S003"), mention("U003", request["query_text"], "虫卵", "stage.clonorchis_egg", "life_cycle_stage", "S003")]
    marker = {"containing_node_id": "S001", "marker_id": "K001", "marker_kind": "WH_FOCUS", "scope_status": "UNIQUE", "scope_target_candidate_ids": ["S002"], "source_span": source_span(request["query_text"], "什么证据")}
    ast = wh_ast(request, norm, mentions, marker, validator_sha, authority_sha)
    frame = exposure_frame(request, norm, ast, "S002", "U001", "AFFIRMED", validator_sha, authority_sha)
    cases.append({"case_id": "R3B-POS-WH-CONTROL", "request": request, "normalized_request": norm, "clause_ast": ast, "event_frame": frame, "scope_authority_records": [{"grammar_class": "WH_INTERROGATIVE_FOCUS", "marker_id": "K001", "path_node_ids": ["S001", "S010", "S002"], "path_relation": "QUESTION_FOCUS_TO_SOURCE_PROPOSITION", "target_semantic_type": "EVENT_PROPOSITION"}]})

    for case in cases:
        case["assertion_derivation"] = v.independently_derive_assertion(case)

    objects: list[tuple[str, Any]] = [("authority", yaml.safe_load(AUTHORITY_PATH.read_text(encoding="utf-8")))]
    for case in cases:
        for key in ("request", "normalized_request", "clause_ast", "event_frame", "scope_authority_records", "assertion_derivation"):
            objects.append((f"{case['case_id']}.{key}", case[key]))
    object_hashes = [{"object_name": name, "canonical_sha256": csha(value), "byte_length": len(cbytes(value))} for name, value in objects]
    chain = []
    previous = "0" * 64
    for index, item in enumerate(object_hashes, 1):
        link = {"sequence": index, "object_name": item["object_name"], "object_sha256": item["canonical_sha256"], "previous_link_sha256": previous}
        link["link_sha256"] = csha(link)
        previous = link["link_sha256"]
        chain.append(link)
    return {"evidence_version": "R3B-0.1", "authority_sha256": authority_sha, "validator_sha256": validator_sha, "cases": cases, "object_hashes": object_hashes, "independent_hash_chain": chain}


def main() -> None:
    payload = build()
    path = FIX / "r3b-negation-scope-positive.json"
    path.write_bytes(cbytes(payload))
    print(json.dumps({"path": "fixtures/r3b-negation-scope-positive.json", "sha256": csha(payload), "positive_case_count": len(payload["cases"]), "canonical_object_count": len(payload["object_hashes"])}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
