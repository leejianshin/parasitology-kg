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
    return {entry["id"]: entry["order"] for entry in load_yaml(REGISTRY)["entries"]}


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


def validate_s1(ast: dict[str, Any], normalized: dict[str, Any]) -> list[dict[str, str]]:
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
        identity = item["normalized_identity"]
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
            local_slots = {slot["slot_id"]: slot for slot in item["participant_slots"]}
            method = local_slots.get(binding["method_slot_id"])
            if method is None or method["semantic_role"] != "METHOD" or any(target not in local_slots for target in binding["target_slot_ids"]):
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


def finite_solution_count(base_core: dict[str, Any], emission: dict[str, Any]) -> int:
    """Enumerate every inclusion subset of the frozen eight-object universe."""
    slots: list[tuple[str, int]] = []
    for collection in (
        "resolved_mentions",
        "resolved_events",
        "resolved_relations",
        "narrative_intents",
        "semantic_roles",
    ):
        slots.extend((collection, index) for index in range(len(base_core[collection])))
    required_ids = {
        item["semantic_object_id"]
        for item in load_json(FIXTURES / "semantic-universe-exposure-positive.json")["semantic_objects"]
    }
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
        mention_keys = {item["mention_key"] for item in candidate["resolved_mentions"]}
        relation_keys = {item["relation_key"] for item in candidate["resolved_relations"]}
        event_keys = {item["event_key"] for item in candidate["resolved_events"]}
        dependencies_valid = not any(
            root.startswith("RM") and root not in mention_keys
            for relation in candidate["resolved_relations"]
            for root in relation["root_keys"]
        ) and bool(relation_keys) == bool(event_keys)
        if material_ids(candidate) == required_ids and dependencies_valid:
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
    registry_entries = registry_object["entries"]
    registry = {entry["id"] for entry in registry_entries}
    constraint_set = inputs.get("CONSTRAINT_SET", load_yaml(CONSTRAINT_SET))
    core = solution_core(typed)
    unknown = set(core["satisfied_constraint_ids"]) - registry
    if unknown:
        errors.append(error("CNS-SOLVER-REGISTRY_MEMBERSHIP", "UNKNOWN_CONSTRAINT_ID", "/selected_solution/satisfied_constraint_ids"))
    if typed["status"] == "UNIQUE" and typed["solution_cardinality"] != "ONE":
        errors.append(error("CNS-SOLVER-SOLUTION_CARDINALITY", "SOLUTION_CARDINALITY_MISMATCH", "/solution_cardinality"))
    if typed["status"] == "UNIQUE" and not any(core[key] for key in ("resolved_mentions", "resolved_events", "resolved_relations", "semantic_roles", "narrative_intents")):
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
    enumerated = finite_solution_count(core, emission)
    if typed["solution_cardinality"] != ("ONE" if enumerated == 1 else "ZERO" if enumerated == 0 else "MULTIPLE"):
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
    return result


def schema_valid(schema_name: str, value: Any) -> bool:
    completed = subprocess.run(
        ["node", str(SCHEMA_GATE), "--validate-schema", schema_name],
        cwd=HERE,
        input=canonical_bytes(value),
        check=False,
        capture_output=True,
    )
    return completed.returncode == 0


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
    results = []
    for path in sorted(FIXTURES.glob("minimality-removal-probe-*.json")):
        probe = load_json(path)
        candidate = apply_patch(core, probe["mutation"])
        refresh_core_hashes(candidate)
        observed = validate_core_minimality(candidate, emission)
        enumerated_after_removal = 1 if not observed else 0
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
        mutated = apply_patch(base, case["patch"])
        recompute_declared_derived(mutated, case["recompute_derived_hashes"])
        stage = case["stage"]
        if stage == "S0_NORMALIZED_REQUEST":
            request = load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
            errors = validate_s0(mutated, request)
        elif stage == "S1_CLAUSE_AST":
            errors = validate_s1(mutated, normalized[mutated["request_id"]])
        elif stage == "S2_EVENT_FRAME":
            errors = validate_s2(mutated, normalized[mutated["request_id"]])
        elif stage == "S3_TYPED_SOLVER":
            s3_record, s3_inputs, _ = load_stage_result("S3")
            s3_hashes = {item["object_kind"]: item["canonical_sha256"] for item in s3_record["actual_input_objects"]}
            errors = validate_s3(mutated, s3_inputs, s3_hashes)
        elif stage == "S4_QUERYIR_EMISSION":
            _, s4_inputs, _ = load_stage_result("S4")
            if "solver_result_version" in mutated:
                query_ir = load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
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
