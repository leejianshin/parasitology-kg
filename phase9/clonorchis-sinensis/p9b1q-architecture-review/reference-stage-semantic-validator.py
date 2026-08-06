#!/usr/bin/env python3
"""Deterministic executable evidence for the P9-B1Q architecture contract.

This is a review-only reference validator.  It does not implement retrieval and
does not modify the frozen 6ac0e4b runtime.  It validates the persisted positive
objects, replays the removal witnesses, and applies every RFC 6902 negative
fixture using the frozen constraint order.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIXTURES = HERE / "fixtures"
CONTRACT = HERE / "stage-semantic-validator-contract.yml"
REGISTRY = HERE / "constraint-id-registry.yml"
NEGATIVE = FIXTURES / "stage-validator-negative-fixtures.yml"
SCHEMA_GATE = HERE / "strict-schema-gate.mjs"
CONSTRAINT_SET = HERE / "constraint-set-v0.1.yml"
PROJECTION_RULE_SET = HERE / "queryir-projection-rule-set.yml"
CONSTRAINT_REGISTRY_SCHEMA = HERE / "constraint-id-registry-schema-candidate.yml"
CONSTRAINT_SET_SCHEMA = HERE / "constraint-set-schema-candidate.yml"
_SCHEMA_VALID_CACHE: dict[tuple[str, str], bool] = {}
_SCHEMA_GATE_CACHE: dict[str, Any] | None = None
_REGISTRY_ORDER_CACHE: dict[str, int] | None = None


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


def error(constraint_id: str, failure_code: str, pointer: str) -> dict[str, str]:
    return {
        "constraint_id": constraint_id,
        "failure_code": failure_code,
        "json_pointer": pointer,
    }


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


def validate_s1(
    ast: dict[str, Any],
    normalized: dict[str, Any],
    alias_authority: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not schema_valid("clause-ast-schema-candidate.yml", ast):
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
    return ordered(errors)


def validate_s2(
    frame: dict[str, Any],
    normalized: dict[str, Any],
    ast: dict[str, Any] | None = None,
    entity_ontology: dict[str, Any] | None = None,
    event_mapping: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not schema_valid("event-frame-schema-candidate.yml", frame):
        errors.append(error("CNS-EF-REF_INTEGRITY", "DANGLING_REFERENCE", "/"))
    ast = ast or {}
    entity_ontology = entity_ontology or load_yaml(REPO / "schema/entity-types.yml")
    event_mapping = event_mapping or load_json(FIXTURES / "authority-event-relation-mapping.json")
    frame_ids = {item["frame_id"] for item in frame["frames"]}
    specimen_ids = {item["specimen_slot_id"] for item in frame["specimen_slots"]}
    slot_ids = {slot["slot_id"] for item in frame["frames"] for slot in item["participant_slots"]}
    reference_ids = {item["reference_hypothesis_id"] for item in frame["reference_hypotheses"]}
    override_ids = {item["override_hypothesis_id"] for item in frame["override_hypotheses"]}
    all_ids = frame_ids | specimen_ids | slot_ids | reference_ids | override_ids
    if len(all_ids) != len(frame_ids) + len(specimen_ids) + len(slot_ids) + len(reference_ids) + len(override_ids):
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
    for index, reference in enumerate(frame["reference_hypotheses"]):
        expected = 1 if reference["status"] == "UNIQUE" else 2
        if len(reference["candidate_referent_ids"]) < expected or len(reference["identity_relation_domain"]) < expected:
            errors.append(error("CNS-EF-REFERENCE_DOMAIN", "REFERENCE_DOMAIN_INVALID", f"/reference_hypotheses/{index}"))
    for index, override in enumerate(frame["override_hypotheses"]):
        expected = 1 if override["status"] == "UNIQUE" else 2 if override["status"] == "UNRESOLVED" else 1
        if len(override["overridden_dimension_domain"]) < expected or set(override["earlier_frame_ids"]) & set(override["later_frame_ids"]):
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
    return ordered(errors)


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


def validate_s3(
    typed: dict[str, Any],
    inputs: dict[str, Any] | None = None,
    input_hashes: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not schema_valid("typed-constraint-result-schema-candidate.yml", typed):
        errors.append(error("CNS-SOLVER-HASH_BINDING", "INPUT_HASH_MISMATCH", "/"))
    inputs = inputs or {}
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
    unknown = set(core["satisfied_constraint_ids"]) - registry
    if unknown:
        errors.append(error("CNS-SOLVER-REGISTRY_MEMBERSHIP", "UNKNOWN_CONSTRAINT_ID", "/selected_solution/satisfied_constraint_ids"))
    if typed["status"] == "UNIQUE" and typed["solution_cardinality"] != "ONE":
        errors.append(error("CNS-SOLVER-SOLUTION_CARDINALITY", "SOLUTION_CARDINALITY_MISMATCH", "/solution_cardinality"))
    empty_unique = typed["status"] == "UNIQUE" and not any(core[key] for key in ("resolved_mentions", "resolved_events", "resolved_relations", "semantic_roles", "narrative_intents"))
    if empty_unique:
        errors.append(error("CNS-SOLVER-NONEMPTY_UNIQUE", "EMPTY_UNIQUE_SOLUTION", "/selected_solution"))
    expected_sequence = [entry["id"] for entry in registry_entries if entry["order"] <= 30]
    if (
        [entry["order"] for entry in registry_entries] != list(range(1, 43))
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
    event_by_key = {item["event_key"]: item for item in core["resolved_events"]}
    relation_by_key = {item["relation_key"]: item for item in core["resolved_relations"]}
    for relation in core["resolved_relations"]:
        if any(root.startswith("RM") and root not in mention_by_key for root in relation["root_keys"]):
            errors.append(error("CNS-SOLVER-ENTITY_RESOLUTION", "INPUT_HASH_MISMATCH", "/selected_solution/resolved_relations"))
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
            errors.append(error("CNS-SOLVER-ENTITY_RESOLUTION", "INPUT_HASH_MISMATCH", "/selected_solution"))
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
        failure = {
            "CNS-SOLVER-ENTITY_RESOLUTION": "INPUT_HASH_MISMATCH",
            "CNS-SOLVER-EVENT_RELATION_DERIVATION": "EVENT_RELATION_DERIVATION_MISMATCH",
            "CNS-SOLVER-LICENSE_DAG": "LICENSE_DAG_INVALID",
        }[constraint]
        errors.append(error(constraint, failure, "/selected_solution"))
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
        or result.get("compiled_schema_count") != 12
        or result.get("fixture_pair_count") != 27
        or result.get("valid_fixture_count") != 27
    ):
        raise RuntimeError("AJV strict schema gate count/result mismatch")
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
            errors.append(error("CNS-SOLVER-ENTITY_RESOLUTION", "INPUT_HASH_MISMATCH", "/selected_solution/resolved_mentions"))
            break
        if any(
            mention[key] != expected[key]
            for key in ("assertion_status", "temporal_scope")
        ):
            errors.append(error("CNS-SOLVER-ASSERTION_SCOPE", "ASSERTION_SCOPE_UNRESOLVED", "/selected_solution/resolved_mentions"))
            break
    if require_complete and set(actual_mentions) != set(expected_mentions):
        errors.append(error("CNS-SOLVER-ENTITY_RESOLUTION", "INPUT_HASH_MISMATCH", "/selected_solution/resolved_mentions"))

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
            errors.append(error("CNS-SOLVER-ASSERTION_SCOPE", "ASSERTION_SCOPE_UNRESOLVED", "/selected_solution/semantic_roles"))
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
            errors.append(error("CNS-SOLVER-ASSERTION_SCOPE", "ASSERTION_SCOPE_UNRESOLVED", "/selected_solution/narrative_intents"))
        relation_key = relation["relation_key"]
        if any(item["root_keys"] != [relation_key] for item in core["semantic_roles"] + core["narrative_intents"]):
            errors.append(error("CNS-SOLVER-LICENSE_DAG", "LICENSE_DAG_INVALID", "/selected_solution"))
    return ordered(errors)


def _queryir_id(identifier: str) -> str:
    prefixes = {"RM": "M", "RE": "E", "RR": "R", "RN": "N", "RQ": "Q"}
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
        assertions = {mention_by_key[root]["assertion_status"] for root in item["root_keys"] if root in mention_by_key}
        temporals = {mention_by_key[root]["temporal_scope"] for root in item["root_keys"] if root in mention_by_key}
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
        "resolved_overrides": copy.deepcopy(core["resolved_overrides"]),
        "resolved_references": copy.deepcopy(core["resolved_references"]),
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
        prefixes = {"RM": "M", "RE": "E", "RR": "R", "RN": "N", "RQ": "Q"}
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


def load_stage_result(stage: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    result = load_json(FIXTURES / f"stage-validation-{stage.lower()}-positive.json")
    body = copy.deepcopy(result)
    declared = body.pop("result_sha256")
    if canonical_sha(body) != declared:
        raise RuntimeError(f"{stage} validation result self hash mismatch")
    if result["validator"]["executable_sha256"] != sha_bytes(Path(__file__).read_bytes()):
        raise RuntimeError(f"{stage} executable binding mismatch")
    if result["validator"]["configuration_sha256"] != sha_bytes(CONTRACT.read_bytes()):
        raise RuntimeError(f"{stage} contract binding mismatch")
    references = result["actual_input_objects"] + [result["actual_output_object"]]
    if not all(validate_actual_reference(reference) for reference in references):
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
    if result["result"] != ("PASS" if not observed else "FAIL_CLOSED") or result["errors"] != observed:
        return [error(expected[0], registry_failure(expected[0]), "/result")]
    if result["verified_constraint_ids"] != expected:
        return [error(expected[0], registry_failure(expected[0]), "/verified_constraint_ids")]
    return observed


def registry_failure(constraint_id: str) -> str:
    for entry in load_yaml(REGISTRY)["entries"]:
        if entry["id"] == constraint_id:
            return entry["failure_code"]
    raise KeyError(constraint_id)


def validate_s5(sidecar: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not schema_valid("execution-binding-sidecar-architecture-schema-candidate.yml", sidecar):
        errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", "/"))
    parsed: dict[str, list[Any]] = {}
    for index, reference in enumerate(sidecar["actual_objects"]):
        path = resolve_review_path(reference["path"])
        if not path.is_file():
            errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", f"/actual_objects/{index}/path"))
            continue
        actual_hash, actual_length = resolved_object_hash(path)
        if actual_hash != reference["canonical_sha256"] or reference.get("byte_length") != actual_length:
            errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", f"/actual_objects/{index}/canonical_sha256"))
        if path.suffix == ".json":
            parsed.setdefault(reference["object_kind"], []).append(load_json(path))
    body = dict(sidecar)
    declared = body.pop("sidecar_sha256")
    if canonical_sha(body) != declared:
        errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", "/sidecar_sha256"))
    index = load_json(FIXTURES / "object-store-index-positive.json")
    sidecar_index = [item for item in index["objects"] if item["object_kind"] == "EXECUTION_BINDING_SIDECAR"]
    if len(sidecar_index) != 1 or sidecar_index[0]["canonical_sha256"] != canonical_sha(sidecar):
        errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", "/sidecar_sha256"))
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
        errors.append(error("CNS-BIND-RESPONSE_AUDIT_CHAIN", "RESPONSE_AUDIT_CHAIN_MISMATCH", "/response_present"))
    return ordered(errors)


def recompute_declared_derived(value: dict[str, Any], paths: list[str]) -> None:
    selected = value.get("selected_solution")
    for name in paths:
        if name.endswith("semantic_solution_core_sha256") and selected is not None:
            selected["queryir_emission_record"]["semantic_solution_core_sha256"] = canonical_sha(solution_core(value))
        elif name.endswith("semantic_object_set_sha256") and selected is not None:
            core = solution_core(value)
            semantic = {key: core[key] for key in ("resolved_mentions", "resolved_events", "resolved_relations", "semantic_roles", "narrative_intents")}
            selected["semantic_object_set_sha256"] = canonical_sha(semantic)
            selected["solution_id"] = f"SOL-{selected['semantic_object_set_sha256'][:24]}"
        elif name.endswith("dag_sha256") and selected is not None:
            dag = selected["queryir_emission_record"]["license_dag"]
            body = dict(dag)
            body.pop("dag_sha256", None)
            dag["dag_sha256"] = canonical_sha(body)
        elif name.endswith("witness_sha256") and selected is not None:
            witness = selected["queryir_emission_record"]["minimality_witness"]
            body = dict(witness)
            body.pop("witness_sha256", None)
            witness["witness_sha256"] = canonical_sha(body)
        elif name.endswith("query_ir_sha256") and selected is not None:
            emission = selected["queryir_emission_record"]
            emission["query_ir_sha256"] = canonical_sha(emission["query_ir"])
        elif name.endswith("field_traces.emitted_value_sha256") and selected is not None:
            emission = selected["queryir_emission_record"]
            for trace in emission["field_traces"]:
                trace["emitted_value_sha256"] = canonical_sha(
                    pointer_get(emission["query_ir"], trace["query_ir_json_pointer"])
                )


def normalized_by_request_id() -> dict[str, dict[str, Any]]:
    result = {}
    for path in FIXTURES.glob("normalized-request-*-positive.json"):
        item = load_json(path)
        result[item["request_id"]] = item
    return result


def run_positive() -> list[dict[str, Any]]:
    schema_gate = run_schema_gate()
    results: list[dict[str, Any]] = []
    normalized = normalized_by_request_id()
    for suffix in ("exposure", "diagnostic"):
        request = load_json(FIXTURES / f"request-{suffix}-positive.json")
        norm = load_json(FIXTURES / f"normalized-request-{suffix}-positive.json")
        ast = load_json(FIXTURES / f"clause-ast-{suffix}-positive.json")
        frame = load_json(FIXTURES / f"event-frame-{suffix}-positive.json")
        s0_errors = validate_s0(norm, request)
        s1_errors = validate_s1(ast, norm)
        s2_errors = validate_s2(frame, norm, ast)
        if suffix == "exposure":
            s0_record, _, _ = load_stage_result("S0")
            s1_record, _, _ = load_stage_result("S1")
            s2_record, _, _ = load_stage_result("S2")
            s0_errors = stage_record_errors(s0_record, s0_errors)
            s1_errors = stage_record_errors(s1_record, s1_errors)
            s2_errors = stage_record_errors(s2_record, s2_errors)
        results.extend([
            {"case": f"POS-S0-{suffix}", "errors": s0_errors},
            {"case": f"POS-S1-{suffix}", "errors": s1_errors},
            {"case": f"POS-S2-{suffix}", "errors": s2_errors},
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
    manifest = load_yaml(NEGATIVE)
    normalized = normalized_by_request_id()
    results = []
    for case in manifest["cases"]:
        base = load_json(resolve_review_path(case["valid_base_object_path"]))
        stage = case["stage"]
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
            base_errors = validate_s2(base, normalized[base["request_id"]], base_ast)
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
            base_errors = validate_s5(base)
        else:
            raise ValueError(stage)
        if base_errors:
            raise RuntimeError(f"negative fixture base failed before mutation: {case['fixture_id']}")

        mutated = apply_patch(base, case["patch"])
        recompute_declared_derived(mutated, case["recompute_derived_hashes"])
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
                mutated, normalized[mutated["request_id"]], paired_ast
            )
        elif stage == "S3_TYPED_SOLVER":
            s3_record, s3_inputs, _ = load_stage_result("S3")
            s3_hashes = {item["object_kind"]: item["canonical_sha256"] for item in s3_record["actual_input_objects"]}
            if case.get("actual_input_mutation"):
                mutation = case["actual_input_mutation"]
                object_kind = mutation["object_kind"]
                s3_inputs = copy.deepcopy(s3_inputs)
                s3_inputs[object_kind] = apply_patch(
                    s3_inputs[object_kind], mutation["patch"]
                )
                s3_hashes[object_kind] = canonical_sha(s3_inputs[object_kind])
            errors = validate_s3(mutated, s3_inputs, s3_hashes)
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
            errors = validate_s5(mutated)
        else:
            raise ValueError(stage)
        first = errors[0] if errors else None
        results.append(
            {
                "fixture_id": case["fixture_id"],
                "observed_first_error": first,
                "passed": first is not None
                and first["constraint_id"] == case["expected_constraint_id"]
                and first["failure_code"] == case["expected_failure_code"],
            }
        )
    return results


def one_run() -> dict[str, Any]:
    positive = run_positive()
    minimality = run_minimality()
    negative = run_negative()
    return {
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
        payload["positive_pass_count"] == len(payload["positive"])
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
    parser.add_argument("--mode", choices=("all", "positive", "minimality", "negative"), default="all")
    args = parser.parse_args()
    if args.mode == "all":
        result: Any = build_summary()
    elif args.mode == "positive":
        result = run_positive()
    elif args.mode == "minimality":
        result = run_minimality()
    else:
        result = run_negative()
    print(canonical_bytes(result).decode("utf-8"), end="")
    if args.mode == "all":
        return 0 if result["result"] == "PASS" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
