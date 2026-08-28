#!/usr/bin/env python3
"""Build deterministic R3-A reference/override/event-identity evidence."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
REPO = HERE.parents[2]
VALIDATOR_PATH = HERE / "reference-stage-semantic-validator.py"


def cbytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def csha(value: Any) -> str:
    return sha(cbytes(value))


def raw_sha(path: Path) -> str:
    return sha(path.read_bytes())


def load_validator():
    spec = importlib.util.spec_from_file_location("p9b1q_r3a_validator", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def build() -> dict[str, Any]:
    v = load_validator()
    text = "华支睾吸虫病粪便检查检出虫卵，华支睾吸虫病粪便检查未检出虫卵；两次检查是同一诊断事件，生食淡水鱼是另一暴露事件，后次结果覆盖前次结果。"
    request = {
        "knowledge_version": "clonorchis_pcms_v1",
        "locale": "zh-CN",
        "query_text": text,
        "request_id": "P9B1Q-R3A-REFERENCE-OVERRIDE-001",
        "schema_version": "1.0",
    }
    request_sha = csha(request)
    validator_sha = raw_sha(VALIDATOR_PATH)
    contract_sha = raw_sha(HERE / "stage-semantic-validator-contract.yml")
    normalized = {
        "knowledge_version": "clonorchis_pcms_v1",
        "locale": "zh-CN",
        "normalization_operations": ["NONE"],
        "normalized_query_text": text,
        "normalized_request_version": "0.1-candidate",
        "producer": {
            "configuration_sha256": contract_sha,
            "executable_sha256": validator_sha,
            "producer_id": "p9b1q-request-normalizer",
            "producer_version": "0.1-r3a-fixture",
        },
        "raw_query_text": text,
        "raw_to_normalized_spans": [{"normalized_end": len(text), "normalized_start": 0, "raw_end": len(text), "raw_start": 0}],
        "request_id": request["request_id"],
        "request_sha256": request_sha,
    }

    clauses_text = [
        "华支睾吸虫病粪便检查检出虫卵",
        "华支睾吸虫病粪便检查未检出虫卵",
        "两次检查是同一诊断事件",
        "生食淡水鱼是另一暴露事件",
        "后次结果覆盖前次结果",
    ]
    clause_spans: list[dict[str, Any]] = []
    cursor = 0
    for clause in clauses_text:
        start = text.index(clause, cursor)
        end = start + len(clause)
        clause_spans.append({"start_char": start, "end_char": end, "text": clause})
        cursor = end

    occurrences: dict[str, int] = {}
    def span(surface: str) -> dict[str, Any]:
        nth = occurrences.get(surface, 0)
        start = -1
        cursor_local = 0
        for _ in range(nth + 1):
            start = text.index(surface, cursor_local)
            cursor_local = start + len(surface)
        occurrences[surface] = nth + 1
        return {"start_char": start, "end_char": start + len(surface), "text": surface}

    mention_specs = [
        ("U001", "华支睾吸虫病", "disease.clonorchiasis", "disease", "S001"),
        ("U002", "粪便检查", "diagnostic.stool_egg_microscopy", "diagnostic_method", "S001"),
        ("U003", "虫卵", "stage.clonorchis_egg", "life_cycle_stage", "S001"),
        ("U004", "华支睾吸虫病", "disease.clonorchiasis", "disease", "S002"),
        ("U005", "粪便检查", "diagnostic.stool_egg_microscopy", "diagnostic_method", "S002"),
        ("U006", "虫卵", "stage.clonorchis_egg", "life_cycle_stage", "S002"),
        ("U007", "生食淡水鱼", "behavior.raw_undercooked_freshwater_fish_consumption", "behavior", "S004"),
    ]
    mentions = []
    mention_spans: dict[str, dict[str, Any]] = {}
    for identifier, surface, entity, entity_type, node in mention_specs:
        source_span = span(surface)
        mention_spans[identifier] = source_span
        mentions.append({
            "candidate_entity_ids": [entity],
            "candidate_entity_types": [entity_type],
            "candidate_origin": "FORMAL_ALIAS_EXACT",
            "containing_node_id": node,
            "normalized_surface": surface,
            "source_span": source_span,
            "surface_mention_id": identifier,
        })
    ast = {
        "assertion_markers": [],
        "attachment_sets": [],
        "canonicalization_profile_sha256": raw_sha(HERE / "object-canonicalization-and-hash-chain.yml"),
        "clause_ast_version": "0.2-candidate",
        "clause_grammar_config_sha256": raw_sha(HERE / "clause-grammar-config.yml"),
        "entity_ontology_sha256": raw_sha(REPO / "schema/entity-types.yml"),
        "knowledge_version": "clonorchis_pcms_v1",
        "nodes": [
            {"assertion_marker_ids": [], "child_node_ids": ["S010"], "node_id": "S000", "node_kind": "ROOT", "operator_span": None, "parent_node_id": None, "scope_role": "WHOLE_REQUEST", "source_span": {"start_char": 0, "end_char": len(text), "text": text}},
            {"assertion_marker_ids": [], "child_node_ids": [f"S{i:03d}" for i in range(1, 6)], "node_id": "S010", "node_kind": "COORDINATION", "operator_span": {"start_char": clause_spans[0]["end_char"], "end_char": clause_spans[0]["end_char"] + 1, "text": "，"}, "parent_node_id": "S000", "scope_role": "MATERIAL_PROPOSITION", "source_span": {"start_char": 0, "end_char": len(text) - 1, "text": text[:-1]}},
        ] + [
            {"assertion_marker_ids": [], "child_node_ids": [], "node_id": f"S{i:03d}", "node_kind": "PROPOSITION", "operator_span": None, "parent_node_id": "S010", "scope_role": "COORDINATE_MEMBER", "source_span": source_span}
            for i, source_span in enumerate(clause_spans, 1)
        ],
        "normalized_request_sha256": csha(normalized),
        "producer": {"configuration_sha256": raw_sha(HERE / "clause-grammar-config.yml"), "executable_sha256": validator_sha, "producer_id": "p9b1q-clause-ast-compiler", "producer_version": "0.2-r3a-fixture"},
        "request_id": request["request_id"],
        "request_sha256": request_sha,
        "root_node_id": "S000",
        "span_basis": "REQUEST_QUERY_TEXT_UNICODE_CODEPOINT_ZERO_BASED_HALF_OPEN",
        "stage_validator_contract_sha256": contract_sha,
        "surface_mentions": mentions,
    }

    def participant(slot_id: str, role: str, source_id: str, entity: str, entity_type: str) -> dict[str, Any]:
        return {"binding_status": "FIXED", "domain": {"entity_ids": [entity], "entity_types": [entity_type]}, "semantic_role": role, "slot_id": slot_id, "source_ids": [source_id]}

    diagnostic_frames = []
    for index, (node, ids, polarity) in enumerate((("S001", ("U001", "U002", "U003"), "POSITIVE"), ("S002", ("U004", "U005", "U006"), "NEGATIVE")), 1):
        disease_id, method_id, egg_id = ids
        base = (index - 1) * 3
        actor_slot, method_slot, target_slot = (f"V{base + n:03d}" for n in (1, 2, 3))
        specimen_id = f"SP{index:03d}"
        diagnostic_frames.append({
            "assertion": {"assertion_status": "AFFIRMED", "finding_polarity": polarity, "governing_ast_node_ids": [node], "marker_ids": [], "temporal_scope": "GENERAL"},
            "diagnostic_binding": {"method_slot_id": method_slot, "polarity_source_ids": [node], "specimen_slot_id": specimen_id, "target_slot_ids": [target_slot]},
            "event_type_domain": ["DIAGNOSTIC_FINDING"],
            "frame_id": f"EF{index:03d}",
            "frame_status": "FIXED",
            "normalized_identity": {"actor_slot_ids": [actor_slot], "anatomical_site_slot_ids": [], "event_type_domain": ["DIAGNOSTIC_FINDING"], "method_slot_id": method_slot, "specimen_slot_ids": [specimen_id], "target_slot_ids": [target_slot], "temporal_scope_domain": ["GENERAL"]},
            "participant_slots": [
                participant(actor_slot, "ACTOR", disease_id, "disease.clonorchiasis", "disease"),
                participant(method_slot, "METHOD", method_id, "diagnostic.stool_egg_microscopy", "diagnostic_method"),
                participant(target_slot, "TARGET", egg_id, "stage.clonorchis_egg", "life_cycle_stage"),
            ],
            "source_ast_node_ids": [node],
            "source_spans": [copy.deepcopy(clause_spans[index - 1])],
        })
    exposure_frame = {
        "assertion": {"assertion_status": "AFFIRMED", "finding_polarity": "NOT_APPLICABLE", "governing_ast_node_ids": ["S004"], "marker_ids": [], "temporal_scope": "GENERAL"},
        "diagnostic_binding": None,
        "event_type_domain": ["EXPOSURE"],
        "frame_id": "EF003",
        "frame_status": "FIXED",
        "normalized_identity": {"actor_slot_ids": [], "anatomical_site_slot_ids": [], "event_type_domain": ["EXPOSURE"], "method_slot_id": None, "specimen_slot_ids": [], "target_slot_ids": ["V007"], "temporal_scope_domain": ["GENERAL"]},
        "participant_slots": [participant("V007", "TARGET", "U007", "behavior.raw_undercooked_freshwater_fish_consumption", "behavior")],
        "source_ast_node_ids": ["S004"],
        "source_spans": [copy.deepcopy(clause_spans[3])],
    }
    frame = {
        "canonicalization_profile_sha256": ast["canonicalization_profile_sha256"],
        "clause_ast_sha256": csha(ast),
        "entity_ontology_sha256": ast["entity_ontology_sha256"],
        "event_frame_version": "0.2-candidate",
        "event_relation_mapping_sha256": raw_sha(FIX / "authority-event-relation-mapping.json"),
        "frames": diagnostic_frames + [exposure_frame],
        "knowledge_version": "clonorchis_pcms_v1",
        "normalized_request_sha256": csha(normalized),
        "override_hypotheses": [{"earlier_frame_ids": ["EF001"], "identity_constraint": "SAME_NORMALIZED_IDENTITY_EXCLUDING_ASSERTION", "later_frame_ids": ["EF002"], "override_ast_node_id": "S005", "override_hypothesis_id": "OH001", "overridden_dimension_domain": ["FINDING_POLARITY"], "status": "UNIQUE"}],
        "producer": {"configuration_sha256": raw_sha(FIX / "authority-event-relation-mapping.json"), "executable_sha256": validator_sha, "producer_id": "p9b1q-event-frame-compiler", "producer_version": "0.2-r3a-fixture"},
        "reference_hypotheses": [
            {"anaphor_frame_id": "EF002", "anaphor_source_id": "S002", "candidate_referent_ids": ["EF001"], "identity_relation_domain": ["SAME_EVENT"], "reference_hypothesis_id": "RH001", "status": "UNIQUE"},
            {"anaphor_frame_id": "EF003", "anaphor_source_id": "S004", "candidate_referent_ids": ["EF002"], "identity_relation_domain": ["DISTINCT_EVENT"], "reference_hypothesis_id": "RH002", "status": "UNIQUE"},
        ],
        "request_id": request["request_id"],
        "request_sha256": request_sha,
        "specimen_slots": [
            {"binding_status": "FIXED", "source_ids": ["U002"], "source_spans": [{"start_char": mention_spans["U002"]["start_char"], "end_char": mention_spans["U002"]["start_char"] + 2, "text": "粪便"}], "specimen_code_domain": ["STOOL"], "specimen_slot_id": "SP001"},
            {"binding_status": "FIXED", "source_ids": ["U005"], "source_spans": [{"start_char": mention_spans["U005"]["start_char"], "end_char": mention_spans["U005"]["start_char"] + 2, "text": "粪便"}], "specimen_code_domain": ["STOOL"], "specimen_slot_id": "SP002"},
        ],
        "stage_validator_contract_sha256": contract_sha,
    }

    core = {
        "forbidden_relations": [],
        "narrative_intents": [],
        "resolved_events": [
            {"actor_entity_ids": ["disease.clonorchiasis"], "assertion_status": "AFFIRMED", "event_key": "RE001", "event_type": "DIAGNOSTIC_FINDING", "finding_polarity": "POSITIVE", "frame_id": "EF001", "method_entity_id": "diagnostic.stool_egg_microscopy", "specimen_code": "STOOL", "target_entity_ids": ["stage.clonorchis_egg"], "temporal_scope": "GENERAL"},
            {"actor_entity_ids": ["disease.clonorchiasis"], "assertion_status": "AFFIRMED", "event_key": "RE002", "event_type": "DIAGNOSTIC_FINDING", "finding_polarity": "NEGATIVE", "frame_id": "EF002", "method_entity_id": "diagnostic.stool_egg_microscopy", "specimen_code": "STOOL", "target_entity_ids": ["stage.clonorchis_egg"], "temporal_scope": "GENERAL"},
            {"actor_entity_ids": [], "assertion_status": "AFFIRMED", "event_key": "RE003", "event_type": "EXPOSURE", "finding_polarity": "NOT_APPLICABLE", "frame_id": "EF003", "method_entity_id": None, "specimen_code": "NOT_APPLICABLE", "target_entity_ids": ["behavior.raw_undercooked_freshwater_fish_consumption"], "temporal_scope": "GENERAL"},
        ],
        "resolved_mentions": [
            {"assertion_status": "AFFIRMED", "entity_id": entity, "entity_type": entity_type, "mention_key": f"RM{index:03d}", "surface_mention_id": identifier, "temporal_scope": "GENERAL"}
            for index, (identifier, _surface, entity, entity_type, _node) in enumerate(mention_specs, 1)
        ],
        "resolved_overrides": [{"earlier_event_key": "RE001", "hypothesis_id": "OH001", "later_event_key": "RE002", "override_key": "ROV001", "overridden_dimension": "FINDING_POLARITY"}],
        "resolved_references": [
            {"anaphor_key": "RE002", "hypothesis_id": "RH001", "identity_relation": "SAME_EVENT", "reference_key": "RREF001", "referent_key": "RE001"},
            {"anaphor_key": "RE003", "hypothesis_id": "RH002", "identity_relation": "DISTINCT_EVENT", "reference_key": "RREF002", "referent_key": "RE002"},
        ],
        "resolved_relations": [{"activation_policy": "REQUIRED", "derivation_mode": "EVENT_DERIVED", "object_selector": {"entity_ids": ["diagnostic.stool_egg_microscopy"], "entity_types": []}, "predicate": "diagnosed_by", "relation_key": "RR001", "root_keys": ["RE002"], "subject_selector": {"entity_ids": ["disease.clonorchiasis"], "entity_types": []}}],
        "satisfied_constraint_ids": [entry["id"] for entry in v.load_yaml(v.REGISTRY)["entries"] if entry["stage"] in {"S0_NORMALIZED_REQUEST", "S1_CLAUSE_AST", "S2_EVENT_FRAME", "S3_TYPED_SOLVER"}],
        "semantic_object_set_sha256": "0" * 64,
        "semantic_roles": [],
        "solution_id": "SOL-" + "0" * 24,
    }
    v.refresh_core_hashes(core)
    inputs = {
        "NORMALIZED_REQUEST": normalized,
        "CLAUSE_AST": ast,
        "EVENT_FRAME": frame,
        "ENTITY_ONTOLOGY": v.load_yaml(REPO / "schema/entity-types.yml"),
        "PREDICATE_TYPE_MAPPING": v.load_json(FIX / "authority-predicate-type-mapping.json"),
        "EVENT_RELATION_MAPPING": v.load_json(FIX / "authority-event-relation-mapping.json"),
        "PROJECTION_RULE_SET": v.load_yaml(HERE / "queryir-projection-rule-set.yml"),
    }
    query_ir = v.derive_queryir_projection(core, inputs)
    pointers = v.all_json_pointers(query_ir)
    core_hash, ast_hash = csha(core), csha(ast)
    typed_ids = sorted(
        [item[key] for collection, key in (("resolved_mentions", "mention_key"), ("resolved_events", "event_key"), ("resolved_relations", "relation_key"), ("resolved_references", "reference_key"), ("resolved_overrides", "override_key")) for item in core[collection]]
    )
    traces = []
    for index, pointer in enumerate(pointers, 1):
        source_id = typed_ids[0]
        ast_source_id = None
        trace_span = {"start_char": 0, "end_char": len(text), "text": text}
        if pointer.startswith("/clauses/"):
            object_index = int(pointer.split("/")[2])
            ast_source_id = f"S{object_index + 1:03d}"
            trace_span = clause_spans[object_index]
        for prefix, collection, key in (("/mentions/", "resolved_mentions", "mention_key"), ("/events/", "resolved_events", "event_key"), ("/relation_intents/", "resolved_relations", "relation_key"), ("/resolved_references/", "resolved_references", "reference_key"), ("/resolved_overrides/", "resolved_overrides", "override_key")):
            if pointer.startswith(prefix):
                object_index = int(pointer.split("/")[2])
                source_id = core[collection][object_index][key]
                if collection == "resolved_mentions":
                    ast_source_id = core[collection][object_index]["surface_mention_id"]
                    trace_span = mention_spans[ast_source_id]
                elif collection == "resolved_events":
                    ast_source_id = f"S{object_index + 1:03d}" if object_index < 2 else "S004"
                    trace_span = clause_spans[object_index] if object_index < 2 else clause_spans[3]
                elif collection == "resolved_relations":
                    ast_source_id, trace_span = "S002", clause_spans[1]
                elif collection == "resolved_references":
                    ast_source_id = "S002" if object_index == 0 else "S004"
                    trace_span = clause_spans[1] if object_index == 0 else clause_spans[3]
                elif collection == "resolved_overrides":
                    ast_source_id, trace_span = "S005", clause_spans[4]
                break
        bindings = [{"object_kind": "TYPED_SOLUTION", "object_sha256": core_hash, "source_ids": [source_id], "source_spans": [trace_span]}]
        if ast_source_id is not None:
            bindings.append({"object_kind": "CLAUSE_AST", "object_sha256": ast_hash, "source_ids": [ast_source_id], "source_spans": [trace_span]})
        traces.append({"constraint_ids": ["CNS-EMIT-LEAF_TRACE_COVERAGE", "CNS-EMIT-TRACE_VALUE_HASH"], "emitted_value_sha256": csha(v.pointer_get(query_ir, pointer)), "projection_rule_id": "PRJ-EXTRACT_QUERYIR", "query_ir_json_pointer": pointer, "source_bindings": bindings, "trace_id": f"TR{index:04d}"})

    material = sorted(v.material_ids(core))
    material_to_typed = {v._queryir_id(identifier): identifier for identifier in typed_ids}
    nodes = []
    for index, semantic_id in enumerate(material, 1):
        if semantic_id.startswith("REF"):
            kind = "REFERENCE"
        elif semantic_id.startswith("OVR"):
            kind = "OVERRIDE"
        elif semantic_id.startswith("M"):
            kind = "EXPLICIT_RELATION_ROOT"
        elif semantic_id.startswith("E"):
            kind = "AFFIRMED_EVENT_ROOT"
        else:
            kind = "RELATION"
        typed_id = material_to_typed[semantic_id]
        trace_id = next(item["trace_id"] for item in traces if any(typed_id in binding["source_ids"] for binding in item["source_bindings"] if binding["object_kind"] == "TYPED_SOLUTION"))
        nodes.append({"node_id": f"LN{index:04d}", "node_kind": kind, "semantic_object_id": semantic_id, "source_binding_ids": [trace_id]})
    node_for = {item["semantic_object_id"]: item["node_id"] for item in nodes}
    edge_specs = [
        ("E02", "R01", "EVENT_DERIVES_RELATION"),
        ("E02", "REF01", "REFERENCE_BINDS_OBJECT"),
        ("E03", "REF02", "REFERENCE_BINDS_OBJECT"),
        ("E01", "OVR01", "OVERRIDE_BINDS_EVENTS"),
        ("E02", "OVR01", "OVERRIDE_BINDS_EVENTS"),
    ]
    edges = [{"edge_id": f"LE{index:04d}", "from_node_id": node_for[source], "to_node_id": node_for[target], "edge_kind": kind, "constraint_ids": ["CNS-SOLVER-LICENSE_DAG"]} for index, (source, target, kind) in enumerate(edge_specs, 1)]
    dag = {"nodes": nodes, "edges": edges, "topological_order": [item["node_id"] for item in nodes]}
    dag["dag_sha256"] = csha(dag)
    licenses = [{"semantic_object_id": semantic_id, "license_node_id": node_for[semantic_id], "license_kind": next(item["node_kind"] for item in nodes if item["semantic_object_id"] == semantic_id)} for semantic_id in material]

    probes = []
    for collection, index, semantic_id in (("resolved_references", 0, "REF01"), ("resolved_references", 1, "REF02"), ("resolved_overrides", 0, "OVR01")):
        candidate = copy.deepcopy(core)
        candidate[collection].pop(index)
        v.refresh_core_hashes(candidate)
        probes.append({"probe_id": f"R3A-PROBE-{semantic_id}", "removed_semantic_object_id": semantic_id, "operation": [{"op": "remove", "path": f"/{collection}/{index}"}], "candidate_semantic_object_set_sha256": candidate["semantic_object_set_sha256"], "expected_constraint_id": "CNS-SOLVER-EVENT_IDENTITY"})

    canonical_objects = {"normalized_request": normalized, "clause_ast": ast, "event_frame": frame, "typed_solution_core": core, "query_ir": query_ir, "field_traces": traces, "permission_dag": dag, "material_object_licenses": licenses, "minimality_probes": probes, "event_identity_contract": v.load_yaml(EVENT_IDENTITY_CONTRACT := HERE / "event-identity-contract.yml")}
    object_hashes = [{"object_name": name, "canonical_sha256": csha(value), "byte_length": len(cbytes(value))} for name, value in canonical_objects.items()]
    chain = []
    previous = "0" * 64
    for index, item in enumerate(object_hashes, 1):
        link = {"sequence": index, "object_name": item["object_name"], "object_sha256": item["canonical_sha256"], "previous_link_sha256": previous}
        link["link_sha256"] = csha(link)
        previous = link["link_sha256"]
        chain.append(link)
    return {"evidence_version": "R3A-0.1", "request": request, "objects": canonical_objects, "object_hashes": object_hashes, "independent_hash_chain": chain}


def main() -> None:
    payload = build()
    (FIX / "r3a-reference-override-positive.json").write_bytes(cbytes(payload))
    print(json.dumps({"path": "fixtures/r3a-reference-override-positive.json", "sha256": csha(payload), "material_object_count": len(payload["objects"]["material_object_licenses"]), "trace_count": len(payload["objects"]["field_traces"]), "probe_count": len(payload["objects"]["minimality_probes"])}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
