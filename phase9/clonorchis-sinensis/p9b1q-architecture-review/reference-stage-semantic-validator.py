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
import json
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIXTURES = HERE / "fixtures"
CONTRACT = HERE / "stage-semantic-validator-contract.yml"
REGISTRY = HERE / "constraint-id-registry.yml"
NEGATIVE = FIXTURES / "stage-validator-negative-fixtures.yml"


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
    if not dangling:
        for index, item in enumerate(ast["assertion_markers"]):
            if item["scope_status"] == "UNIQUE" and len(item["scope_target_candidate_ids"]) != 1:
                errors.append(error("CNS-AST-SCOPE_TARGET_INTEGRITY", "SCOPE_TARGET_INVALID", f"/assertion_markers/{index}"))
    return ordered(errors)


def validate_s2(frame: dict[str, Any], normalized: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    frame_ids = {item["frame_id"] for item in frame["frames"]}
    specimen_ids = {item["specimen_slot_id"] for item in frame["specimen_slots"]}
    slot_ids = {slot["slot_id"] for item in frame["frames"] for slot in item["participant_slots"]}
    all_ids = frame_ids | specimen_ids | slot_ids
    if len(all_ids) != len(frame_ids) + len(specimen_ids) + len(slot_ids):
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
    if dangling:
        errors.append(error("CNS-EF-REF_INTEGRITY", "DANGLING_REFERENCE", "/frames"))
    for fi, item in enumerate(frame["frames"]):
        for si, slot in enumerate(item["participant_slots"]):
            domain = slot["domain"]
            if slot["binding_status"] == "FIXED" and not domain["entity_ids"]:
                errors.append(error("CNS-EF-NONEMPTY_FIXED_DOMAIN", "EMPTY_FIXED_DOMAIN", f"/frames/{fi}/participant_slots/{si}/domain"))
        identity = item["normalized_identity"]
        if identity["event_type_domain"] != item["event_type_domain"]:
            errors.append(error("CNS-EF-IDENTITY_CONSISTENCY", "EVENT_IDENTITY_MISMATCH", f"/frames/{fi}/normalized_identity/event_type_domain"))
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


def validate_core_minimality(core: dict[str, Any], emission: dict[str, Any]) -> list[str]:
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
    if material_ids(core) != dag_ids:
        return ["CNS-SOLVER-LICENSE_DAG"]
    return []


def validate_s3(typed: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    registry = {entry["id"] for entry in load_yaml(REGISTRY)["entries"]}
    core = solution_core(typed)
    unknown = set(core["satisfied_constraint_ids"]) - registry
    if unknown:
        errors.append(error("CNS-SOLVER-REGISTRY_MEMBERSHIP", "UNKNOWN_CONSTRAINT_ID", "/selected_solution/satisfied_constraint_ids"))
    if typed["status"] == "UNIQUE" and typed["solution_cardinality"] != "ONE":
        errors.append(error("CNS-SOLVER-SOLUTION_CARDINALITY", "SOLUTION_CARDINALITY_MISMATCH", "/solution_cardinality"))
    if typed["status"] == "UNIQUE" and not any(core[key] for key in ("resolved_mentions", "resolved_events", "resolved_relations", "semantic_roles", "narrative_intents")):
        errors.append(error("CNS-SOLVER-NONEMPTY_UNIQUE", "EMPTY_UNIQUE_SOLUTION", "/selected_solution"))
    emission = typed["selected_solution"]["queryir_emission_record"]
    core_failure = validate_core_minimality(core, emission)
    for constraint in core_failure:
        failure = {
            "CNS-SOLVER-ENTITY_RESOLUTION": "INPUT_HASH_MISMATCH",
            "CNS-SOLVER-EVENT_RELATION_DERIVATION": "EVENT_RELATION_DERIVATION_MISMATCH",
            "CNS-SOLVER-LICENSE_DAG": "LICENSE_DAG_INVALID",
        }[constraint]
        errors.append(error(constraint, failure, "/selected_solution"))
    if not dag_valid(emission["license_dag"]):
        errors.append(error("CNS-SOLVER-LICENSE_DAG", "LICENSE_DAG_INVALID", "/selected_solution/queryir_emission_record/license_dag"))
    retained = set(emission["minimality_witness"]["retained_semantic_object_ids"])
    witnesses = {item["semantic_object_id"] for item in emission["minimality_witness"]["retained_object_witnesses"]}
    if retained != witnesses or retained != material_ids(core):
        errors.append(error("CNS-SOLVER-MINIMALITY", "MINIMALITY_WITNESS_INVALID", "/selected_solution/queryir_emission_record/minimality_witness"))
    return ordered(errors)


def validate_s4(typed: dict[str, Any], query_ir: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    emission = typed["selected_solution"]["queryir_emission_record"]
    emitted = emission["query_ir"]
    pointers = all_json_pointers(emitted)
    traces = emission["field_traces"]
    trace_pointers = [item["query_ir_json_pointer"] for item in traces]
    if len(trace_pointers) != len(set(trace_pointers)) or set(trace_pointers) != set(pointers):
        errors.append(error("CNS-EMIT-LEAF_TRACE_COVERAGE", "TRACE_COVERAGE_INCOMPLETE", "/selected_solution/queryir_emission_record/field_traces"))
    for index, trace in enumerate(traces):
        if trace["query_ir_json_pointer"] in set(pointers) and canonical_sha(pointer_get(emitted, trace["query_ir_json_pointer"])) != trace["emitted_value_sha256"]:
            errors.append(error("CNS-EMIT-TRACE_VALUE_HASH", "TRACE_VALUE_HASH_MISMATCH", f"/selected_solution/queryir_emission_record/field_traces/{index}"))
    if query_ir != emitted:
        errors.append(error("CNS-EMIT-PROJECTION_ONLY", "NON_PURE_PROJECTION", "/"))
    return ordered(errors)


def resolved_object_hash(path: Path) -> tuple[str, int]:
    raw = path.read_bytes()
    if path.suffix == ".json":
        value = json.loads(raw)
        canonical = canonical_bytes(value)
        if raw != canonical:
            return "NONCANONICAL", len(raw)
        return sha_bytes(raw), len(raw)
    return sha_bytes(raw), len(raw)


def validate_s5(sidecar: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for index, reference in enumerate(sidecar["actual_objects"]):
        path = resolve_review_path(reference["path"])
        if not path.is_file():
            errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", f"/actual_objects/{index}/path"))
            continue
        actual_hash, _ = resolved_object_hash(path)
        if actual_hash != reference["canonical_sha256"]:
            errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", f"/actual_objects/{index}/canonical_sha256"))
    body = dict(sidecar)
    declared = body.pop("sidecar_sha256")
    if canonical_sha(body) != declared:
        errors.append(error("CNS-BIND-ACTUAL_OBJECT_HASH", "ACTUAL_OBJECT_BINDING_MISMATCH", "/sidecar_sha256"))
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
    results: list[dict[str, Any]] = []
    normalized = normalized_by_request_id()
    for suffix in ("exposure", "diagnostic"):
        request = load_json(FIXTURES / f"request-{suffix}-positive.json")
        norm = load_json(FIXTURES / f"normalized-request-{suffix}-positive.json")
        ast = load_json(FIXTURES / f"clause-ast-{suffix}-positive.json")
        frame = load_json(FIXTURES / f"event-frame-{suffix}-positive.json")
        results.extend(
            [
                {"case": f"POS-S0-{suffix}", "errors": validate_s0(norm, request)},
                {"case": f"POS-S1-{suffix}", "errors": validate_s1(ast, norm)},
                {"case": f"POS-S2-{suffix}", "errors": validate_s2(frame, norm)},
            ]
        )
    typed = load_json(FIXTURES / "typed-result-exposure-positive.json")
    query_ir = load_json(FIXTURES / "queryir-exposure-positive.json")
    sidecar = load_json(FIXTURES / "execution-binding-sidecar-positive.json")
    results.extend(
        [
            {"case": "POS-S3-exposure", "errors": validate_s3(typed)},
            {"case": "POS-S4-exposure", "errors": validate_s4(typed, query_ir)},
            {"case": "POS-S5-exposure", "errors": validate_s5(sidecar)},
        ]
    )
    return results


def run_minimality() -> list[dict[str, Any]]:
    core = load_json(FIXTURES / "typed-solution-exposure-positive.json")
    emission = load_json(FIXTURES / "queryir-emission-record-exposure-positive.json")
    results = []
    for path in sorted(FIXTURES.glob("minimality-removal-probe-*.json")):
        probe = load_json(path)
        candidate = apply_patch(core, probe["mutation"])
        observed = validate_core_minimality(candidate, emission)
        results.append(
            {
                "probe_id": probe["probe_id"],
                "candidate_sha256": canonical_sha(candidate),
                "observed_unsatisfied_constraint_ids": observed,
                "passed": canonical_sha(candidate) == probe["candidate_typed_solution_sha256"]
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
            errors = validate_s3(mutated)
        elif stage == "S4_QUERYIR_EMISSION":
            if "solver_result_version" in mutated:
                query_ir = load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
                errors = validate_s4(mutated, query_ir)
            else:
                typed = load_json(resolve_review_path(case["paired_actual_object_paths"][0]))
                errors = validate_s4(typed, mutated)
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
