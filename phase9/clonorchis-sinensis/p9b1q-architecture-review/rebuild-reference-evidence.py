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
    write(
        "diagnostic-predicate-argument-binding-positive.json",
        diagnostic_argument_binding,
    )

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
    ) -> dict[str, Any]:
        return copy.deepcopy(base_case) | {
            "fixture_id": fixture_id,
            "fault_class": fault_class,
            "patch": [],
            "actual_input_mutation": {
                "object_kind": object_kind,
                "patch": [{"op": "replace", "path": path, "value": value}],
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
