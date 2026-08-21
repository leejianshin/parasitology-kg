#!/usr/bin/env python3
"""Shared deterministic negation surface, scope, target, and assertion semantics.

This module is the semantic authority consumed by both the standalone R3-B
validator and the authoritative S1/S3 reference pipeline.  It performs no file
I/O and trusts neither declared marker kinds, declared scope records, nor Event
Frame assertions as derivation inputs.
"""

from __future__ import annotations

from typing import Any


def error(constraint_id: str, failure_code: str, pointer: str) -> dict[str, str]:
    return {
        "constraint_id": constraint_id,
        "failure_code": failure_code,
        "json_pointer": pointer,
    }


def ordered(
    errors: list[dict[str, str]], authority: dict[str, Any]
) -> list[dict[str, str]]:
    order = {
        value: index for index, value in enumerate(authority["constraint_order"])
    }
    return sorted(
        errors,
        key=lambda item: (order[item["constraint_id"]], item["json_pointer"]),
    )


def _node_path(
    nodes: dict[str, dict[str, Any]], start: str, target: str
) -> list[str] | None:
    pending: list[tuple[str, list[str]]] = [(start, [start])]
    visited: set[str] = set()
    while pending:
        node_id, path = pending.pop(0)
        if node_id in visited or node_id not in nodes:
            continue
        visited.add(node_id)
        if node_id == target:
            return path
        pending.extend(
            (child, path + [child]) for child in nodes[node_id]["child_node_ids"]
        )
    return None


def _source_proposition(
    ast: dict[str, Any], marker: dict[str, Any]
) -> str | None:
    span = marker["source_span"]
    candidates = [
        node
        for node in ast["nodes"]
        if node["node_kind"] == "PROPOSITION"
        and node["source_span"]["start_char"] <= span["start_char"]
        and span["end_char"] <= node["source_span"]["end_char"]
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda node: node["source_span"]["end_char"]
        - node["source_span"]["start_char"],
    )["node_id"]


def _target_type(ast: dict[str, Any], target_id: str) -> str | None:
    nodes = {item["node_id"]: item for item in ast["nodes"]}
    mentions = {
        item["surface_mention_id"]: item for item in ast["surface_mentions"]
    }
    if target_id in nodes and nodes[target_id]["node_kind"] == "PROPOSITION":
        return "EVENT_PROPOSITION"
    if target_id in mentions:
        return "PARTICIPANT_MENTION"
    return None


def derive_scope_record(
    ast: dict[str, Any], marker: dict[str, Any], authority: dict[str, Any]
) -> dict[str, Any] | None:
    """Derive a marker's only licensed scope record from actual AST edges."""
    nodes = {item["node_id"]: item for item in ast["nodes"]}
    mentions = {
        item["surface_mention_id"]: item for item in ast["surface_mentions"]
    }
    containing = marker["containing_node_id"]
    if containing not in nodes or len(marker["scope_target_candidate_ids"]) != 1:
        return None
    target = marker["scope_target_candidate_ids"][0]
    source_node = _source_proposition(ast, marker)
    if target in nodes:
        path = _node_path(nodes, containing, target)
        if path is None:
            return None
        if target == containing and nodes[target]["node_kind"] == "PROPOSITION":
            relation = "SELF_PROPOSITION"
        elif source_node == target and nodes[containing]["node_kind"] == "QUESTION":
            relation = "QUESTION_FOCUS_TO_SOURCE_PROPOSITION"
        else:
            return None
    elif target in mentions:
        mention_node = mentions[target]["containing_node_id"]
        path = _node_path(nodes, containing, mention_node)
        if path is None:
            return None
        path = path + [target]
        relation = "DESCENDANT_MENTION"
    else:
        return None
    classification = authority["source_classification"].get(
        marker["source_span"]["text"]
    )
    return {
        "grammar_class": classification["grammar_class"]
        if classification is not None
        else None,
        "marker_id": marker["marker_id"],
        "path_node_ids": path,
        "path_relation": relation,
        "target_semantic_type": _target_type(ast, target),
    }


def governed_markers(
    ast: dict[str, Any], authority: dict[str, Any]
) -> list[dict[str, Any]]:
    governed_kinds = {
        item["marker_kind"] for item in authority["source_classification"].values()
    }
    governed_surfaces = set(authority["source_classification"])
    return [
        marker
        for marker in ast["assertion_markers"]
        if marker["marker_kind"] in governed_kinds
        or marker["source_span"]["text"] in governed_surfaces
    ]


def derive_scope_records(
    ast: dict[str, Any], authority: dict[str, Any]
) -> list[dict[str, Any]]:
    records = []
    for marker in governed_markers(ast, authority):
        record = derive_scope_record(ast, marker, authority)
        if record is not None:
            records.append(record)
    return records


def validate_surface_scope_target(
    ast: dict[str, Any],
    normalized: dict[str, Any],
    authority: dict[str, Any],
    declared_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Validate surface classification, AST scope path, and target type."""
    text = normalized["normalized_query_text"]
    nodes = {item["node_id"]: item for item in ast["nodes"]}
    records = (
        {item["marker_id"]: item for item in declared_records}
        if declared_records is not None
        else None
    )
    markers = governed_markers(ast, authority)
    errors: list[dict[str, str]] = []
    for marker in markers:
        index = ast["assertion_markers"].index(marker)
        pointer = f"/assertion_markers/{index}"
        span = marker["source_span"]
        surface = span["text"]
        classification = authority["source_classification"].get(surface)
        exact_span = (
            0 <= span["start_char"] < span["end_char"] <= len(text)
            and text[span["start_char"] : span["end_char"]] == surface
        )
        if (
            classification is None
            or not exact_span
            or classification["marker_kind"] != marker["marker_kind"]
        ):
            errors.append(
                error(
                    "CNS-AST-MARKER-SURFACE-AUTHORITY",
                    "MARKER_SURFACE_UNLICENSED",
                    pointer,
                )
            )
            continue
        containing = nodes.get(marker["containing_node_id"])
        member = (
            containing is not None
            and marker["marker_id"] in containing["assertion_marker_ids"]
        )
        inside = (
            containing is not None
            and containing["source_span"]["start_char"] <= span["start_char"]
            and span["end_char"] <= containing["source_span"]["end_char"]
        )
        derived = derive_scope_record(ast, marker, authority)
        declared = records.get(marker["marker_id"]) if records is not None else derived
        if not member or not inside or derived is None or declared is None:
            errors.append(
                error(
                    "CNS-AST-SCOPE-PATH-AUTHORITY",
                    "SCOPE_PATH_INVALID",
                    pointer,
                )
            )
            continue
        if declared["grammar_class"] != classification["grammar_class"]:
            errors.append(
                error(
                    "CNS-AST-MARKER-SURFACE-AUTHORITY",
                    "MARKER_SURFACE_UNLICENSED",
                    pointer,
                )
            )
            continue
        grammar = authority["grammar_classes"][classification["grammar_class"]]
        if (
            derived["target_semantic_type"]
            not in grammar["allowable_target_types"]
            or declared["target_semantic_type"]
            != derived["target_semantic_type"]
        ):
            errors.append(
                error(
                    "CNS-AST-TARGET-TYPE-AUTHORITY",
                    "TARGET_TYPE_INVALID",
                    pointer,
                )
            )
            continue
        if (
            derived["path_relation"] not in grammar["allowable_path_relations"]
            or declared["path_relation"] != derived["path_relation"]
            or declared["path_node_ids"] != derived["path_node_ids"]
        ):
            errors.append(
                error(
                    "CNS-AST-SCOPE-PATH-AUTHORITY",
                    "SCOPE_PATH_INVALID",
                    pointer,
                )
            )
    if records is not None and set(records) != {
        item["marker_id"] for item in markers
    }:
        errors.append(
            error(
                "CNS-AST-SCOPE-PATH-AUTHORITY",
                "SCOPE_PATH_INVALID",
                "/scope_authority_records",
            )
        )
    return ordered(errors, authority)


def validate_target_binding(
    ast: dict[str, Any],
    frame: dict[str, Any],
    authority: dict[str, Any],
    declared_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    records = declared_records or derive_scope_records(ast, authority)
    markers = {item["marker_id"]: item for item in ast["assertion_markers"]}
    errors: list[dict[str, str]] = []
    for index, record in enumerate(records):
        marker = markers.get(record["marker_id"])
        if marker is None or len(marker["scope_target_candidate_ids"]) != 1:
            errors.append(
                error(
                    "CNS-AST-SCOPE-PATH-AUTHORITY",
                    "SCOPE_PATH_INVALID",
                    f"/scope_authority_records/{index}",
                )
            )
            continue
        target = marker["scope_target_candidate_ids"][0]
        if record["target_semantic_type"] == "EVENT_PROPOSITION":
            bound = sum(
                target in event["source_ast_node_ids"] for event in frame["frames"]
            )
        else:
            bound = sum(
                target in slot["source_ids"]
                for event in frame["frames"]
                for slot in event["participant_slots"]
            )
        if bound != 1:
            errors.append(
                error(
                    "CNS-AST-TARGET-TYPE-AUTHORITY",
                    "TARGET_TYPE_INVALID",
                    f"/scope_authority_records/{index}",
                )
            )
    return ordered(errors, authority)


def derive_assertion(
    ast: dict[str, Any],
    frame: dict[str, Any],
    authority: dict[str, Any],
    declared_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Derive assertion only from validated source, AST, scope, and target data."""
    records = {
        item["marker_id"]: item
        for item in (
            declared_records
            if declared_records is not None
            else derive_scope_records(ast, authority)
        )
    }
    markers = sorted(
        governed_markers(ast, authority),
        key=lambda item: (
            item["source_span"]["start_char"],
            item["source_span"]["end_char"],
            item["marker_id"],
        ),
    )
    event_sources = {
        source for event in frame["frames"] for source in event["source_ast_node_ids"]
    }
    event_negators: list[str] = []
    participant_counts: dict[str, int] = {}
    for marker in markers:
        record = records.get(marker["marker_id"])
        if record is None:
            continue
        classification = authority["source_classification"].get(
            marker["source_span"]["text"], {}
        )
        target = marker["scope_target_candidate_ids"][0]
        if (
            classification.get("semantic_effect") == "EVENT_NEGATION"
            and record["target_semantic_type"] == "EVENT_PROPOSITION"
            and target in event_sources
        ):
            event_negators.append(marker["marker_id"])
        elif (
            classification.get("semantic_effect") == "PARTICIPANT_NEGATION"
            and record["target_semantic_type"] == "PARTICIPANT_MENTION"
        ):
            participant_counts[target] = participant_counts.get(target, 0) + 1
    event_assertion = "NEGATED" if len(event_negators) % 2 else "AFFIRMED"
    participant_assertions = {
        target: "NEGATED" if count % 2 else "AFFIRMED"
        for target, count in sorted(participant_counts.items())
    }
    event_type = frame["frames"][0]["event_type_domain"][0]
    finding = (
        "NEGATIVE"
        if participant_assertions
        and all(value == "NEGATED" for value in participant_assertions.values())
        else "POSITIVE"
        if event_type == "DIAGNOSTIC_FINDING"
        else "NOT_APPLICABLE"
    )
    return {
        "ordered_marker_ids": [item["marker_id"] for item in markers],
        "event_negator_count": len(event_negators),
        "derived_event_assertion": event_assertion,
        "participant_assertions": participant_assertions,
        "derived_finding_polarity": finding,
    }


def validate_assertion_derivation(
    ast: dict[str, Any],
    normalized: dict[str, Any],
    frame: dict[str, Any],
    typed_assertions: list[dict[str, Any]],
    authority: dict[str, Any],
    declared_records: list[dict[str, Any]] | None = None,
    declared_derivation: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """Validate and compare DERIVED, DECLARED_EVENT_FRAME, and TYPED assertions."""
    authority_errors = validate_surface_scope_target(
        ast, normalized, authority, declared_records
    )
    if authority_errors:
        return None, authority_errors
    derived = derive_assertion(ast, frame, authority, declared_records)
    errors: list[dict[str, str]] = []
    declared = frame["frames"][0]["assertion"]
    if declared_derivation is not None and declared_derivation != derived:
        errors.append(
            error(
                "CNS-SOLVER-ASSERTION-DERIVATION",
                "ASSERTION_DERIVATION_MISMATCH",
                "/assertion_derivation",
            )
        )
    if (
        declared["assertion_status"] != derived["derived_event_assertion"]
        or declared["finding_polarity"] != derived["derived_finding_polarity"]
    ):
        errors.append(
            error(
                "CNS-SOLVER-ASSERTION-DERIVATION",
                "ASSERTION_DERIVATION_MISMATCH",
                "/event_frame/frames/0/assertion",
            )
        )
    frame_id = frame["frames"][0]["frame_id"]
    typed = [item for item in typed_assertions if item.get("frame_id") == frame_id]
    if (
        len(typed) != 1
        or typed[0].get("assertion_status") != derived["derived_event_assertion"]
        or typed[0].get("finding_polarity") != derived["derived_finding_polarity"]
    ):
        errors.append(
            error(
                "CNS-SOLVER-ASSERTION-DERIVATION",
                "ASSERTION_DERIVATION_MISMATCH",
                "/typed_solution/resolved_events",
            )
        )
    return derived, ordered(errors, authority)
