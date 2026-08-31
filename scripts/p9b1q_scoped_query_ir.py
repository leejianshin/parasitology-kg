#!/usr/bin/env python3
"""Deterministic Scoped QueryIR and bound graph execution for P9-B1Q.

This module implements the contracts frozen under ``phase9/.../p9b1q``.  It
uses only the reviewed local authority bundle.  It does not call a model, the
network, or student data, and it never places claim/source/citation/answer
content in QueryIR.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml

try:
    from scripts import p9b1_local_retrieval as p9b1
except ModuleNotFoundError:  # Direct ``python scripts/...py`` execution.
    import p9b1_local_retrieval as p9b1


ROOT = Path(__file__).resolve().parents[1]
PHASE9 = Path("phase9/clonorchis-sinensis")
P9B1Q = PHASE9 / "p9b1q"
CONFIG_PATH = P9B1Q / "query-interpreter-config.yml"
QUERY_IR_SCHEMA_PATH = P9B1Q / "query-ir-schema-candidate.yml"
SEMANTIC_SCHEMA_PATH = P9B1Q / "semantic-validation-result-schema-candidate.yml"
SIDECAR_SCHEMA_PATH = P9B1Q / "execution-binding-sidecar-schema-candidate.yml"
SEMANTIC_CONTRACT_PATH = P9B1Q / "query-ir-semantic-contract.yml"
VALIDATOR_CONTRACT_PATH = P9B1Q / "query-ir-semantic-validator-contract.yml"
MAPPING_PATH = P9B1Q / "event-predicate-type-role-mapping.yml"
BINDING_CONTRACT_PATH = P9B1Q / "request-queryir-retrieval-audit-binding.yml"
AMBIGUITY_RULES_PATH = P9B1Q / "ambiguity-fail-closed-rules.yml"

ARCH_REVIEW = PHASE9 / "p9b1q-architecture-review"
NORMALIZED_REQUEST_SCHEMA_PATH = ARCH_REVIEW / "normalized-request-schema-candidate.yml"
CLAUSE_AST_SCHEMA_PATH = ARCH_REVIEW / "clause-ast-schema-candidate.yml"
CLAUSE_GRAMMAR_PATH = ARCH_REVIEW / "clause-grammar-config.yml"
STAGE_VALIDATOR_CONTRACT_PATH = ARCH_REVIEW / "stage-semantic-validator-contract.yml"
CANONICALIZATION_PROFILE_PATH = ARCH_REVIEW / "object-canonicalization-and-hash-chain.yml"
NEGATION_SURFACE_SCOPE_PATH = ARCH_REVIEW / "negation-surface-scope-authority.yml"
NEGATION_SEMANTIC_AUTHORITY_PATH = ARCH_REVIEW / "negation_semantic_authority.py"
ENTITY_ONTOLOGY_PATH = Path("schema/entity-types.yml")
EVENT_FRAME_SCHEMA_PATH = ARCH_REVIEW / "event-frame-schema-candidate.yml"
EVENT_IDENTITY_CONTRACT_PATH = ARCH_REVIEW / "event-identity-contract.yml"
EVENT_RELATION_AUTHORITY_PATH = (
    ARCH_REVIEW / "fixtures/authority-event-relation-mapping.json"
)

C1_TERMINAL_STAGE = "S1_CLAUSE_AST"
C1_IMPLEMENTED_STAGES = ("S0_REQUEST_NORMALIZATION", C1_TERMINAL_STAGE)
C1_PROHIBITED_STAGES = (
    "S2_EVENT_FRAME",
    "S3_TYPED_CONSTRAINT_SOLVER",
    "S4_QUERYIR_EMISSION_IMPLEMENTATION",
    "S5_RUNTIME_RETRIEVAL_BINDING",
)

C2_TERMINAL_STAGE = "S2_EVENT_FRAME"
C2_IMPLEMENTED_STAGES = (*C1_IMPLEMENTED_STAGES, C2_TERMINAL_STAGE)
C2_PROHIBITED_STAGES = (
    "S3_TYPED_CONSTRAINT_SOLVER",
    "S4_QUERYIR_EMISSION_IMPLEMENTATION",
    "S5_RUNTIME_RETRIEVAL_BINDING",
)

NORMATIVE_SCHEMA_PATHS = {
    "p9a_request_schema": PHASE9 / "request-schema.yml",
    "p9a_response_schema": PHASE9 / "response-schema.yml",
    "p9a_audit_schema": PHASE9 / "audit-log-schema.yml",
    "retrieval_result_schema": PHASE9 / "retrieval-result-schema.yml",
    "semantic_validation_result_schema": SEMANTIC_SCHEMA_PATH,
    "query_ir_schema": QUERY_IR_SCHEMA_PATH,
    "query_ir_semantic_contract": SEMANTIC_CONTRACT_PATH,
    "query_ir_semantic_validator_contract": VALIDATOR_CONTRACT_PATH,
    "event_predicate_type_role_mapping": MAPPING_PATH,
    "p9b1_retrieval_contract": PHASE9 / "p9b1-retrieval-contract.yml",
    "p9a_release_boundary": PHASE9 / "release-boundary.yml",
    "p9a_reviewer_evidence_admission": PHASE9 / "reviewer-evidence-admission.yml",
    "request_queryir_retrieval_audit_binding_contract": BINDING_CONTRACT_PATH,
    "ambiguity_fail_closed_rules": AMBIGUITY_RULES_PATH,
    "sidecar_schema": SIDECAR_SCHEMA_PATH,
}
NORMATIVE_AUTHORITY_PATHS = {
    "runtime_bundle": PHASE9 / "runtime-bundle-manifest.yml",
    "runtime_authority_projection": PHASE9 / "runtime-authority-projection.yml",
    "runtime_contract": PHASE9 / "runtime-contract.yml",
    "reviewed_nodes": Path("derived/clonorchis-sinensis/pcms-v1/nodes.jsonl"),
    "reviewed_edges": Path("derived/clonorchis-sinensis/pcms-v1/edges.jsonl"),
    "entity_type_schema": Path("schema/entity-types.yml"),
    "relation_type_schema": Path("schema/relation-types.yml"),
    "pcms_authority_review": (
        Path("phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml")
    ),
    "source_registry": Path("sources/registry.yml"),
}

_DATE_TIME_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_CLAUSE_SPLIT_RE = re.compile(r"[，,；;。！？!?]+")
_ID_RE = re.compile(r"^(?P<prefix>[A-Z]+)(?P<suffix>[0-9]+)$")


def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SchemaValidationError(ValueError):
    pass


def _schema_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }[expected]()


class LocalSchemaValidator:
    """Closed Draft-2020-12 subset covering every frozen local Schema keyword."""

    def __init__(self, schema: dict[str, Any]):
        self.schema = schema

    def validate(self, instance: Any) -> None:
        self._validate(instance, self.schema, "$")

    def is_valid(self, instance: Any, schema: Any) -> bool:
        try:
            self._validate(instance, schema, "$")
        except SchemaValidationError:
            return False
        return True

    def _resolve(self, ref: str) -> Any:
        if not ref.startswith("#/"):
            raise SchemaValidationError(f"unsupported non-local $ref: {ref}")
        value: Any = self.schema
        for token in ref[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(value, dict) or token not in value:
                raise SchemaValidationError(f"unresolvable $ref: {ref}")
            value = value[token]
        return value

    def _fail(self, path: str, message: str) -> None:
        raise SchemaValidationError(f"schema validation failed at {path}: {message}")

    def _validate(self, value: Any, schema: Any, path: str) -> None:
        if schema is True:
            return
        if schema is False:
            self._fail(path, "false Schema")
        if not isinstance(schema, dict):
            self._fail(path, "invalid Schema node")
        if "$ref" in schema:
            self._validate(value, self._resolve(schema["$ref"]), path)
            siblings = {key: item for key, item in schema.items() if key != "$ref"}
            if siblings:
                self._validate(value, siblings, path)
            return

        expected = schema.get("type")
        if expected is not None:
            types = expected if isinstance(expected, list) else [expected]
            if not any(_schema_type_matches(value, item) for item in types):
                self._fail(path, f"expected type {types}")
        if "const" in schema and canonical_bytes(value) != canonical_bytes(schema["const"]):
            self._fail(path, "const mismatch")
        if "enum" in schema and not any(
            canonical_bytes(value) == canonical_bytes(item) for item in schema["enum"]
        ):
            self._fail(path, "enum mismatch")

        if isinstance(value, dict):
            missing = [key for key in schema.get("required", []) if key not in value]
            if missing:
                self._fail(path, f"missing required properties {missing}")
            properties = schema.get("properties", {})
            for key, item in value.items():
                if key in properties:
                    self._validate(item, properties[key], f"{path}.{key}")
                elif schema.get("additionalProperties") is False:
                    self._fail(path, f"unexpected property {key}")
                elif isinstance(schema.get("additionalProperties"), (dict, bool)):
                    self._validate(
                        item, schema["additionalProperties"], f"{path}.{key}"
                    )
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                self._fail(path, "too few items")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                self._fail(path, "too many items")
            if schema.get("uniqueItems"):
                items = [canonical_bytes(item) for item in value]
                if len(set(items)) != len(items):
                    self._fail(path, "duplicate items")
            if "items" in schema:
                for index, item in enumerate(value):
                    self._validate(item, schema["items"], f"{path}[{index}]")
            if "contains" in schema:
                count = sum(self.is_valid(item, schema["contains"]) for item in value)
                if count < schema.get("minContains", 1):
                    self._fail(path, "minContains not met")
                if "maxContains" in schema and count > schema["maxContains"]:
                    self._fail(path, "maxContains exceeded")
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                self._fail(path, "minLength not met")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                self._fail(path, "maxLength exceeded")
            if "pattern" in schema and re.search(schema["pattern"], value) is None:
                self._fail(path, f"pattern mismatch: {schema['pattern']}")
            if schema.get("format") == "date-time" and not _DATE_TIME_RE.match(value):
                self._fail(path, "invalid date-time")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                self._fail(path, "below minimum")
            if "maximum" in schema and value > schema["maximum"]:
                self._fail(path, "above maximum")

        for child in schema.get("allOf", []):
            self._validate(value, child, path)
        if "anyOf" in schema and not any(
            self.is_valid(value, child) for child in schema["anyOf"]
        ):
            self._fail(path, "anyOf mismatch")
        if "oneOf" in schema:
            count = sum(self.is_valid(value, child) for child in schema["oneOf"])
            if count != 1:
                self._fail(path, f"oneOf matched {count} branches")
        if "not" in schema and self.is_valid(value, schema["not"]):
            self._fail(path, "forbidden by not")
        if "if" in schema:
            branch = "then" if self.is_valid(value, schema["if"]) else "else"
            if branch in schema:
                self._validate(value, schema[branch], path)


def validate_schema(instance: Any, schema_path: Path, root: Path = ROOT) -> None:
    LocalSchemaValidator(_read_yaml(root / schema_path)).validate(instance)


class C1ValidationError(ValueError):
    """Fail-closed S0/S1 compilation or semantic validation failure."""


def _c1_fail(stage: str, message: str) -> None:
    raise C1ValidationError(f"{stage}: {message}")


def _normalization_units(raw: str) -> tuple[str, list[dict[str, int]], list[str]]:
    """Apply only the frozen S0 whitespace profile and retain exact mappings."""
    output: list[str] = []
    spans: list[dict[str, int]] = []
    observed: set[str] = set()
    raw_index = 0
    normalized_index = 0

    def append(raw_start: int, raw_end: int, value: str, operation: str | None) -> None:
        nonlocal normalized_index
        output.append(value)
        spans.append({
            "raw_start": raw_start,
            "raw_end": raw_end,
            "normalized_start": normalized_index,
            "normalized_end": normalized_index + len(value),
        })
        normalized_index += len(value)
        if operation is not None:
            observed.add(operation)

    while raw_index < len(raw):
        if raw.startswith("\r\n", raw_index):
            append(raw_index, raw_index + 2, "\n", "CRLF_TO_LF")
            raw_index += 2
            continue
        if raw[raw_index] in " \t":
            end = raw_index + 1
            while end < len(raw) and raw[end] in " \t":
                end += 1
            if "\t" in raw[raw_index:end]:
                observed.add("TAB_TO_SINGLE_SPACE")
            if end - raw_index > 1:
                observed.add("COLLAPSE_ASCII_SPACE_RUN")
            append(raw_index, end, " ", None)
            raw_index = end
            continue
        append(raw_index, raw_index + 1, raw[raw_index], None)
        raw_index += 1

    # Coalesce only adjacent identity units. Changed units remain independently
    # auditable because their raw and normalized extents can differ.
    coalesced: list[dict[str, int]] = []
    normalized = "".join(output)
    for item in spans:
        is_identity = (
            raw[item["raw_start"] : item["raw_end"]]
            == normalized[item["normalized_start"] : item["normalized_end"]]
        )
        if coalesced:
            prior = coalesced[-1]
            prior_identity = (
                raw[prior["raw_start"] : prior["raw_end"]]
                == normalized[prior["normalized_start"] : prior["normalized_end"]]
            )
            if (
                is_identity
                and prior_identity
                and prior["raw_end"] == item["raw_start"]
                and prior["normalized_end"] == item["normalized_start"]
            ):
                prior["raw_end"] = item["raw_end"]
                prior["normalized_end"] = item["normalized_end"]
                continue
        coalesced.append(item)

    operation_order = (
        "CRLF_TO_LF",
        "TAB_TO_SINGLE_SPACE",
        "COLLAPSE_ASCII_SPACE_RUN",
    )
    operations = [item for item in operation_order if item in observed] or ["NONE"]
    return normalized, coalesced, operations


def normalize_request(request: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Compile a frozen P9-A request into the S0 normalized-request object."""
    try:
        validate_schema(request, PHASE9 / "request-schema.yml", root)
    except (SchemaValidationError, KeyError, TypeError) as exc:
        _c1_fail("S0_REQUEST_NORMALIZATION", f"invalid P9-A request: {exc}")
    raw = request["query_text"]
    normalized, spans, operations = _normalization_units(raw)
    result = {
        "normalized_request_version": "0.1-candidate",
        "request_id": request["request_id"],
        "request_sha256": canonical_sha256(request),
        "knowledge_version": request["knowledge_version"],
        "locale": request["locale"],
        "raw_query_text": raw,
        "normalized_query_text": normalized,
        "normalization_operations": operations,
        "raw_to_normalized_spans": spans,
        "producer": {
            "producer_id": "p9b1q-request-normalizer",
            "producer_version": "0.1-c1",
            "executable_sha256": file_sha256(Path(__file__)),
            "configuration_sha256": file_sha256(root / STAGE_VALIDATOR_CONTRACT_PATH),
        },
    }
    validate_c1_normalized_request(request, result, root)
    return result


def validate_c1_normalized_request(
    request: dict[str, Any], normalized: dict[str, Any], root: Path = ROOT
) -> None:
    """Validate S0 schema, request binding, transformation, and exact span map."""
    try:
        validate_schema(request, PHASE9 / "request-schema.yml", root)
        validate_schema(normalized, NORMALIZED_REQUEST_SCHEMA_PATH, root)
    except (SchemaValidationError, KeyError, TypeError) as exc:
        _c1_fail("S0_NORMALIZED_REQUEST", f"schema failure: {exc}")
    expected_text, expected_spans, expected_operations = _normalization_units(
        request["query_text"]
    )
    expected_binding = (
        normalized["request_id"] == request["request_id"]
        and normalized["request_sha256"] == canonical_sha256(request)
        and normalized["knowledge_version"] == request["knowledge_version"]
        and normalized["locale"] == request["locale"]
        and normalized["raw_query_text"] == request["query_text"]
    )
    if not expected_binding:
        _c1_fail("S0_NORMALIZED_REQUEST", "request binding mismatch")
    if (
        normalized["normalized_query_text"] != expected_text
        or normalized["raw_to_normalized_spans"] != expected_spans
        or normalized["normalization_operations"] != expected_operations
    ):
        _c1_fail("S0_NORMALIZED_REQUEST", "non-lossless or unauthorized normalization")


def _source_span(text: str, start: int, end: int) -> dict[str, Any]:
    return {"start_char": start, "end_char": end, "text": text[start:end]}


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _entity_type_from_id(entity_id: str, ontology: dict[str, Any]) -> str:
    prefix = entity_id.split(".", 1)[0]
    matches = [
        entity_type
        for entity_type, authority in ontology["entity_types"].items()
        if authority["id_prefix"] == prefix
    ]
    if len(matches) != 1:
        _c1_fail("S1_CLAUSE_AST", f"entity type is not licensed: {entity_id}")
    return matches[0]


def _operator_plan(
    text: str,
    start: int,
    end: int,
    config: dict[str, Any],
    shared_left_argument_available: bool = False,
) -> tuple[
    str,
    tuple[int, int],
    tuple[int, int],
    list[tuple[int, int, str]],
    bool,
] | None:
    """Return one source-bound structural operator without semantic inference.

    Each plan carries exactly one operator span. Repeated operators are
    represented by recursive plans, so no recognized surface operator remains
    hidden in a proposition leaf.
    """
    discourse = config["discourse"]
    separators = [match for match in re.finditer(r"[，,；;]", text[start:end])]

    # Prefix condition plus the first structural separator.
    for token in sorted(discourse["condition"], key=lambda value: (-len(value), value)):
        if text.startswith(token, start) and separators:
            sep_start = start + separators[0].start()
            left = _trim_span(text, start + len(token), sep_start)
            right = _trim_span(text, sep_start + 1, end)
            if left[0] < left[1] and right[0] < right[1]:
                return (
                    "CONDITION",
                    (start, end),
                    (start, start + len(token)),
                    [
                        (*left, "CONDITION_ANTECEDENT"),
                        (*right, "CONDITION_CONSEQUENT"),
                    ],
                    False,
                )

    lexical_kinds = (
        ("CONTRAST", "contrast", "CONTRAST_LEFT", "CONTRAST_RIGHT"),
        ("OVERRIDE", "override", "OVERRIDE_EARLIER", "OVERRIDE_LATER"),
        ("ALTERNATIVE_GROUP", "or", "ALTERNATIVE_BRANCH", "ALTERNATIVE_BRANCH"),
    )
    lexical_candidates: list[tuple[int, int, str, str, str, str]] = []
    for node_kind, config_key, left_role, right_role in lexical_kinds:
        for token in discourse[config_key]:
            for match in re.finditer(re.escape(token), text[start:end]):
                absolute_start = start + match.start()
                absolute_end = start + match.end()
                shared_contrast = (
                    node_kind == "CONTRAST"
                    and shared_left_argument_available
                    and absolute_start == start
                )
                if (absolute_start > start or shared_contrast) and absolute_end < end:
                    lexical_candidates.append(
                        (
                            absolute_start,
                            absolute_end,
                            token,
                            node_kind,
                            left_role,
                            right_role,
                        )
                    )
    if lexical_candidates:
        operator_start, operator_end, _, node_kind, left_role, right_role = sorted(
            lexical_candidates,
            key=lambda item: (item[0], -(item[1] - item[0]), item[3], item[2]),
        )[0]
        right = _trim_span(text, operator_end, end)
        if (
            node_kind == "CONTRAST"
            and shared_left_argument_available
            and operator_start == start
            and right[0] < right[1]
        ):
            return (
                node_kind,
                (start, end),
                (operator_start, operator_end),
                [(*right, "CONTRAST_RIGHT")],
                True,
            )
        left = _trim_span(text, start, operator_start)
        while left[1] > left[0] and text[left[1] - 1] in "，,；;":
            left = _trim_span(text, left[0], left[1] - 1)
        if left[0] < left[1] and right[0] < right[1]:
            return node_kind, (start, end), (operator_start, operator_end), [
                (*left, left_role),
                (*right, right_role),
            ], False

    if separators:
        operator_start = start + separators[0].start()
        left = _trim_span(text, start, operator_start)
        right = _trim_span(text, operator_start + 1, end)
        if left[0] < left[1] and right[0] < right[1]:
            return (
                "COORDINATION",
                (start, end),
                (operator_start, operator_start + 1),
                [
                    (*left, "COORDINATE_MEMBER"),
                    (*right, "COORDINATE_MEMBER"),
                ],
                False,
            )
    return None


def _append_clause_subtree(
    text: str,
    start: int,
    end: int,
    parent_node_id: str,
    scope_role: str,
    nodes: list[dict[str, Any]],
    next_node_id: list[int],
    config: dict[str, Any],
    shared_left_argument_node_id: str | None = None,
) -> str:
    """Append a deterministic pre-order, recursively compositional S1 subtree."""
    plan = _operator_plan(
        text,
        start,
        end,
        config,
        shared_left_argument_available=shared_left_argument_node_id is not None,
    )
    node_id = f"S{next_node_id[0]:03d}"
    next_node_id[0] += 1
    if plan is None:
        nodes.append({
            "node_id": node_id,
            "node_kind": "PROPOSITION",
            "source_span": _source_span(text, start, end),
            "operator_span": None,
            "parent_node_id": parent_node_id,
            "child_node_ids": [],
            "scope_role": scope_role,
            "assertion_marker_ids": [],
        })
        return node_id

    node_kind, node_span, operator_span, branches, uses_shared_left_argument = plan
    operator_node = {
        "node_id": node_id,
        "node_kind": node_kind,
        "source_span": _source_span(text, *node_span),
        "operator_span": _source_span(text, *operator_span),
        "parent_node_id": parent_node_id,
        "child_node_ids": [],
        "scope_role": scope_role,
        "assertion_marker_ids": [],
    }
    if uses_shared_left_argument:
        if shared_left_argument_node_id is None:
            _c1_fail("S1_CLAUSE_AST", "shared left argument has no target")
        operator_node["shared_left_argument_node_id"] = shared_left_argument_node_id
    nodes.append(operator_node)
    condition_antecedent_node_id: str | None = None
    for index, (branch_start, branch_end, branch_role) in enumerate(branches):
        branch_shared_left_argument_node_id = (
            condition_antecedent_node_id
            if node_kind == "CONDITION" and index == 1
            else None
        )
        child_id = _append_clause_subtree(
            text,
            branch_start,
            branch_end,
            node_id,
            branch_role,
            nodes,
            next_node_id,
            config,
            shared_left_argument_node_id=branch_shared_left_argument_node_id,
        )
        operator_node["child_node_ids"].append(child_id)
        if node_kind == "CONDITION" and index == 0:
            condition_antecedent_node_id = child_id
    return node_id


def _smallest_proposition(nodes: list[dict[str, Any]], start: int, end: int) -> str:
    candidates = [
        item
        for item in nodes
        if item["node_kind"] == "PROPOSITION"
        and item["source_span"]["start_char"] <= start
        and end <= item["source_span"]["end_char"]
    ]
    if not candidates:
        _c1_fail("S1_CLAUSE_AST", f"no proposition contains span {start}:{end}")
    return min(
        candidates,
        key=lambda item: (
            item["source_span"]["end_char"] - item["source_span"]["start_char"],
            item["node_id"],
        ),
    )["node_id"]


def _surface_mentions(
    text: str,
    nodes: list[dict[str, Any]],
    aliases: dict[str, Any],
    ontology: dict[str, Any],
) -> list[dict[str, Any]]:
    occurrences: dict[str, set[tuple[int, int, str]]] = {}
    for entity_id, values in aliases.get("entity_alias_extensions", {}).items():
        for alias in values:
            if not alias:
                continue
            for match in re.finditer(re.escape(alias), text):
                occurrences.setdefault(entity_id, set()).add(
                    (match.start(), match.end(), text[match.start() : match.end()])
                )
    # Exact-longest removes only overlapping aliases for the same formal entity.
    # Distinct entities remain separate surface candidates even when nested.
    candidates: dict[tuple[int, int, str], set[str]] = {}
    for entity_id, entity_occurrences in occurrences.items():
        retained: list[tuple[int, int, str]] = []
        for item in sorted(
            entity_occurrences,
            key=lambda value: (-(value[1] - value[0]), value[0], value[1], value[2]),
        ):
            if any(not (item[1] <= kept[0] or kept[1] <= item[0]) for kept in retained):
                continue
            retained.append(item)
        for item in retained:
            candidates.setdefault(item, set()).add(entity_id)
    result: list[dict[str, Any]] = []
    for index, ((start, end, surface), entity_ids) in enumerate(
        sorted(candidates.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])),
        1,
    ):
        ids = sorted(entity_ids)
        types = sorted({_entity_type_from_id(entity_id, ontology) for entity_id in ids})
        result.append({
            "surface_mention_id": f"U{index:03d}",
            "containing_node_id": _smallest_proposition(nodes, start, end),
            "source_span": _source_span(text, start, end),
            "normalized_surface": surface,
            "candidate_entity_ids": ids,
            "candidate_entity_types": types,
            "candidate_origin": "FORMAL_ALIAS_EXACT",
        })
    return result


def _assertion_markers(
    text: str,
    nodes: list[dict[str, Any]],
    mentions: list[dict[str, Any]],
    question_node_id: str | None,
    config: dict[str, Any],
    negation_authority: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    surfaces = negation_authority["source_classification"]
    occurrences: list[tuple[int, int, str]] = []
    for surface in surfaces:
        for match in re.finditer(re.escape(surface), text):
            occurrences.append((match.start(), match.end(), surface))
    # Longest licensed surface wins on overlap (e.g. 未检出 over 未).
    selected: list[tuple[int, int, str]] = []
    for item in sorted(occurrences, key=lambda value: (value[0], -(value[1] - value[0]), value[2])):
        if any(not (item[1] <= kept[0] or kept[1] <= item[0]) for kept in selected):
            continue
        selected.append(item)
    selected.sort(key=lambda value: (value[0], value[1], value[2]))

    markers: list[dict[str, Any]] = []
    attachments: list[dict[str, Any]] = []
    for start, end, surface in selected:
        classification = surfaces[surface]
        marker_id = f"K{len(markers) + 1:03d}"
        source_proposition = _smallest_proposition(nodes, start, end)
        if classification["grammar_class"] == "PARTICIPANT_ABSENCE_NEGATOR":
            targets = sorted(
                (
                    item for item in mentions
                    if item["containing_node_id"] == source_proposition
                    and item["source_span"]["start_char"] >= end
                ),
                key=lambda item: (
                    item["source_span"]["start_char"],
                    item["source_span"]["end_char"],
                    item["surface_mention_id"],
                ),
            )
            if not targets:
                _c1_fail(
                    "S1_CLAUSE_AST",
                    f"participant negator has no licensed target: {surface}",
                )
            target_ids = [item["surface_mention_id"] for item in targets]
            containing = source_proposition
        elif classification["grammar_class"] == "WH_INTERROGATIVE_FOCUS":
            if question_node_id is None:
                _c1_fail("S1_CLAUSE_AST", "WH focus is not contained by a QUESTION node")
            target_ids = [source_proposition]
            containing = question_node_id
        else:
            target_ids = [source_proposition]
            containing = source_proposition
        markers.append({
            "marker_id": marker_id,
            "containing_node_id": containing,
            "marker_kind": classification["marker_kind"],
            "source_span": _source_span(text, start, end),
            "scope_target_candidate_ids": target_ids,
            "scope_status": "UNIQUE" if len(target_ids) == 1 else "UNRESOLVED",
        })
        if classification["grammar_class"] in {
            "PARTICIPANT_ABSENCE_NEGATOR",
            "WH_INTERROGATIVE_FOCUS",
        }:
            attachments.append({
                "attachment_set_id": f"AT{len(attachments) + 1:03d}",
                "dependent_id": marker_id,
                "candidate_governor_ids": target_ids,
                "status": "UNIQUE" if len(target_ids) == 1 else "UNRESOLVED",
            })

    configured_classes = (
        ("EXCLUSION", config["discourse"]["exclusion"]),
        ("HYPOTHETICAL", config["discourse"]["hypothetical"]),
        ("HISTORICAL", config["temporal"]["historical"]),
        ("CURRENT", config["temporal"]["current"]),
        ("FUTURE", config["temporal"]["future"]),
    )
    configured_occurrences: list[tuple[int, int, str, str]] = []
    for marker_kind, marker_surfaces in configured_classes:
        for surface in marker_surfaces:
            for match in re.finditer(re.escape(surface), text):
                configured_occurrences.append(
                    (match.start(), match.end(), surface, marker_kind)
                )
    selected_configured: list[tuple[int, int, str, str]] = []
    for item in sorted(
        configured_occurrences,
        key=lambda value: (value[0], -(value[1] - value[0]), value[3], value[2]),
    ):
        if any(
            item[3] == kept[3]
            and not (item[1] <= kept[0] or kept[1] <= item[0])
            for kept in selected_configured
        ):
            continue
        selected_configured.append(item)
    for start, end, _, marker_kind in selected_configured:
        if any(
            item["marker_kind"] == marker_kind
            and item["source_span"]["start_char"] == start
            and item["source_span"]["end_char"] == end
            for item in markers
        ):
            continue
        proposition_candidates = [
            item
            for item in nodes
            if item["node_kind"] == "PROPOSITION"
            and item["source_span"]["start_char"] <= start
            and end <= item["source_span"]["end_char"]
        ]
        if proposition_candidates:
            containing_node = min(
                proposition_candidates,
                key=lambda item: (
                    item["source_span"]["end_char"] - item["source_span"]["start_char"],
                    item["node_id"],
                ),
            )
            targets = [containing_node["node_id"]]
            if marker_kind == "EXCLUSION":
                mention_targets = sorted(
                    (
                        item for item in mentions
                        if item["containing_node_id"] == containing_node["node_id"]
                        and item["source_span"]["start_char"] >= end
                    ),
                    key=lambda item: (
                        item["source_span"]["start_char"],
                        item["surface_mention_id"],
                    ),
                )
                if mention_targets:
                    targets = [item["surface_mention_id"] for item in mention_targets]
            containing = containing_node["node_id"]
        else:
            operator_candidates = [
                item for item in nodes
                if item["node_kind"] not in {"ROOT", "PROPOSITION", "QUESTION"}
                and item["source_span"]["start_char"] <= start
                and end <= item["source_span"]["end_char"]
            ]
            if not operator_candidates:
                _c1_fail("S1_CLAUSE_AST", f"configured marker has no structural container: {text[start:end]}")
            containing_node = min(
                operator_candidates,
                key=lambda item: (
                    item["source_span"]["end_char"] - item["source_span"]["start_char"],
                    item["node_id"],
                ),
            )
            containing = containing_node["node_id"]
            targets = [containing_node["child_node_ids"][0]]
        marker_id = f"K{len(markers) + 1:03d}"
        markers.append({
            "marker_id": marker_id,
            "containing_node_id": containing,
            "marker_kind": marker_kind,
            "source_span": _source_span(text, start, end),
            "scope_target_candidate_ids": targets,
            "scope_status": "UNIQUE" if len(targets) == 1 else "UNRESOLVED",
        })

    structural_operators = [
        item
        for item in nodes
        if item["node_kind"]
        in {"COORDINATION", "CONDITION", "CONTRAST", "OVERRIDE", "ALTERNATIVE_GROUP"}
    ]
    for operator in structural_operators:
        marker_id = f"K{len(markers) + 1:03d}"
        markers.append({
            "marker_id": marker_id,
            "containing_node_id": operator["node_id"],
            "marker_kind": "CONNECTIVE",
            "source_span": operator["operator_span"],
            "scope_target_candidate_ids": [operator["node_id"]],
            "scope_status": "UNIQUE",
        })
    return markers, attachments


def _load_negation_semantic_authority(root: Path) -> Any:
    path = root / NEGATION_SEMANTIC_AUTHORITY_PATH
    spec = importlib.util.spec_from_file_location("p9b1q_negation_semantic_authority", path)
    if spec is None or spec.loader is None:
        _c1_fail("S1_CLAUSE_AST", "cannot resolve frozen negation semantic authority")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recognized_lexical_operator_spans(
    text: str,
    material_start: int,
    material_end: int,
    config: dict[str, Any],
) -> list[tuple[int, int, str]]:
    """Return longest, non-overlapping structural surfaces licensed in this span."""
    candidates: list[tuple[int, int, str, str]] = []
    for config_key in ("condition", "contrast", "override", "or"):
        for surface in config["discourse"][config_key]:
            for match in re.finditer(re.escape(surface), text[material_start:material_end]):
                start = material_start + match.start()
                end = material_start + match.end()
                is_condition = (
                    config_key == "condition"
                    and start == material_start
                    and re.search(r"[，,；;]", text[end:material_end]) is not None
                )
                is_infix = (
                    config_key != "condition"
                    and start > material_start
                    and end < material_end
                )
                if is_condition or is_infix:
                    candidates.append((start, end, surface, config_key))
    selected: list[tuple[int, int, str, str]] = []
    for item in sorted(
        candidates,
        key=lambda value: (value[0], -(value[1] - value[0]), value[3], value[2]),
    ):
        if any(not (item[1] <= kept[0] or kept[1] <= item[0]) for kept in selected):
            continue
        selected.append(item)
    return [(start, end, surface) for start, end, surface, _ in selected]


def compile_clause_ast(
    normalized: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    """Compile only S1 syntax and surface domains; never construct S2 objects."""
    try:
        validate_schema(normalized, NORMALIZED_REQUEST_SCHEMA_PATH, root)
    except (SchemaValidationError, KeyError, TypeError) as exc:
        _c1_fail("S1_CLAUSE_AST", f"invalid normalized request: {exc}")
    text = normalized["normalized_query_text"]
    grammar = _read_yaml(root / CLAUSE_GRAMMAR_PATH)
    aliases = _read_yaml(root / CONFIG_PATH)
    ontology = _read_yaml(root / ENTITY_ONTOLOGY_PATH)
    negation_authority = _read_yaml(root / NEGATION_SURFACE_SCOPE_PATH)

    material_start, material_end = _trim_span(text, 0, len(text))
    while material_end > material_start and text[material_end - 1] in "。.!！？?":
        material_end -= 1
        material_start, material_end = _trim_span(text, material_start, material_end)
    if material_start >= material_end:
        _c1_fail("S1_CLAUSE_AST", "request contains no material proposition")

    nodes: list[dict[str, Any]] = [{
        "node_id": "S000",
        "node_kind": "ROOT",
        "source_span": _source_span(text, 0, len(text)),
        "operator_span": None,
        "parent_node_id": None,
        "child_node_ids": [],
        "scope_role": "WHOLE_REQUEST",
        "assertion_marker_ids": [],
    }]
    next_id = 1
    wh_surfaces = [
        surface
        for surface, authority in negation_authority["source_classification"].items()
        if authority["marker_kind"] == "WH_FOCUS" and surface in text
    ]
    is_question = bool(wh_surfaces) or text.rstrip().endswith(("?", "？"))
    question_node_id: str | None = None
    parent_id = "S000"
    parent_role = "MATERIAL_PROPOSITION"
    if is_question:
        question_node_id = f"S{next_id:03d}"
        next_id += 1
        wh_start = min((text.index(item) for item in wh_surfaces), default=material_end)
        wh_end = max((wh_start + len(item) for item in wh_surfaces if text.find(item) == wh_start), default=len(text))
        nodes.append({
            "node_id": question_node_id,
            "node_kind": "QUESTION",
            "source_span": _source_span(text, 0, len(text)),
            "operator_span": _source_span(text, wh_start, wh_end) if wh_start < wh_end else None,
            "parent_node_id": "S000",
            "child_node_ids": [],
            "scope_role": "QUESTION_FOCUS",
            "assertion_marker_ids": [],
        })
        nodes[0]["child_node_ids"] = [question_node_id]
        parent_id = question_node_id

    next_node_id = [next_id]
    material_node_id = _append_clause_subtree(
        text,
        material_start,
        material_end,
        parent_id,
        parent_role,
        nodes,
        next_node_id,
        aliases,
    )
    next(item for item in nodes if item["node_id"] == parent_id)["child_node_ids"] = [material_node_id]

    mentions = _surface_mentions(text, nodes, aliases, ontology)
    markers, attachments = _assertion_markers(
        text,
        nodes,
        mentions,
        question_node_id,
        aliases,
        negation_authority,
    )
    marker_membership: dict[str, list[str]] = {}
    for marker in markers:
        marker_membership.setdefault(marker["containing_node_id"], []).append(marker["marker_id"])
    for node in nodes:
        node["assertion_marker_ids"] = marker_membership.get(node["node_id"], [])

    ast = {
        "clause_ast_version": "0.2-candidate",
        "request_id": normalized["request_id"],
        "request_sha256": normalized["request_sha256"],
        "normalized_request_sha256": canonical_sha256(normalized),
        "knowledge_version": normalized["knowledge_version"],
        "entity_ontology_sha256": file_sha256(root / ENTITY_ONTOLOGY_PATH),
        "clause_grammar_config_sha256": file_sha256(root / CLAUSE_GRAMMAR_PATH),
        "canonicalization_profile_sha256": file_sha256(root / CANONICALIZATION_PROFILE_PATH),
        "stage_validator_contract_sha256": file_sha256(root / STAGE_VALIDATOR_CONTRACT_PATH),
        "span_basis": "REQUEST_QUERY_TEXT_UNICODE_CODEPOINT_ZERO_BASED_HALF_OPEN",
        "producer": {
            "producer_id": "p9b1q-clause-ast-compiler",
            "producer_version": "0.2-c1",
            "executable_sha256": file_sha256(Path(__file__)),
            "configuration_sha256": file_sha256(root / CLAUSE_GRAMMAR_PATH),
        },
        "root_node_id": "S000",
        "nodes": nodes,
        "surface_mentions": mentions,
        "assertion_markers": markers,
        "attachment_sets": attachments,
    }
    validate_c1_clause_ast(normalized, ast, root)
    return ast


def _span_contains(parent: dict[str, Any], child: dict[str, Any]) -> bool:
    return (
        parent["start_char"] <= child["start_char"]
        and child["end_char"] <= parent["end_char"]
    )


def _spans_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return max(left["start_char"], right["start_char"]) < min(
        left["end_char"], right["end_char"]
    )


def _validate_shared_left_argument_integrity(
    nodes: dict[str, dict[str, Any]],
) -> None:
    """Enforce the frozen local S1 shared-argument edge and single realization."""
    for owner in nodes.values():
        target_id = owner.get("shared_left_argument_node_id")
        if target_id is None:
            if owner["node_kind"] == "CONTRAST" and len(owner["child_node_ids"]) == 1:
                _c1_fail(
                    "S1_CLAUSE_AST",
                    "single-child CONTRAST requires a shared left argument",
                )
            continue
        target = nodes.get(target_id)
        if target is None:
            _c1_fail("S1_CLAUSE_AST", "shared left argument target is missing")
        if owner["node_kind"] != "CONTRAST":
            _c1_fail("S1_CLAUSE_AST", "shared left argument owner is not CONTRAST")
        if len(owner["child_node_ids"]) != 1:
            _c1_fail(
                "S1_CLAUSE_AST",
                "shared CONTRAST must have exactly one explicit right child",
            )
        right = nodes.get(owner["child_node_ids"][0])
        if right is None or right["scope_role"] != "CONTRAST_RIGHT":
            _c1_fail(
                "S1_CLAUSE_AST",
                "shared CONTRAST explicit child is not CONTRAST_RIGHT",
            )
        if target_id in owner["child_node_ids"]:
            _c1_fail(
                "S1_CLAUSE_AST",
                "shared left argument is also materialized as an explicit child",
            )
        parent = nodes.get(owner["parent_node_id"])
        if (
            parent is None
            or parent["node_kind"] != "CONDITION"
            or owner["scope_role"] != "CONDITION_CONSEQUENT"
            or owner["node_id"] not in parent["child_node_ids"]
        ):
            _c1_fail(
                "S1_CLAUSE_AST",
                "shared CONTRAST is not the immediate CONDITION consequent",
            )
        antecedents = [
            nodes[child_id]
            for child_id in parent["child_node_ids"]
            if nodes[child_id]["scope_role"] == "CONDITION_ANTECEDENT"
        ]
        consequents = [
            nodes[child_id]
            for child_id in parent["child_node_ids"]
            if nodes[child_id]["scope_role"] == "CONDITION_CONSEQUENT"
        ]
        if (
            len(antecedents) != 1
            or antecedents[0]["node_id"] != target_id
            or target["node_kind"] != "PROPOSITION"
            or target["parent_node_id"] != parent["node_id"]
            or len(consequents) != 1
            or consequents[0]["node_id"] != owner["node_id"]
        ):
            _c1_fail(
                "S1_CLAUSE_AST",
                "shared target is not the unique immediate CONDITION antecedent proposition",
            )
        if (
            target["source_span"]["start_char"] >= owner["source_span"]["start_char"]
            or target["source_span"]["end_char"] > owner["source_span"]["start_char"]
        ):
            _c1_fail("S1_CLAUSE_AST", "shared left argument is not strictly backward")
        if "shared_left_argument_node_id" in target:
            _c1_fail("S1_CLAUSE_AST", "shared left argument reference chain is prohibited")
        realizations = [
            node
            for node in nodes.values()
            if node["node_kind"] == "PROPOSITION"
            and node["source_span"] == target["source_span"]
        ]
        if len(realizations) != 1:
            _c1_fail(
                "S1_CLAUSE_AST",
                "shared antecedent proposition is not realized exactly once",
            )


def validate_c1_clause_ast(
    normalized: dict[str, Any], ast: dict[str, Any], root: Path = ROOT
) -> None:
    """Apply frozen S1 schema, binding, graph, span, alias, and scope gates."""
    try:
        validate_schema(normalized, NORMALIZED_REQUEST_SCHEMA_PATH, root)
        validate_schema(ast, CLAUSE_AST_SCHEMA_PATH, root)
    except (SchemaValidationError, KeyError, TypeError) as exc:
        _c1_fail("S1_CLAUSE_AST", f"schema failure: {exc}")
    expected_hashes = {
        "request_id": normalized["request_id"],
        "request_sha256": normalized["request_sha256"],
        "normalized_request_sha256": canonical_sha256(normalized),
        "knowledge_version": normalized["knowledge_version"],
        "entity_ontology_sha256": file_sha256(root / ENTITY_ONTOLOGY_PATH),
        "clause_grammar_config_sha256": file_sha256(root / CLAUSE_GRAMMAR_PATH),
        "canonicalization_profile_sha256": file_sha256(root / CANONICALIZATION_PROFILE_PATH),
        "stage_validator_contract_sha256": file_sha256(root / STAGE_VALIDATOR_CONTRACT_PATH),
    }
    if any(ast.get(key) != value for key, value in expected_hashes.items()):
        _c1_fail("S1_CLAUSE_AST", "input or frozen-authority hash binding mismatch")

    nodes = {item["node_id"]: item for item in ast["nodes"]}
    mentions = {item["surface_mention_id"]: item for item in ast["surface_mentions"]}
    markers = {item["marker_id"]: item for item in ast["assertion_markers"]}
    if len(nodes) != len(ast["nodes"]) or len(mentions) != len(ast["surface_mentions"]) or len(markers) != len(ast["assertion_markers"]):
        _c1_fail("S1_CLAUSE_AST", "duplicate IDs")
    roots = [item for item in nodes.values() if item["node_kind"] == "ROOT"]
    if len(roots) != 1 or roots[0]["node_id"] != ast["root_node_id"] or roots[0]["parent_node_id"] is not None:
        _c1_fail("S1_CLAUSE_AST", "single-root invariant failed")
    for node in nodes.values():
        if node["parent_node_id"] is not None:
            parent = nodes.get(node["parent_node_id"])
            if parent is None or node["node_id"] not in parent["child_node_ids"]:
                _c1_fail("S1_CLAUSE_AST", "parent/child reference mismatch")
        if any(child not in nodes for child in node["child_node_ids"]):
            _c1_fail("S1_CLAUSE_AST", "dangling child reference")
        if any(marker not in markers for marker in node["assertion_marker_ids"]):
            _c1_fail("S1_CLAUSE_AST", "dangling marker reference")
    _validate_shared_left_argument_integrity(nodes)
    visited: set[str] = set()
    pending = [ast["root_node_id"]]
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            _c1_fail("S1_CLAUSE_AST", "cycle or duplicate AST reachability")
        visited.add(node_id)
        pending.extend(nodes[node_id]["child_node_ids"])
    if visited != set(nodes):
        _c1_fail("S1_CLAUSE_AST", "AST contains unreachable nodes")
    valid_targets = set(nodes) | set(mentions)
    for marker in markers.values():
        candidates = marker["scope_target_candidate_ids"]
        if any(target not in valid_targets for target in candidates):
            _c1_fail("S1_CLAUSE_AST", "dangling scope target")
        if (marker["scope_status"] == "UNIQUE") != (len(candidates) == 1):
            _c1_fail("S1_CLAUSE_AST", "scope target cardinality mismatch")
    for attachment in ast["attachment_sets"]:
        candidates = attachment["candidate_governor_ids"]
        if any(target not in valid_targets | set(markers) for target in candidates):
            _c1_fail("S1_CLAUSE_AST", "dangling attachment governor")
        if (attachment["status"] == "UNIQUE") != (len(candidates) == 1):
            _c1_fail("S1_CLAUSE_AST", "attachment cardinality mismatch")

    text = normalized["normalized_query_text"]
    spans: list[dict[str, Any]] = []
    for node in nodes.values():
        spans.append(node["source_span"])
        if node["operator_span"] is not None:
            spans.append(node["operator_span"])
    spans.extend(item["source_span"] for item in mentions.values())
    spans.extend(item["source_span"] for item in markers.values())
    if any(
        not (0 <= span["start_char"] < span["end_char"] <= len(text))
        or text[span["start_char"] : span["end_char"]] != span["text"]
        for span in spans
    ):
        _c1_fail("S1_CLAUSE_AST", "source span mismatch")
    if roots[0]["source_span"] != _source_span(text, 0, len(text)):
        _c1_fail("S1_CLAUSE_AST", "root does not cover the complete request")
    node_spans = [item["source_span"] for item in nodes.values()]
    for left_index, left in enumerate(node_spans):
        for right in node_spans[left_index + 1 :]:
            crossing = (
                left["start_char"] < right["start_char"] < left["end_char"] < right["end_char"]
                or right["start_char"] < left["start_char"] < right["end_char"] < left["end_char"]
            )
            if crossing:
                _c1_fail("S1_CLAUSE_AST", "crossing node spans")
    for parent in nodes.values():
        children = [nodes[child_id] for child_id in parent["child_node_ids"]]
        if any(
            not _span_contains(parent["source_span"], child["source_span"])
            for child in children
        ):
            _c1_fail("S1_CLAUSE_AST", "child span escapes parent source span")
        for left_index, left in enumerate(children):
            for right in children[left_index + 1 :]:
                if _spans_overlap(left["source_span"], right["source_span"]):
                    _c1_fail("S1_CLAUSE_AST", "sibling node spans overlap or contain")
    for mention in mentions.values():
        containing_node = nodes.get(mention["containing_node_id"])
        if (
            containing_node is None
            or containing_node["node_kind"] != "PROPOSITION"
            or not _span_contains(
                containing_node["source_span"], mention["source_span"]
            )
        ):
            _c1_fail("S1_CLAUSE_AST", "surface mention lacks proposition grounding")

    grammar_config = _read_yaml(root / CONFIG_PATH)
    material_start, material_end = _trim_span(text, 0, len(text))
    while material_end > material_start and text[material_end - 1] in "。.!！？?":
        material_end -= 1
        material_start, material_end = _trim_span(text, material_start, material_end)
    structural_operator_spans = [
        (
            item["operator_span"]["start_char"],
            item["operator_span"]["end_char"],
            item["operator_span"]["text"],
        )
        for item in nodes.values()
        if item["node_kind"]
        in {"COORDINATION", "CONDITION", "CONTRAST", "OVERRIDE", "ALTERNATIVE_GROUP"}
    ]
    for recognized in _recognized_lexical_operator_spans(
        text, material_start, material_end, grammar_config
    ):
        if structural_operator_spans.count(recognized) != 1:
            _c1_fail(
                "S1_CLAUSE_AST",
                f"recognized operator lacks exactly one structural node: {recognized}",
            )
        if any(
            item["source_span"]["start_char"] <= recognized[0]
            and recognized[1] <= item["source_span"]["end_char"]
            for item in nodes.values()
            if item["node_kind"] == "PROPOSITION"
        ):
            _c1_fail(
                "S1_CLAUSE_AST",
                f"recognized operator leaked into proposition leaf: {recognized}",
            )

    aliases = _read_yaml(root / CONFIG_PATH).get("entity_alias_extensions", {})
    ontology = _read_yaml(root / ENTITY_ONTOLOGY_PATH)
    for mention in mentions.values():
        surface = mention["normalized_surface"]
        if surface != mention["source_span"]["text"]:
            _c1_fail("S1_CLAUSE_AST", "normalized surface is not exact")
        if any(surface not in aliases.get(entity_id, []) for entity_id in mention["candidate_entity_ids"]):
            _c1_fail("S1_CLAUSE_AST", "surface mention is not licensed by alias authority")
        expected_types = sorted({_entity_type_from_id(entity_id, ontology) for entity_id in mention["candidate_entity_ids"]})
        if mention["candidate_entity_types"] != expected_types:
            _c1_fail("S1_CLAUSE_AST", "candidate entity type domain mismatch")

    negation_authority = _read_yaml(root / NEGATION_SURFACE_SCOPE_PATH)
    negation_semantic = _load_negation_semantic_authority(root)
    governed_kinds = {
        item["marker_kind"]
        for item in negation_authority["source_classification"].values()
    }
    unresolved_governed = [
        item
        for item in ast["assertion_markers"]
        if item["scope_status"] == "UNRESOLVED"
        and (
            item["marker_kind"] in governed_kinds
            or item["source_span"]["text"]
            in negation_authority["source_classification"]
        )
    ]
    candidate_views: list[dict[str, Any]] = []
    if unresolved_governed:
        # The frozen executable derives one path at a time. Validate every
        # preserved candidate through that executable without selecting a
        # winner or mutating the frozen authority.
        for unresolved in unresolved_governed:
            for target_id in unresolved["scope_target_candidate_ids"]:
                candidate_view = copy.deepcopy(ast)
                for marker in candidate_view["assertion_markers"]:
                    if marker["scope_status"] != "UNRESOLVED":
                        continue
                    selected_target = (
                        target_id
                        if marker["marker_id"] == unresolved["marker_id"]
                        else marker["scope_target_candidate_ids"][0]
                    )
                    marker["scope_target_candidate_ids"] = [selected_target]
                    marker["scope_status"] = "UNIQUE"
                candidate_views.append(candidate_view)
    else:
        candidate_views.append(ast)
    for candidate_view in candidate_views:
        authority_errors = negation_semantic.validate_surface_scope_target(
            candidate_view, normalized, negation_authority
        )
        if authority_errors:
            _c1_fail(
                "S1_CLAUSE_AST",
                f"frozen marker/scope authority failure: {authority_errors[0]}",
            )
    validate_c1_stop_boundary(ast)


def validate_c1_stop_boundary(value: dict[str, Any]) -> None:
    """Reject any S2+ or runtime object accidentally introduced into C1 output."""
    prohibited_keys = {
        "event_frame",
        "event_frames",
        "events",
        "typed_constraint_result",
        "selected_solution",
        "query_ir",
        "retrieval_result",
        "model_response",
    }
    pending: list[Any] = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            overlap = prohibited_keys.intersection(item)
            if overlap:
                _c1_fail("C1_STOP_BOUNDARY", f"prohibited downstream object keys: {sorted(overlap)}")
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def compile_c1(request: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Run the authorized C1 atom and stop at a validated Clause AST."""
    normalized = normalize_request(request, root)
    ast = compile_clause_ast(normalized, root)
    result = {
        "implemented_stages": list(C1_IMPLEMENTED_STAGES),
        "terminal_stage": C1_TERMINAL_STAGE,
        "normalized_request": normalized,
        "normalized_request_sha256": canonical_sha256(normalized),
        "clause_ast": ast,
        "clause_ast_sha256": canonical_sha256(ast),
    }
    validate_c1_stop_boundary(result)
    return result


class C2ValidationError(ValueError):
    pass


def _c2_fail(stage: str, message: str) -> None:
    raise C2ValidationError(f"{stage}: {message}")


def _load_event_authority(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    mapping = json.loads((root / EVENT_RELATION_AUTHORITY_PATH).read_text(encoding="utf-8"))
    public_mapping = _read_yaml(root / MAPPING_PATH)
    if mapping.get("event_mapping") != public_mapping.get("event_mapping"):
        _c2_fail("S2_EVENT_FRAME", "event mapping projection differs from public authority")
    return mapping, public_mapping


def _entity_type_map(ontology: dict[str, Any]) -> dict[str, str]:
    return {
        authority["id_prefix"]: entity_type
        for entity_type, authority in ontology["entity_types"].items()
    }


def _candidate_domain(
    mention: dict[str, Any],
    allowed_types: set[str],
    prefix_types: dict[str, str],
) -> tuple[list[str], list[str]]:
    entity_ids = sorted(
        entity_id
        for entity_id in mention["candidate_entity_ids"]
        if prefix_types.get(entity_id.split(".", 1)[0]) in allowed_types
    )
    entity_types = sorted(
        {prefix_types[entity_id.split(".", 1)[0]] for entity_id in entity_ids}
    )
    return entity_ids, entity_types


def _node_descendants(
    node_id: str, nodes_by_id: dict[str, dict[str, Any]]
) -> set[str]:
    result: set[str] = set()
    pending = list(nodes_by_id[node_id]["child_node_ids"])
    while pending:
        current = pending.pop()
        if current in result:
            continue
        result.add(current)
        pending.extend(nodes_by_id[current]["child_node_ids"])
    return result


def _node_ancestors(
    node_id: str, nodes_by_id: dict[str, dict[str, Any]]
) -> list[str]:
    result: list[str] = []
    current = nodes_by_id[node_id]["parent_node_id"]
    while current is not None:
        result.append(current)
        current = nodes_by_id[current]["parent_node_id"]
    return result


def _event_domain_for_proposition(
    proposition: dict[str, Any],
    mentions: list[dict[str, Any]],
    config: dict[str, Any],
    mapping: dict[str, Any],
) -> tuple[list[str], dict[str, set[str]]]:
    """Return every formally licensed event type and its expressed predicates."""
    text = proposition["source_span"]["text"]
    present_types = {
        entity_type
        for mention in mentions
        for entity_type in mention["candidate_entity_types"]
    }
    if "diagnostic_method" in present_types:
        return ["DIAGNOSTIC_FINDING"], {"DIAGNOSTIC_FINDING": set()}

    expressed_predicates = {
        predicate
        for predicate, cues in config["predicate_cues"].items()
        if _contains_any(text, cues)
    }
    candidates: dict[str, set[str]] = {}
    for event_type, authority in mapping["event_mapping"].items():
        matched = expressed_predicates.intersection(authority.get("predicates", {}))
        if matched:
            candidates[event_type] = matched

    exposure_cue = (
        _contains_any(text, config["role_cues"]["epidemiologic_exposure_clue"])
        or _contains_any(text, config["topic_cues"]["exposure"])
    )
    if exposure_cue and present_types.intersection({"behavior", "environment"}):
        candidates = {"EXPOSURE": candidates.get("EXPOSURE", set())}

    if not candidates and "behavior" in present_types:
        # The reviewed consumption behavior is a target licensed by both event
        # classes.  Without an expressed narrowing cue S2 preserves both.
        candidates = {"EXPOSURE": set(), "INGESTION": set()}

    viable: dict[str, set[str]] = {}
    for event_type, predicates in candidates.items():
        authority = mapping["event_mapping"][event_type]
        actor_types = set(authority.get("allowed_actor_types", []))
        target_types = set(authority.get("allowed_target_types", []))
        if present_types.intersection(actor_types | target_types):
            viable[event_type] = predicates
    ordered = [
        event_type
        for event_type in mapping["event_mapping"]
        if event_type in viable
    ]
    return ordered, viable


def _role_type_domains(
    event_types: list[str],
    expressed: dict[str, set[str]],
    mapping: dict[str, Any],
) -> tuple[set[str], set[str]]:
    actor_domains: list[set[str]] = []
    target_domains: list[set[str]] = []
    for event_type in event_types:
        authority = mapping["event_mapping"][event_type]
        predicates = expressed.get(event_type, set())
        if predicates:
            actor = {
                entity_type
                for predicate in predicates
                for entity_type in authority["predicates"][predicate]["subject_from"]
                if entity_type != "method_entity_id"
            }
            target = {
                entity_type
                for predicate in predicates
                for entity_type in authority["predicates"][predicate]["object_from"]
                if entity_type != "method_entity_id"
            }
        else:
            actor = set(authority.get("allowed_actor_types", []))
            target = set(authority.get("allowed_target_types", []))
        actor_domains.append(actor)
        target_domains.append(target)
    return set.intersection(*actor_domains), set.intersection(*target_domains)


def _maximal_role_candidates(
    candidates: list[tuple[dict[str, Any], list[str], list[str]]]
) -> list[tuple[dict[str, Any], list[str], list[str]]]:
    result: list[tuple[dict[str, Any], list[str], list[str]]] = []
    for candidate in candidates:
        span = candidate[0]["source_span"]
        if any(
            other is not candidate
            and other[0]["source_span"]["start_char"] <= span["start_char"]
            and span["end_char"] <= other[0]["source_span"]["end_char"]
            and other[0]["source_span"] != span
            for other in candidates
        ):
            continue
        result.append(candidate)
    return result


def _frame_marker_context(
    proposition: dict[str, Any],
    participant_source_ids: set[str],
    ast: dict[str, Any],
) -> list[dict[str, Any]]:
    nodes_by_id = {node["node_id"]: node for node in ast["nodes"]}
    ancestors = set(_node_ancestors(proposition["node_id"], nodes_by_id))
    governed_ids = {proposition["node_id"], *participant_source_ids}
    result: list[dict[str, Any]] = []
    for marker in ast["assertion_markers"]:
        targets = set(marker["scope_target_candidate_ids"])
        if targets.intersection(governed_ids):
            result.append(marker)
            continue
        if (
            marker["containing_node_id"] in ancestors
            and targets.intersection(ancestors | {proposition["node_id"]})
        ):
            result.append(marker)
    return sorted(result, key=lambda item: item["marker_id"])


def _assertion_envelope(
    proposition: dict[str, Any],
    participant_source_ids: set[str],
    ast: dict[str, Any],
    config: dict[str, Any],
    negation_authority: dict[str, Any],
    diagnostic: bool,
) -> tuple[dict[str, Any], list[str]]:
    markers = _frame_marker_context(proposition, participant_source_ids, ast)
    status_candidates: set[str] = set()
    temporal_candidates: set[str] = set()
    polarity_sources: list[str] = []
    for marker in markers:
        kind = marker["marker_kind"]
        if kind == "EXCLUSION":
            status_candidates.add("EXCLUDED")
        elif kind == "HYPOTHETICAL":
            status_candidates.add("HYPOTHETICAL")
        elif kind in {"HISTORICAL", "CURRENT", "FUTURE"}:
            temporal_candidates.add(kind)
        elif kind == "NEGATOR":
            authority = negation_authority["source_classification"].get(
                marker["source_span"]["text"]
            )
            if authority is None:
                _c2_fail("S2_EVENT_FRAME", "negator lacks frozen surface authority")
            if authority["semantic_effect"] == "EVENT_NEGATION":
                status_candidates.add("NEGATED")
            elif authority["semantic_effect"] == "PARTICIPANT_NEGATION":
                polarity_sources.append(marker["marker_id"])
    if len(status_candidates) > 1 or len(temporal_candidates) > 1:
        _c2_fail("S2_EVENT_FRAME", "assertion or temporal scope remains unrepresentable")
    assertion_status = next(iter(status_candidates), "AFFIRMED")
    temporal_scope = next(iter(temporal_candidates), "GENERAL")
    finding_polarity = "NOT_APPLICABLE"
    if diagnostic:
        finding_polarity = _diagnostic_polarity(
            proposition["source_span"]["text"], config
        )
        if polarity_sources:
            finding_polarity = "NEGATIVE"
        if not polarity_sources:
            polarity_sources = [proposition["node_id"]]
    envelope = {
        "assertion_status": assertion_status,
        "finding_polarity": finding_polarity,
        "temporal_scope": temporal_scope,
        "governing_ast_node_ids": [proposition["node_id"]],
        "marker_ids": [
            marker["marker_id"]
            for marker in markers
            if marker["marker_kind"] != "CONNECTIVE"
        ],
    }
    return envelope, polarity_sources


def _specimen_surface(
    mention: dict[str, Any], specimen_code: str
) -> dict[str, Any] | None:
    surfaces = {
        "STOOL": ("粪便", "粪样", "大便"),
        "DUODENAL_FLUID": ("十二指肠引流液", "十二指肠液"),
    }
    source = mention["source_span"]
    for surface in surfaces.get(specimen_code, ()):
        offset = source["text"].find(surface)
        if offset >= 0:
            start = source["start_char"] + offset
            return {
                "start_char": start,
                "end_char": start + len(surface),
                "text": surface,
            }
    return None


def _method_specimen_code(entity_id: str) -> str:
    codes = {
        "diagnostic.stool_egg_microscopy": "STOOL",
        "diagnostic.duodenal_fluid_egg_microscopy": "DUODENAL_FLUID",
        "diagnostic.biliary_imaging": "NOT_APPLICABLE",
    }
    if entity_id not in codes:
        _c2_fail("S2_EVENT_FRAME", f"diagnostic specimen mapping is absent: {entity_id}")
    return codes[entity_id]


def _frame_identity_signature(
    frame: dict[str, Any], specimens: dict[str, dict[str, Any]]
) -> tuple[Any, ...]:
    slots = {slot["slot_id"]: slot for slot in frame["participant_slots"]}
    identity = frame["normalized_identity"]

    def entities(slot_ids: list[str]) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    entity_id
                    for slot_id in slot_ids
                    for entity_id in slots[slot_id]["domain"]["entity_ids"]
                }
            )
        )

    method_ids = ()
    if identity["method_slot_id"] is not None:
        method_ids = entities([identity["method_slot_id"]])
    specimen_codes = tuple(
        sorted(
            {
                code
                for slot_id in identity["specimen_slot_ids"]
                for code in specimens[slot_id]["specimen_code_domain"]
            }
        )
    ) or ("NOT_APPLICABLE",)
    return (
        tuple(frame["event_type_domain"]),
        entities(identity["actor_slot_ids"]),
        method_ids,
        specimen_codes,
        entities(identity["target_slot_ids"]),
        entities(identity["anatomical_site_slot_ids"]),
    )


def normalized_event_identity(
    frame: dict[str, Any], event_frame: dict[str, Any]
) -> tuple[Any, ...]:
    """Execute the frozen event identity contract without using frame IDs."""
    specimens = {
        item["specimen_slot_id"]: item for item in event_frame["specimen_slots"]
    }
    return _frame_identity_signature(frame, specimens)


def same_normalized_event_identity(
    left: dict[str, Any], right: dict[str, Any], event_frame: dict[str, Any]
) -> bool:
    return normalized_event_identity(left, event_frame) == normalized_event_identity(
        right, event_frame
    )


def _state_difference_domain(
    earlier: dict[str, Any], later: dict[str, Any]
) -> list[str]:
    fields = (
        ("ASSERTION_STATUS", "assertion_status"),
        ("FINDING_POLARITY", "finding_polarity"),
        ("TEMPORAL_SCOPE", "temporal_scope"),
    )
    return [
        dimension
        for dimension, field in fields
        if earlier["assertion"][field] != later["assertion"][field]
    ]


def _build_reference_hypotheses(
    proposition_nodes: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    frame_node_ids: dict[str, str],
    specimens: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    node_start = {
        node["node_id"]: node["source_span"]["start_char"]
        for node in proposition_nodes
    }
    for node in proposition_nodes:
        text = node["source_span"]["text"]
        current = [
            frame
            for frame in frames
            if frame_node_ids[frame["frame_id"]] == node["node_id"]
        ]
        prior = [
            frame
            for frame in frames
            if node_start[frame_node_ids[frame["frame_id"]]]
            < node["source_span"]["start_char"]
        ]
        if "同一" in text and "事件" in text and not current:
            if "诊断" in text:
                prior = [
                    frame
                    for frame in prior
                    if "DIAGNOSTIC_FINDING" in frame["event_type_domain"]
                ]
            if len(prior) < 2:
                continue
            anaphor = prior[-1]
            candidates = prior[:-1]
            relations = sorted(
                {
                    "SAME_EVENT"
                    if _frame_identity_signature(anaphor, specimens)
                    == _frame_identity_signature(candidate, specimens)
                    else "DISTINCT_EVENT"
                    for candidate in candidates
                }
            )
            result.append({
                "reference_hypothesis_id": f"RH{len(result) + 1:03d}",
                "anaphor_source_id": frame_node_ids[anaphor["frame_id"]],
                "anaphor_frame_id": anaphor["frame_id"],
                "candidate_referent_ids": [
                    candidate["frame_id"] for candidate in candidates
                ],
                "identity_relation_domain": relations,
                "status": (
                    "UNIQUE"
                    if len(candidates) == 1 and len(relations) == 1
                    else "UNRESOLVED"
                ),
            })
        if "另一" in text and "事件" in text and current and prior:
            for anaphor in current:
                # The frozen R3A evidence defines “另一…事件” against the
                # immediately preceding explicit event anchor.  This is a
                # grammatical anchor relation, not a distance-based winner
                # chosen from multiple otherwise compatible referents.
                candidates = prior[-1:]
                relations = sorted(
                    {
                        "SAME_EVENT"
                        if _frame_identity_signature(anaphor, specimens)
                        == _frame_identity_signature(candidate, specimens)
                        else "DISTINCT_EVENT"
                        for candidate in candidates
                    }
                )
                result.append({
                    "reference_hypothesis_id": f"RH{len(result) + 1:03d}",
                    "anaphor_source_id": frame_node_ids[anaphor["frame_id"]],
                    "anaphor_frame_id": anaphor["frame_id"],
                    "candidate_referent_ids": [
                        candidate["frame_id"] for candidate in candidates
                    ],
                    "identity_relation_domain": relations,
                    "status": (
                        "UNIQUE"
                        if len(candidates) == 1 and len(relations) == 1
                        else "UNRESOLVED"
                    ),
                })
    return result


def _override_hypothesis(
    override_node_id: str,
    earlier: list[dict[str, Any]],
    later: list[dict[str, Any]],
    specimens: dict[str, dict[str, Any]],
    number: int,
) -> dict[str, Any] | None:
    if not earlier or not later:
        return None
    valid: list[tuple[dict[str, Any], dict[str, Any], list[str]]] = []
    observed_dimensions: set[str] = set()
    for left in earlier:
        for right in later:
            differences = _state_difference_domain(left, right)
            observed_dimensions.update(differences)
            if (
                _frame_identity_signature(left, specimens)
                == _frame_identity_signature(right, specimens)
                and differences
            ):
                valid.append((left, right, differences))
    if valid:
        earlier_ids = sorted({item[0]["frame_id"] for item in valid})
        later_ids = sorted({item[1]["frame_id"] for item in valid})
        dimensions = [
            dimension
            for dimension in (
                "ASSERTION_STATUS",
                "FINDING_POLARITY",
                "TEMPORAL_SCOPE",
            )
            if any(dimension in item[2] for item in valid)
        ]
        status = (
            "UNIQUE"
            if len(valid) == 1 and len(dimensions) == 1
            else "UNRESOLVED"
        )
    else:
        earlier_ids = [item["frame_id"] for item in earlier]
        later_ids = [item["frame_id"] for item in later]
        dimensions = [
            dimension
            for dimension in (
                "ASSERTION_STATUS",
                "FINDING_POLARITY",
                "TEMPORAL_SCOPE",
            )
            if dimension in observed_dimensions
        ] or ["ASSERTION_STATUS", "FINDING_POLARITY", "TEMPORAL_SCOPE"]
        status = "NO_MATCH"
    return {
        "override_hypothesis_id": f"OH{number:03d}",
        "override_ast_node_id": override_node_id,
        "earlier_frame_ids": earlier_ids,
        "later_frame_ids": later_ids,
        "identity_constraint": "SAME_NORMALIZED_IDENTITY_EXCLUDING_ASSERTION",
        "overridden_dimension_domain": dimensions,
        "status": status,
    }


def _build_override_hypotheses(
    nodes: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    frame_node_ids: dict[str, str],
    specimens: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    nodes_by_id = {node["node_id"]: node for node in nodes}
    frames_by_node: dict[str, list[dict[str, Any]]] = {}
    for frame in frames:
        frames_by_node.setdefault(frame_node_ids[frame["frame_id"]], []).append(frame)
    result: list[dict[str, Any]] = []
    covered_statements: set[str] = set()
    for node in nodes:
        if node["node_kind"] != "OVERRIDE" or len(node["child_node_ids"]) != 2:
            continue
        left_ids = _node_descendants(node["child_node_ids"][0], nodes_by_id) | {
            node["child_node_ids"][0]
        }
        right_ids = _node_descendants(node["child_node_ids"][1], nodes_by_id) | {
            node["child_node_ids"][1]
        }
        earlier = [
            frame for source_id in left_ids for frame in frames_by_node.get(source_id, [])
        ]
        later = [
            frame for source_id in right_ids for frame in frames_by_node.get(source_id, [])
        ]
        hypothesis = _override_hypothesis(
            node["node_id"], earlier, later, specimens, len(result) + 1
        )
        if hypothesis:
            result.append(hypothesis)
            covered_statements.add(node["node_id"])

    proposition_nodes = [node for node in nodes if node["node_kind"] == "PROPOSITION"]
    for node in proposition_nodes:
        if "覆盖" not in node["source_span"]["text"] or node["node_id"] in covered_statements:
            continue
        prior = [
            frame
            for frame in frames
            if nodes_by_id[frame_node_ids[frame["frame_id"]]]["source_span"]["end_char"]
            <= node["source_span"]["start_char"]
        ]
        if len(prior) < 2:
            continue
        if "结果" in node["source_span"]["text"]:
            prior = [
                frame
                for frame in prior
                if "DIAGNOSTIC_FINDING" in frame["event_type_domain"]
            ]
        if len(prior) < 2:
            continue
        if (
            "后次" in node["source_span"]["text"]
            and "前次" in node["source_span"]["text"]
        ):
            earlier, later = prior[-2:-1], prior[-1:]
        else:
            earlier, later = prior[:-1], prior[-1:]
        hypothesis = _override_hypothesis(
            node["node_id"], earlier, later, specimens, len(result) + 1
        )
        if hypothesis:
            result.append(hypothesis)
    return result


def _build_event_frame(
    normalized: dict[str, Any], ast: dict[str, Any], root: Path
) -> dict[str, Any]:
    ontology = _read_yaml(root / ENTITY_ONTOLOGY_PATH)
    prefix_types = _entity_type_map(ontology)
    mapping, _ = _load_event_authority(root)
    config = _load_configuration(root)
    negation_authority = _read_yaml(root / NEGATION_SURFACE_SCOPE_PATH)
    nodes_by_id = {node["node_id"]: node for node in ast["nodes"]}
    propositions = sorted(
        (node for node in ast["nodes"] if node["node_kind"] == "PROPOSITION"),
        key=lambda node: (
            node["source_span"]["start_char"],
            node["source_span"]["end_char"],
            node["node_id"],
        ),
    )
    mentions_by_node: dict[str, list[dict[str, Any]]] = {}
    for mention in ast["surface_mentions"]:
        mentions_by_node.setdefault(mention["containing_node_id"], []).append(mention)
    unresolved_target_groups = [
        set(attachment["candidate_governor_ids"])
        for attachment in ast["attachment_sets"]
        if attachment["status"] == "UNRESOLVED"
    ]

    frames: list[dict[str, Any]] = []
    specimen_slots: list[dict[str, Any]] = []
    frame_node_ids: dict[str, str] = {}
    next_slot = 1
    for proposition in propositions:
        mentions = sorted(
            mentions_by_node.get(proposition["node_id"], []),
            key=lambda item: (
                item["source_span"]["start_char"],
                item["source_span"]["end_char"],
                item["surface_mention_id"],
            ),
        )
        event_types, expressed = _event_domain_for_proposition(
            proposition, mentions, config, mapping
        )
        if not event_types:
            continue
        diagnostic = event_types == ["DIAGNOSTIC_FINDING"]
        actor_types, target_types = _role_type_domains(event_types, expressed, mapping)
        role_candidates: dict[
            str, list[tuple[dict[str, Any], list[str], list[str]]]
        ] = {"ACTOR": [], "METHOD": [], "TARGET": [], "LOCATION": []}
        for mention in mentions:
            if diagnostic:
                ids, types = _candidate_domain(
                    mention, {"diagnostic_method"}, prefix_types
                )
                if ids:
                    role_candidates["METHOD"].append((mention, ids, types))
            ids, types = _candidate_domain(mention, actor_types, prefix_types)
            if ids:
                role_candidates["ACTOR"].append((mention, ids, types))
            location_ids, location_types = _candidate_domain(
                mention, {"anatomical_site"}.intersection(target_types), prefix_types
            )
            if location_ids:
                role_candidates["LOCATION"].append(
                    (mention, location_ids, location_types)
                )
            ids, types = _candidate_domain(
                mention, target_types - {"anatomical_site"}, prefix_types
            )
            if ids:
                role_candidates["TARGET"].append((mention, ids, types))
        for role in role_candidates:
            role_candidates[role] = _maximal_role_candidates(role_candidates[role])

        participant_slots: list[dict[str, Any]] = []
        slots_by_role: dict[str, list[str]] = {
            "ACTOR": [], "METHOD": [], "TARGET": [], "LOCATION": []
        }

        def add_slot(
            role: str,
            group: list[tuple[dict[str, Any], list[str], list[str]]],
        ) -> str:
            nonlocal next_slot
            source_ids = sorted({item[0]["surface_mention_id"] for item in group})
            entity_ids = sorted({entity_id for item in group for entity_id in item[1]})
            entity_types = sorted({entity_type for item in group for entity_type in item[2]})
            if not source_ids or not entity_ids or not entity_types:
                _c2_fail("S2_EVENT_FRAME", f"empty {role} participant domain")
            slot_id = f"V{next_slot:03d}"
            next_slot += 1
            participant_slots.append({
                "slot_id": slot_id,
                "semantic_role": role,
                "source_ids": source_ids,
                "domain": {
                    "entity_ids": entity_ids,
                    "entity_types": entity_types,
                },
                "binding_status": "FIXED" if len(entity_ids) == 1 else "COMPETING",
            })
            slots_by_role[role].append(slot_id)
            return slot_id

        for role in ("ACTOR", "METHOD"):
            candidates = role_candidates[role]
            if role == "METHOD" and len(candidates) > 1:
                add_slot(role, candidates)
            else:
                for candidate in candidates:
                    add_slot(role, [candidate])

        target_candidates = role_candidates["TARGET"]
        consumed: set[str] = set()
        for unresolved in unresolved_target_groups:
            group = [
                candidate
                for candidate in target_candidates
                if candidate[0]["surface_mention_id"] in unresolved
            ]
            if len(group) >= 2:
                add_slot("TARGET", group)
                consumed.update(item[0]["surface_mention_id"] for item in group)
        for candidate in target_candidates:
            if candidate[0]["surface_mention_id"] not in consumed:
                add_slot("TARGET", [candidate])
        for candidate in role_candidates["LOCATION"]:
            add_slot("LOCATION", [candidate])

        if not participant_slots:
            continue
        participant_source_ids = {
            source_id
            for slot in participant_slots
            for source_id in slot["source_ids"]
        }
        assertion, polarity_sources = _assertion_envelope(
            proposition,
            participant_source_ids,
            ast,
            config,
            negation_authority,
            diagnostic,
        )
        diagnostic_binding = None
        specimen_ids: list[str] = []
        if diagnostic:
            if len(slots_by_role["METHOD"]) != 1:
                _c2_fail("S2_EVENT_FRAME", "diagnostic frame lacks one method domain")
            method_slot_id = slots_by_role["METHOD"][0]
            method_slot = next(
                slot for slot in participant_slots if slot["slot_id"] == method_slot_id
            )
            source_mentions = [
                mention
                for mention in mentions
                if mention["surface_mention_id"] in method_slot["source_ids"]
            ]
            specimen_codes = sorted(
                {_method_specimen_code(entity_id) for entity_id in method_slot["domain"]["entity_ids"]}
            )
            specimen_spans: list[dict[str, Any]] = []
            for code in specimen_codes:
                if code == "NOT_APPLICABLE":
                    # This is the frozen non-concrete code for biliary
                    # imaging, not an inferred specimen.  The method mention
                    # is the auditable source for the formal absence.
                    specimen_spans.extend(
                        mention["source_span"] for mention in source_mentions
                    )
                    continue
                matches = [
                    span
                    for mention in source_mentions
                    if (span := _specimen_surface(mention, code)) is not None
                ]
                if not matches:
                    _c2_fail(
                        "S2_EVENT_FRAME",
                        f"specimen {code} is not explicitly source-grounded",
                    )
                specimen_spans.extend(matches)
            specimen_slot_id = f"SP{len(specimen_slots) + 1:03d}"
            specimen_slots.append({
                "specimen_slot_id": specimen_slot_id,
                "source_ids": method_slot["source_ids"],
                "source_spans": sorted(
                    {canonical_bytes(span): span for span in specimen_spans}.values(),
                    key=lambda span: (span["start_char"], span["end_char"], span["text"]),
                ),
                "specimen_code_domain": specimen_codes,
                "binding_status": "FIXED" if len(specimen_codes) == 1 else "COMPETING",
            })
            specimen_ids = [specimen_slot_id]
            diagnostic_binding = {
                "method_slot_id": method_slot_id,
                "specimen_slot_id": specimen_slot_id,
                "target_slot_ids": slots_by_role["TARGET"],
                "polarity_source_ids": polarity_sources,
            }

        incomplete = diagnostic and (
            assertion["finding_polarity"] == "UNSPECIFIED"
            or not slots_by_role["TARGET"]
        )
        competing = (
            len(event_types) > 1
            or any(slot["binding_status"] == "COMPETING" for slot in participant_slots)
            or any(
                specimen["binding_status"] == "COMPETING"
                for specimen in specimen_slots
                if specimen["specimen_slot_id"] in specimen_ids
            )
        )
        frame_id = f"EF{len(frames) + 1:03d}"
        frame = {
            "frame_id": frame_id,
            "event_type_domain": event_types,
            "source_ast_node_ids": [proposition["node_id"]],
            "source_spans": [proposition["source_span"]],
            "participant_slots": participant_slots,
            "assertion": assertion,
            "diagnostic_binding": diagnostic_binding,
            "normalized_identity": {
                "event_type_domain": event_types,
                "actor_slot_ids": slots_by_role["ACTOR"],
                "method_slot_id": slots_by_role["METHOD"][0]
                if slots_by_role["METHOD"]
                else None,
                "specimen_slot_ids": specimen_ids,
                "target_slot_ids": slots_by_role["TARGET"],
                "anatomical_site_slot_ids": slots_by_role["LOCATION"],
                "temporal_scope_domain": [assertion["temporal_scope"]],
            },
            "frame_status": (
                "INCOMPLETE" if incomplete else "COMPETING" if competing else "FIXED"
            ),
        }
        frames.append(frame)
        frame_node_ids[frame_id] = proposition["node_id"]

    specimens_by_id = {
        item["specimen_slot_id"]: item for item in specimen_slots
    }
    event_frame = {
        "event_frame_version": "0.2-candidate",
        "request_id": normalized["request_id"],
        "request_sha256": normalized["request_sha256"],
        "normalized_request_sha256": canonical_sha256(normalized),
        "knowledge_version": normalized["knowledge_version"],
        "clause_ast_sha256": canonical_sha256(ast),
        "entity_ontology_sha256": file_sha256(root / ENTITY_ONTOLOGY_PATH),
        "event_relation_mapping_sha256": file_sha256(
            root / EVENT_RELATION_AUTHORITY_PATH
        ),
        "canonicalization_profile_sha256": file_sha256(
            root / CANONICALIZATION_PROFILE_PATH
        ),
        "stage_validator_contract_sha256": file_sha256(
            root / STAGE_VALIDATOR_CONTRACT_PATH
        ),
        "producer": {
            "producer_id": "p9b1q-event-frame-compiler",
            "producer_version": "0.2-c2",
            "executable_sha256": file_sha256(Path(__file__)),
            "configuration_sha256": file_sha256(
                root / EVENT_RELATION_AUTHORITY_PATH
            ),
        },
        "frames": frames,
        "specimen_slots": specimen_slots,
        "reference_hypotheses": _build_reference_hypotheses(
            propositions, frames, frame_node_ids, specimens_by_id
        ),
        "override_hypotheses": _build_override_hypotheses(
            ast["nodes"], frames, frame_node_ids, specimens_by_id
        ),
    }
    return event_frame


def validate_c2_event_frame(
    normalized: dict[str, Any],
    ast: dict[str, Any],
    event_frame: dict[str, Any],
    root: Path = ROOT,
    *,
    require_compiler_projection: bool = True,
) -> None:
    """Validate S2 schema, content bindings, domains, identity, and completeness."""
    try:
        validate_schema(normalized, NORMALIZED_REQUEST_SCHEMA_PATH, root)
        validate_c1_clause_ast(normalized, ast, root)
        validate_schema(event_frame, EVENT_FRAME_SCHEMA_PATH, root)
    except (SchemaValidationError, C1ValidationError, KeyError, TypeError) as exc:
        _c2_fail("S2_EVENT_FRAME", f"schema or input failure: {exc}")
    expected_bindings = {
        "request_id": normalized["request_id"],
        "request_sha256": normalized["request_sha256"],
        "normalized_request_sha256": canonical_sha256(normalized),
        "knowledge_version": normalized["knowledge_version"],
        "clause_ast_sha256": canonical_sha256(ast),
        "entity_ontology_sha256": file_sha256(root / ENTITY_ONTOLOGY_PATH),
        "event_relation_mapping_sha256": file_sha256(
            root / EVENT_RELATION_AUTHORITY_PATH
        ),
        "canonicalization_profile_sha256": file_sha256(
            root / CANONICALIZATION_PROFILE_PATH
        ),
        "stage_validator_contract_sha256": file_sha256(
            root / STAGE_VALIDATOR_CONTRACT_PATH
        ),
    }
    if any(event_frame.get(key) != value for key, value in expected_bindings.items()):
        _c2_fail("S2_EVENT_FRAME", "actual input hash or request binding mismatch")
    expected_producer = {
        "producer_id": "p9b1q-event-frame-compiler",
        "producer_version": "0.2-c2",
        "executable_sha256": file_sha256(Path(__file__)),
        "configuration_sha256": file_sha256(root / EVENT_RELATION_AUTHORITY_PATH),
    }
    if event_frame["producer"] != expected_producer:
        _c2_fail("S2_EVENT_FRAME", "producer binding mismatch")

    ast_nodes = {node["node_id"]: node for node in ast["nodes"]}
    mentions = {
        mention["surface_mention_id"]: mention for mention in ast["surface_mentions"]
    }
    marker_ids = {marker["marker_id"] for marker in ast["assertion_markers"]}
    specimen_slots = {
        specimen["specimen_slot_id"]: specimen
        for specimen in event_frame["specimen_slots"]
    }
    all_ids: list[str] = []
    for frame in event_frame["frames"]:
        all_ids.append(frame["frame_id"])
        all_ids.extend(slot["slot_id"] for slot in frame["participant_slots"])
    all_ids.extend(specimen_slots)
    all_ids.extend(
        reference["reference_hypothesis_id"]
        for reference in event_frame["reference_hypotheses"]
    )
    all_ids.extend(
        override["override_hypothesis_id"]
        for override in event_frame["override_hypotheses"]
    )
    if len(all_ids) != len(set(all_ids)):
        _c2_fail("S2_EVENT_FRAME", "semantic IDs are not globally unique")

    for frame in event_frame["frames"]:
        if any(source_id not in ast_nodes for source_id in frame["source_ast_node_ids"]):
            _c2_fail("S2_EVENT_FRAME", "frame has dangling AST provenance")
        expected_spans = [
            ast_nodes[source_id]["source_span"]
            for source_id in frame["source_ast_node_ids"]
        ]
        if frame["source_spans"] != expected_spans:
            _c2_fail("S2_EVENT_FRAME", "frame source span is not exact AST provenance")
        slots = {slot["slot_id"]: slot for slot in frame["participant_slots"]}
        for slot in frame["participant_slots"]:
            if any(source_id not in mentions for source_id in slot["source_ids"]):
                _c2_fail("S2_EVENT_FRAME", "participant has dangling mention source")
            licensed = {
                entity_id
                for source_id in slot["source_ids"]
                for entity_id in mentions[source_id]["candidate_entity_ids"]
                if _entity_type_from_id(
                    entity_id, _read_yaml(root / ENTITY_ONTOLOGY_PATH)
                ) in slot["domain"]["entity_types"]
            }
            if set(slot["domain"]["entity_ids"]) != licensed:
                _c2_fail("S2_EVENT_FRAME", "participant domain is incomplete or unlicensed")
            if slot["binding_status"] == "FIXED" and (
                len(slot["domain"]["entity_ids"]) != 1
                or len(slot["domain"]["entity_types"]) != 1
            ):
                _c2_fail("S2_EVENT_FRAME", "FIXED participant is not singleton")
            if slot["binding_status"] == "COMPETING" and len(
                slot["domain"]["entity_ids"]
            ) < 2:
                _c2_fail("S2_EVENT_FRAME", "COMPETING participant lacks alternatives")
        identity = frame["normalized_identity"]
        if identity["event_type_domain"] != frame["event_type_domain"]:
            _c2_fail("S2_EVENT_FRAME", "event type and identity domains differ")
        role_fields = {
            "actor_slot_ids": "ACTOR",
            "target_slot_ids": "TARGET",
            "anatomical_site_slot_ids": "LOCATION",
        }
        used_dimensions: list[set[str]] = []
        for field, role in role_fields.items():
            values = set(identity[field])
            used_dimensions.append(values)
            if any(slots.get(slot_id, {}).get("semantic_role") != role for slot_id in values):
                _c2_fail("S2_EVENT_FRAME", "identity references a wrong-role slot")
        method_values = (
            {identity["method_slot_id"]} if identity["method_slot_id"] else set()
        )
        used_dimensions.append(method_values)
        if method_values and any(
            slots.get(slot_id, {}).get("semantic_role") != "METHOD"
            for slot_id in method_values
        ):
            _c2_fail("S2_EVENT_FRAME", "identity method is not a METHOD slot")
        if any(
            left.intersection(right)
            for index, left in enumerate(used_dimensions)
            for right in used_dimensions[index + 1 :]
        ):
            _c2_fail("S2_EVENT_FRAME", "one slot is reused across identity dimensions")
        if any(
            specimen_id not in specimen_slots
            for specimen_id in identity["specimen_slot_ids"]
        ):
            _c2_fail("S2_EVENT_FRAME", "identity has dangling specimen slot")
        diagnostic = "DIAGNOSTIC_FINDING" in frame["event_type_domain"]
        binding = frame["diagnostic_binding"]
        if diagnostic != (binding is not None):
            _c2_fail("S2_EVENT_FRAME", "diagnostic binding nullability mismatch")
        if binding is not None:
            if (
                binding["method_slot_id"] != identity["method_slot_id"]
                or binding["target_slot_ids"] != identity["target_slot_ids"]
                or binding["specimen_slot_id"] not in identity["specimen_slot_ids"]
                or slots[binding["method_slot_id"]]["semantic_role"] != "METHOD"
                or any(slots[target]["semantic_role"] != "TARGET" for target in binding["target_slot_ids"])
            ):
                _c2_fail("S2_EVENT_FRAME", "diagnostic components do not share one frame")
        if any(
            source_id not in ast_nodes
            for source_id in frame["assertion"]["governing_ast_node_ids"]
        ) or any(
            marker_id not in marker_ids for marker_id in frame["assertion"]["marker_ids"]
        ):
            _c2_fail("S2_EVENT_FRAME", "assertion has dangling AST authority")

    text = normalized["normalized_query_text"]
    for specimen in specimen_slots.values():
        for span in specimen["source_spans"]:
            if text[span["start_char"] : span["end_char"]] != span["text"]:
                _c2_fail("S2_EVENT_FRAME", "specimen span is not an exact request slice")
            if not any(
                source_id in mentions
                and mentions[source_id]["source_span"]["start_char"] <= span["start_char"]
                and span["end_char"] <= mentions[source_id]["source_span"]["end_char"]
                for source_id in specimen["source_ids"]
            ):
                _c2_fail("S2_EVENT_FRAME", "specimen span lacks mention grounding")

    if require_compiler_projection:
        expected = _build_event_frame(normalized, ast, root)
        if canonical_bytes(event_frame) != canonical_bytes(expected):
            _c2_fail("S2_EVENT_FRAME", "output differs from complete deterministic projection")


def compile_event_frame(
    normalized: dict[str, Any], ast: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    """Compile validated S1 authority into S2 and stop before constraint solving."""
    try:
        validate_schema(normalized, NORMALIZED_REQUEST_SCHEMA_PATH, root)
        validate_c1_clause_ast(normalized, ast, root)
    except (SchemaValidationError, C1ValidationError, KeyError, TypeError) as exc:
        _c2_fail("S2_EVENT_FRAME", f"invalid S1 input: {exc}")
    event_frame = _build_event_frame(normalized, ast, root)
    validate_c2_event_frame(normalized, ast, event_frame, root)
    validate_c2_stop_boundary(event_frame)
    return event_frame


def validate_c2_stop_boundary(value: dict[str, Any]) -> None:
    prohibited_keys = {
        "typed_constraint_result",
        "selected_solution",
        "query_ir",
        "queryir",
        "retrieval_result",
        "model_response",
    }
    pending: list[Any] = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            overlap = prohibited_keys.intersection(item)
            if overlap:
                _c2_fail(
                    "C2_STOP_BOUNDARY",
                    f"prohibited downstream object keys: {sorted(overlap)}",
                )
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def compile_c2(request: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Run the authorized C2 atom and stop at a validated Event Frame object."""
    normalized = normalize_request(request, root)
    ast = compile_clause_ast(normalized, root)
    event_frame = compile_event_frame(normalized, ast, root)
    result = {
        "implemented_stages": list(C2_IMPLEMENTED_STAGES),
        "terminal_stage": C2_TERMINAL_STAGE,
        "normalized_request": normalized,
        "normalized_request_sha256": canonical_sha256(normalized),
        "clause_ast": ast,
        "clause_ast_sha256": canonical_sha256(ast),
        "event_frame": event_frame,
        "event_frame_sha256": canonical_sha256(event_frame),
    }
    validate_c2_stop_boundary(result)
    return result


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    text: str

    def public(self) -> dict[str, Any]:
        return {"start_char": self.start, "end_char": self.end, "text": self.text}


@dataclass(frozen=True)
class ClauseSpec:
    clause_id: str
    order: int
    span: Span
    operator: str
    parent_id: str | None
    alternative_group_id: str | None

    def public(self) -> dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "order": self.order,
            "source_span": self.span.public(),
            "discourse_operator": self.operator,
            "parent_clause_id": self.parent_id,
            "alternative_group_id": self.alternative_group_id,
        }


def _iter_occurrences(text: str, term: str) -> Iterator[tuple[int, int]]:
    if not term:
        return
    lower = text.lower()
    needle = term.lower()
    start = 0
    while True:
        index = lower.find(needle, start)
        if index < 0:
            break
        yield index, index + len(term)
        start = index + max(1, len(term))


def _span(text: str, start: int, end: int) -> Span:
    return Span(start, end, text[start:end])


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def _load_configuration(root: Path) -> dict[str, Any]:
    return _read_yaml(root / CONFIG_PATH)


def _entity_aliases(
    index: p9b1.RetrievalIndex, config: dict[str, Any]
) -> dict[str, tuple[str, ...]]:
    extensions = config.get("entity_alias_extensions", {})
    result: dict[str, tuple[str, ...]] = {}
    for entity_id, entity in index.entities.items():
        values = {
            str(entity.get("name_zh", "")).strip(),
            *(str(item).strip() for item in entity.get("aliases", [])),
            *(str(item).strip() for item in extensions.get(entity_id, [])),
        }
        values.discard("")
        result[entity_id] = tuple(sorted(values, key=lambda item: (-len(item), item)))
    return result


def _clause_specs(query: str, config: dict[str, Any]) -> list[ClauseSpec]:
    chunks: list[Span] = []
    start = 0
    for match in _CLAUSE_SPLIT_RE.finditer(query):
        if start < match.start() and query[start:match.start()].strip():
            left = start
            right = match.start()
            while left < right and query[left].isspace():
                left += 1
            while right > left and query[right - 1].isspace():
                right -= 1
            chunks.append(_span(query, left, right))
        start = match.end()
    if start < len(query) and query[start:].strip():
        left, right = start, len(query)
        while left < right and query[left].isspace():
            left += 1
        while right > left and query[right - 1].isspace():
            right -= 1
        chunks.append(_span(query, left, right))
    if not chunks:
        chunks = [_span(query, 0, len(query))]

    # Preserve an auditable ROOT for a material OR and add concrete branch
    # clauses.  A lexical "or" is never resolved silently.
    if len(chunks) == 1:
        chunk = chunks[0]
        connectors = sorted(config["discourse"]["or"], key=len, reverse=True)
        split_match: tuple[int, int] | None = None
        for connector in connectors:
            for left, right in _iter_occurrences(chunk.text, connector):
                absolute_left = chunk.start + left
                absolute_right = chunk.start + right
                if connector == "或" and query[absolute_right:absolute_right + 4].startswith("未充分"):
                    continue
                if left >= 2 and len(chunk.text) - right >= 2:
                    split_match = (absolute_left, absolute_right)
                    break
            if split_match:
                break
        if split_match:
            left_end, right_start = split_match
            left_start = chunk.start
            while left_start < left_end and query[left_start].isspace():
                left_start += 1
            right_end = chunk.end
            while right_start < right_end and query[right_start].isspace():
                right_start += 1
            while right_end > right_start and query[right_end - 1].isspace():
                right_end -= 1
            return [
                ClauseSpec("C01", 1, chunk, "ROOT", None, None),
                ClauseSpec("C02", 2, _span(query, left_start, left_end), "OR", "C01", "ALT01"),
                ClauseSpec("C03", 3, _span(query, right_start, right_end), "OR", "C01", "ALT01"),
            ]

    result: list[ClauseSpec] = []
    alt_counter = 1
    for index, chunk in enumerate(chunks, 1):
        text = chunk.text
        operator = "ROOT" if index == 1 else "AND"
        parent = None if index == 1 else "C01"
        alt: str | None = None
        if index > 1 and _contains_any(text, config["discourse"]["condition"]):
            operator = "CONDITION"
        elif index > 1 and _contains_any(text, config["discourse"]["override"]):
            operator = "OVERRIDE"
        elif index > 1 and _contains_any(text, config["discourse"]["contrast"]):
            operator = "CONTRAST"
        if index > 1 and _contains_any(text, config["discourse"]["or"]):
            operator = "OR"
            alt = f"ALT{alt_counter:02d}"
            alt_counter += 1
        result.append(ClauseSpec(f"C{index:02d}", index, chunk, operator, parent, alt))
    return result


def _clause_for_span(clauses: list[ClauseSpec], span: Span) -> ClauseSpec:
    matches = [
        clause for clause in clauses
        if clause.span.start <= span.start and span.end <= clause.span.end
    ]
    return min(matches, key=lambda item: item.span.end - item.span.start) if matches else clauses[0]


def _scope_window(query: str, span: Span, radius: int = 18) -> str:
    return query[max(0, span.start - radius):min(len(query), span.end + radius)]


def _assertion_status(
    query: str, span: Span, clause: ClauseSpec, config: dict[str, Any]
) -> str:
    window = _scope_window(query, span)
    if clause.operator == "CONDITION" or _contains_any(window, config["discourse"]["hypothetical"]):
        return "HYPOTHETICAL"
    if _contains_any(window, config["discourse"]["exclusion"]):
        return "EXCLUDED"
    # Negated diagnostic findings are represented at event polarity; the method
    # mention itself remains affirmed.  Other explicitly negated entities do not.
    if _contains_any(window, config["polarity"]["negative"]):
        return "AFFIRMED"
    return "AFFIRMED"


def _temporal_scope(
    query: str, span: Span, config: dict[str, Any]
) -> str:
    window = _scope_window(query, span, 24)
    for scope, terms in (
        ("HISTORICAL", config["temporal"]["historical"]),
        ("CURRENT", config["temporal"]["current"]),
        ("FUTURE", config["temporal"]["future"]),
    ):
        if _contains_any(window, terms):
            return scope
    return "GENERAL"


def _mention_objects(
    request: dict[str, Any], clauses: list[ClauseSpec], index: p9b1.RetrievalIndex,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    query = request["query_text"]
    candidates: list[tuple[int, int, str]] = []
    for entity_id, aliases in _entity_aliases(index, config).items():
        for alias in aliases:
            for start, end in _iter_occurrences(query, alias):
                candidates.append((start, end, entity_id))
    # Longest alias wins only for the same entity/span overlap; semantically
    # distinct nested entities are retained when their spans differ.
    unique: dict[tuple[int, int, str], tuple[int, int, str]] = {item: item for item in candidates}
    by_length = sorted(unique, key=lambda item: (-(item[1] - item[0]), item[0], item[2]))
    selected: list[tuple[int, int, str]] = []
    for candidate in by_length:
        start, end, _ = candidate
        if any(not (end <= kept_start or kept_end <= start) for kept_start, kept_end, _ in selected):
            continue
        selected.append(candidate)
    ordered = sorted(selected, key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
    result: list[dict[str, Any]] = []
    for number, (start, end, entity_id) in enumerate(ordered, 1):
        span = _span(query, start, end)
        clause = _clause_for_span(clauses, span)
        result.append({
            "mention_id": f"M{number:02d}",
            "clause_id": clause.clause_id,
            "source_span": span.public(),
            "entity_id": entity_id,
            "entity_type": index.entities[entity_id]["entity_type"],
            "assertion_status": _assertion_status(query, span, clause, config),
            "temporal_scope": _temporal_scope(query, span, config),
            "reference_ids": [],
        })
    return result


def _mentions_by_entity(mentions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for mention in mentions:
        result.setdefault(mention["entity_id"], []).append(mention)
    return result


def _event_span(query: str, clause: ClauseSpec, bound: list[dict[str, Any]]) -> Span:
    if not bound:
        return clause.span
    start = min(item["source_span"]["start_char"] for item in bound)
    end = max(item["source_span"]["end_char"] for item in bound)
    return _span(query, start, end)


def _diagnostic_polarity(text: str, config: dict[str, Any]) -> str:
    lowered = text.lower()
    if any(term.lower() in lowered for term in config["polarity"]["double_negative_prefix"]):
        return "POSITIVE"
    negative_positions = [
        lowered.find(term.lower()) for term in config["polarity"]["negative"]
        if term.lower() in lowered
    ]
    positive_positions = [
        lowered.find(term.lower()) for term in config["polarity"]["positive"]
        if term.lower() in lowered
    ]
    if negative_positions and (not positive_positions or min(negative_positions) <= min(positive_positions)):
        return "NEGATIVE"
    if positive_positions:
        return "POSITIVE"
    return "UNSPECIFIED"


def _first_mentions_of_type(
    mentions: list[dict[str, Any]], entity_type: str, clause_id: str | None = None
) -> list[dict[str, Any]]:
    return [
        item for item in mentions
        if item["entity_type"] == entity_type
        and (clause_id is None or item["clause_id"] == clause_id)
    ]


def _event_objects(
    request: dict[str, Any], clauses: list[ClauseSpec], mentions: list[dict[str, Any]],
    index: p9b1.RetrievalIndex, config: dict[str, Any], mapping: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    query = request["query_text"]
    events: list[dict[str, Any]] = []
    ambiguities: list[dict[str, Any]] = []
    event_no = 1

    def add_event(
        event_type: str, clause: ClauseSpec, bound: list[dict[str, Any]],
        actors: list[str], target: str | None, *, method: str | None = None,
        specimen: str = "NOT_APPLICABLE", polarity: str = "NOT_APPLICABLE",
        status: str = "AFFIRMED", temporal: str | None = None,
    ) -> None:
        nonlocal event_no
        span = _event_span(query, clause, bound)
        events.append({
            "event_id": f"E{event_no:02d}",
            "clause_id": clause.clause_id,
            "source_span": span.public(),
            "event_type": event_type,
            "assertion_status": status,
            "temporal_scope": temporal or _temporal_scope(query, span, config),
            "actor_entity_ids": sorted(set(actors)),
            "method_entity_id": method,
            "specimen_code": specimen,
            "target_entity_id": target,
            "finding_polarity": polarity,
            "mention_ids": sorted({item["mention_id"] for item in bound}),
            "reference_ids": [],
        })
        event_no += 1

    method_to_specimen = {
        "diagnostic.stool_egg_microscopy": "STOOL",
        "diagnostic.duodenal_fluid_egg_microscopy": "DUODENAL_FLUID",
        "diagnostic.biliary_imaging": "NOT_APPLICABLE",
    }
    for clause in clauses:
        clause_mentions = [item for item in mentions if item["clause_id"] == clause.clause_id]
        methods = [item for item in clause_mentions if item["entity_type"] == "diagnostic_method"]
        targets = [item for item in clause_mentions if item["entity_type"] in {"life_cycle_stage", "pathological_process"}]
        disease = [item for item in clause_mentions if item["entity_type"] == "disease"]
        hosts = [item for item in clause_mentions if item["entity_type"] == "host"]
        for method in methods:
            method_start = method["source_span"]["start_char"]
            method_end = method["source_span"]["end_char"]
            window = query[
                max(clause.span.start, method_start - 20):
                min(clause.span.end, method_end + 20)
            ]
            polarity = _diagnostic_polarity(window, config)
            event_status = "HYPOTHETICAL" if (
                clause.operator == "CONDITION"
                or _contains_any(clause.span.text, config["discourse"]["hypothetical"])
            ) else (
                "EXCLUDED" if _contains_any(clause.span.text, config["discourse"]["exclusion"])
                else "AFFIRMED"
            )
            bound = [method, *targets[:1], *disease[:1], *hosts[:1]]
            actor_ids = [item["entity_id"] for item in [*disease[:1], *targets[:1], *hosts[:1]]]
            if polarity == "UNSPECIFIED" and _contains_any(clause.span.text, ("结果", "检出", "阴性", "阳性")):
                ambiguity_no = len(ambiguities) + 1
                ambiguities.append({
                    "ambiguity_id": f"A{ambiguity_no:02d}",
                    "ambiguity_type": "FINDING_POLARITY",
                    "source_spans": [clause.span.public()],
                    "affected_ids": [f"E{event_no:02d}"],
                    "candidate_options": [
                        {"option_id": f"OPT{ambiguity_no * 2 - 1:02d}", "option_kind": "FINDING_POLARITY", "finding_polarity": "POSITIVE"},
                        {"option_id": f"OPT{ambiguity_no * 2:02d}", "option_kind": "FINDING_POLARITY", "finding_polarity": "NEGATIVE"},
                    ],
                    "resolution_status": "UNRESOLVED",
                })
            add_event(
                "DIAGNOSTIC_FINDING", clause, bound, actor_ids,
                targets[0]["entity_id"] if targets else None,
                method=method["entity_id"], specimen=method_to_specimen[method["entity_id"]],
                polarity=polarity, status=event_status,
            )

        clause_text = clause.span.text
        present_ids = {item["entity_id"] for item in clause_mentions}
        present_types = {item["entity_type"] for item in clause_mentions}
        predicate_cues = {
            predicate for predicate, cues in config["predicate_cues"].items()
            if _contains_any(clause_text, cues)
        }
        event_types: set[str] = set()
        if (
            predicate_cues & {"has_diagnostic_clue", "risk_increased_by", "transmitted_via"}
            or _contains_any(clause_text, config["role_cues"]["epidemiologic_exposure_clue"])
        ) and (
            "behavior" in present_types
            or _contains_any(clause_text, config["role_cues"]["epidemiologic_exposure_clue"])
        ):
            event_types.add("EXPOSURE")
        if predicate_cues & {"develops_into", "has_life_cycle_stage"}:
            event_types.add("DEVELOPMENT")
        if predicate_cues & {"has_definitive_host", "has_first_intermediate_host", "has_second_intermediate_host", "has_reservoir_host"}:
            event_types.add("HOST_ROLE")
        if predicate_cues & {"transmitted_via", "infective_stage_for"} and _contains_any(clause_text, ("摄入", "食入", "吃", "生食", "经口")):
            event_types.add("INGESTION")
        if "sheds_stage" in predicate_cues:
            event_types.add("SHEDDING")
        if predicate_cues & {"present_in_environment", "transmission_supported_by"}:
            event_types.add("ENVIRONMENT_PRESENCE")
        if predicate_cues & {"infects", "causes"}:
            event_types.add("INFECTION")
        if "parasitizes_site" in predicate_cues:
            event_types.add("PARASITISM")
        if predicate_cues & {"pathogenic_stage_for", "has_pathological_process", "occurs_in", "manifests_as", "has_complication", "epidemiologically_associated_with"}:
            event_types.add("PATHOLOGICAL_PROCESS")
        if "treated_by" in predicate_cues:
            event_types.add("TREATMENT")
        if predicate_cues & {"controlled_by", "targets"} or "intervention" in present_types:
            event_types.add("CONTROL")
        if "classified_as" in predicate_cues:
            event_types.add("HAZARD_CLASSIFICATION")
        if _contains_any(clause_text, config["topic_cues"]["source_traceability"]):
            event_types.add("SOURCE_TRACEABILITY")

        for event_type in sorted(event_types):
            if event_type == "DIAGNOSTIC_FINDING":
                continue
            rule = mapping["event_mapping"][event_type]
            actors = [item for item in clause_mentions if item["entity_type"] in rule["allowed_actor_types"]]
            targets_allowed = rule.get("allowed_target_types", [])
            targets2 = [item for item in clause_mentions if item["entity_type"] in targets_allowed]
            if event_type in {"CONTROL", "TREATMENT", "HAZARD_CLASSIFICATION"}:
                if event_type == "CONTROL":
                    actors = [
                        item for item in clause_mentions
                        if item["entity_type"] in {"parasite", "disease"}
                    ]
                    targets2 = [item for item in clause_mentions if item["entity_type"] in {"intervention", "institution_policy"}]
                elif event_type == "TREATMENT":
                    targets2 = [item for item in clause_mentions if item["entity_type"] == "treatment"]
                else:
                    targets2 = [item for item in clause_mentions if item["entity_type"] == "hazard_classification"]
            elif event_type == "HOST_ROLE":
                targets2 = [item for item in clause_mentions if item["entity_type"] == "host"]
            if not actors and event_type == "DEVELOPMENT":
                actors = [item for item in clause_mentions if item["entity_type"] == "life_cycle_stage"][:1]
            bound = list(dict.fromkeys(item["mention_id"] for item in [*actors, *targets2]))
            bound_mentions = [next(item for item in mentions if item["mention_id"] == mid) for mid in bound]
            if not bound_mentions:
                continue
            status = "HYPOTHETICAL" if (
                clause.operator == "CONDITION"
                or _contains_any(clause_text, config["discourse"]["hypothetical"])
            ) else (
                "EXCLUDED" if _contains_any(clause_text, config["discourse"]["exclusion"]) else "AFFIRMED"
            )
            # Each material target is its own normalized event.  Combining two
            # interventions or stages into one event would make polarity,
            # exclusion and later override scope impossible to audit.
            event_targets = targets2 or [None]
            for target_mention in event_targets:
                local_bound = [*actors]
                if target_mention is not None:
                    local_bound.append(target_mention)
                if not local_bound:
                    continue
                add_event(
                    event_type, clause, local_bound,
                    [item["entity_id"] for item in actors],
                    target_mention["entity_id"] if target_mention else None,
                    status=status,
                )

    return events, ambiguities


def _resolve_event_overrides(
    clauses: list[ClauseSpec], events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Resolve only an explicit later event with the same normalized identity."""
    clause_by_id = {item.clause_id: item for item in clauses}
    results: list[dict[str, Any]] = []

    def identity(event: dict[str, Any]) -> tuple[Any, ...]:
        return (
            event["event_type"],
            tuple(event["actor_entity_ids"]),
            event["method_entity_id"],
            event["specimen_code"],
            event["target_entity_id"],
        )

    for later_index, later in enumerate(events):
        later_clause = clause_by_id[later["clause_id"]]
        if later_clause.operator != "OVERRIDE":
            continue
        for earlier in reversed(events[:later_index]):
            if identity(earlier) != identity(later):
                continue
            material_conflict = (
                earlier["finding_polarity"] != later["finding_polarity"]
                or earlier["assertion_status"] != later["assertion_status"]
            )
            if not material_conflict:
                continue
            results.append({
                "override_id": f"OVR{len(results) + 1:02d}",
                "override_clause_id": later["clause_id"],
                "earlier_event_id": earlier["event_id"],
                "later_event_id": later["event_id"],
                "same_normalized_event_identity": True,
                "resolution_status": "RESOLVED",
            })
            break
    return results


def _selector(entity_ids: Iterable[str], entity_types: Iterable[str]) -> dict[str, Any]:
    return {
        "entity_ids": sorted(set(entity_ids)),
        "entity_types": sorted(set(entity_types)),
    }


def _event_participants(
    event: dict[str, Any], mentions_by_id: dict[str, dict[str, Any]], token: str
) -> tuple[set[str], set[str]]:
    entity_ids: set[str] = set()
    entity_types: set[str] = set()
    if token == "method_entity_id" and event["method_entity_id"]:
        entity_ids.add(event["method_entity_id"])
        entity_types.add("diagnostic_method")
        return entity_ids, entity_types
    formal_types = {
        "parasite", "life_cycle_stage", "host", "disease", "anatomical_site",
        "pathological_process", "clinical_manifestation", "diagnostic_method",
        "treatment", "intervention", "behavior", "environment",
        "institution_policy", "hazard_classification",
    }
    if token not in formal_types:
        return entity_ids, entity_types
    participant_ids = set(event["actor_entity_ids"])
    if event["target_entity_id"]:
        participant_ids.add(event["target_entity_id"])
    if event["method_entity_id"]:
        participant_ids.add(event["method_entity_id"])
    for mention_id in event["mention_ids"]:
        participant_ids.add(mentions_by_id[mention_id]["entity_id"])
    for mention in mentions_by_id.values():
        if mention["entity_id"] in participant_ids and mention["entity_type"] == token:
            entity_ids.add(mention["entity_id"])
    if entity_ids:
        entity_types.add(token)
    return entity_ids, entity_types


def _relation_intents(
    request: dict[str, Any], clauses: list[ClauseSpec], mentions: list[dict[str, Any]],
    events: list[dict[str, Any]], config: dict[str, Any], mapping: dict[str, Any],
    superseded_event_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    query = request["query_text"]
    mentions_by_id = {item["mention_id"]: item for item in mentions}
    relations: list[dict[str, Any]] = []
    prohibitions: list[dict[str, Any]] = []

    def add_relation(
        predicate: str, clause: ClauseSpec, basis: list[str], subject: dict[str, Any],
        obj: dict[str, Any], mode: str = "EVENT_DERIVED",
        policy: str = "REQUIRED",
    ) -> None:
        if not (subject["entity_ids"] or subject["entity_types"]):
            return
        if not (obj["entity_ids"] or obj["entity_types"]):
            return
        key = (predicate, canonical_sha256(subject), canonical_sha256(obj), tuple(sorted(basis)), policy)
        for item in relations:
            current = (
                item["predicate"], canonical_sha256(item["subject_selector"]),
                canonical_sha256(item["object_selector"]), tuple(sorted(item["basis_ids"])),
                item["activation_policy"],
            )
            if current == key:
                return
        relations.append({
            "intent_id": f"R{len(relations) + 1:02d}",
            "clause_ids": [clause.clause_id],
            "source_spans": [clause.span.public()],
            "predicate": predicate,
            "subject_selector": subject,
            "object_selector": obj,
            "assertion_status": "AFFIRMED",
            "temporal_scope": _temporal_scope(query, clause.span, config),
            "activation_policy": policy,
            "derivation_mode": mode,
            "basis_ids": sorted(set(basis)),
        })

    superseded_event_ids = superseded_event_ids or set()
    for event in events:
        if event["event_id"] in superseded_event_ids:
            continue
        clause = next(item for item in clauses if item.clause_id == event["clause_id"])
        event_rule = mapping["event_mapping"][event["event_type"]]
        predicates = event_rule.get("predicates", {})
        expressed = {
            predicate for predicate, cues in config["predicate_cues"].items()
            if _contains_any(clause.span.text, cues)
        }
        # Diagnostic positive/negative event semantics are explicit: positive
        # may license its requested relation; negative creates no affirmation.
        executable = event["assertion_status"] == "AFFIRMED" and (
            event["event_type"] != "DIAGNOSTIC_FINDING"
            or event["finding_polarity"] == "POSITIVE"
        )
        selected_predicates = set(predicates) & expressed
        if event["event_type"] == "EXPOSURE" and _contains_any(
            clause.span.text, ("证据", "线索", "诊断", "意义", "说明")
        ):
            selected_predicates.add("has_diagnostic_clue")
        if event["event_type"] == "CONTROL" and event["target_entity_id"]:
            target_type = next(
                (
                    mention["entity_type"] for mention in mentions_by_id.values()
                    if mention["entity_id"] == event["target_entity_id"]
                ),
                None,
            )
            if target_type in {"intervention", "institution_policy"}:
                selected_predicates.add("controlled_by")
        if event["event_type"] == "DIAGNOSTIC_FINDING" and not selected_predicates:
            selected_predicates = {"has_diagnostic_clue"}
            if event["finding_polarity"] == "POSITIVE" and event["method_entity_id"] != "diagnostic.biliary_imaging":
                selected_predicates.add("diagnosed_by")
        if (
            event["event_type"] == "DIAGNOSTIC_FINDING"
            and event["method_entity_id"] == "diagnostic.biliary_imaging"
            and not any(
                mentions_by_id[mid]["entity_type"] == "disease"
                for mid in event["mention_ids"]
            )
        ):
            selected_predicates.discard("has_diagnostic_clue")
        for predicate in sorted(selected_predicates):
            derivation = predicates[predicate]
            subject_ids: set[str] = set()
            subject_types: set[str] = set()
            object_ids: set[str] = set()
            object_types: set[str] = set()
            for token in derivation["subject_from"]:
                ids, types = _event_participants(event, mentions_by_id, token)
                subject_ids.update(ids)
                subject_types.update(types)
            for token in derivation["object_from"]:
                ids, types = _event_participants(event, mentions_by_id, token)
                object_ids.update(ids)
                object_types.update(types)
            matrix = mapping["predicate_type_matrix"][predicate]
            if not subject_ids:
                explicit = [
                    m for m in mentions if m["clause_id"] == clause.clause_id
                    and m["entity_type"] in matrix["subject_types"]
                ]
                subject_ids.update(m["entity_id"] for m in explicit)
                subject_types.update(m["entity_type"] for m in explicit)
            if not object_ids:
                explicit = [
                    m for m in mentions if m["clause_id"] == clause.clause_id
                    and m["entity_type"] in matrix["object_types"]
                ]
                object_ids.update(m["entity_id"] for m in explicit)
                object_types.update(m["entity_type"] for m in explicit)
            open_question = _contains_any(
                clause.span.text,
                ("什么", "哪些", "谁", "哪种", "哪一", "如何判断", "能否确证", "是否确诊", "用于确证", "诊断证据", "确证证据"),
            ) or _contains_any(
                query,
                ("什么", "哪些", "谁", "哪种", "哪一", "如何判断", "能否确证", "是否确诊", "用于确证", "诊断证据", "确证证据"),
            )
            if not subject_ids and open_question:
                subject_types.update(matrix["subject_types"])
            if not object_ids and open_question:
                object_types.update(matrix["object_types"])
            subject = _selector(subject_ids, subject_types)
            obj = _selector(object_ids, object_types)
            if executable:
                add_relation(predicate, clause, [event["event_id"]], subject, obj)
            elif subject["entity_ids"] or subject["entity_types"]:
                if obj["entity_ids"] or obj["entity_types"]:
                    prohibitions.append({
                        "prohibition_id": f"F{len(prohibitions) + 1:02d}",
                        "clause_ids": [clause.clause_id],
                        "source_spans": [clause.span.public()],
                        "predicate": predicate,
                        "subject_selector": subject,
                        "object_selector": obj,
                        "reason": (
                            "HYPOTHETICAL_ONLY" if event["assertion_status"] == "HYPOTHETICAL"
                            else "EXPLICIT_EXCLUSION" if event["assertion_status"] == "EXCLUDED"
                            else "EXPLICIT_NEGATION"
                        ),
                        "basis_ids": [event["event_id"]],
                    })

    # Direct formal questions with an unknown counterpart use open type slots.
    for clause in clauses:
        clause_mentions = [m for m in mentions if m["clause_id"] == clause.clause_id and m["assertion_status"] == "AFFIRMED"]
        for predicate, cues in config["predicate_cues"].items():
            if not _contains_any(clause.span.text, cues):
                continue
            if any(r["predicate"] == predicate and clause.clause_id in r["clause_ids"] for r in relations):
                continue
            matrix = mapping["predicate_type_matrix"][predicate]
            subject_mentions = [m for m in clause_mentions if m["entity_type"] in matrix["subject_types"]]
            object_mentions = [m for m in clause_mentions if m["entity_type"] in matrix["object_types"]]
            if predicate == "has_diagnostic_clue" and not subject_mentions and any(
                m["entity_type"] in matrix["subject_types"] for m in mentions
            ):
                # The cross-clause evidence binder below will produce the
                # concrete relation with both auditable mentions.
                continue
            subject = _selector(
                (m["entity_id"] for m in subject_mentions),
                () if subject_mentions else matrix["subject_types"],
            )
            obj = _selector(
                (m["entity_id"] for m in object_mentions),
                () if object_mentions else matrix["object_types"],
            )
            basis = [m["mention_id"] for m in [*subject_mentions, *object_mentions]]
            open_relation_request = _contains_any(
                clause.span.text,
                ("什么", "哪些", "哪条", "哪类", "如何", "关系", "路径", "链"),
            )
            if not basis and open_relation_request and clause_mentions:
                basis = [m["mention_id"] for m in clause_mentions]
            if basis:
                add_relation(predicate, clause, basis, subject, obj, "DIRECT_MENTION_DERIVED")

    # Ordered host-event language is normalized through reviewed entity types,
    # not through a frozen question string.  Snail/fish/human roles are fixed
    # by the formal host ontology and are emitted as three directed relations.
    affirmed_hosts = [
        item for item in mentions
        if item["entity_type"] == "host" and item["assertion_status"] == "AFFIRMED"
    ]
    if len(affirmed_hosts) >= 2 and _contains_any(query, ("宿主角色", "各是什么角色", "分别是什么角色", "先后", "最后")):
        host_predicates = {
            "host.freshwater_snails_suitable_for_clonorchis": "has_first_intermediate_host",
            "host.freshwater_fish": "has_second_intermediate_host",
            "host.human": "has_definitive_host",
            "host.domestic_dogs_cats_pigs": "has_reservoir_host",
            "host.piscivorous_mammals": "has_reservoir_host",
        }
        for host in affirmed_hosts:
            predicate = host_predicates.get(host["entity_id"])
            if predicate is None:
                continue
            clause = next(item for item in clauses if item.clause_id == host["clause_id"])
            add_relation(
                predicate, clause, [host["mention_id"]],
                _selector((), ("parasite",)),
                _selector((host["entity_id"],), ()),
                "DIRECT_MENTION_DERIVED",
            )

    # An explicit request for a complete/continuous developmental path may
    # leave individual stages unnamed.  It licenses an open typed edge query,
    # while the graph executor—not the interpreter—selects reviewed edges.
    if (
        "life_cycle" in _topics(query, config, clauses)
        and _contains_any(query, ("完整", "连续", "路径", "链", "发育", "成熟"))
        and not any(item["predicate"] == "develops_into" for item in relations)
    ):
        roots = [
            item for item in mentions
            if item["assertion_status"] == "AFFIRMED"
            and item["entity_type"] in {"host", "life_cycle_stage", "parasite", "anatomical_site"}
        ]
        if roots:
            clause = next(item for item in clauses if item.clause_id == roots[0]["clause_id"])
            add_relation(
                "develops_into", clause, [item["mention_id"] for item in roots],
                _selector((), ("life_cycle_stage",)),
                _selector((), ("life_cycle_stage",)),
                "DIRECT_MENTION_DERIVED",
            )

    # Evidence questions commonly place the exposure/imaging proposition before
    # a comma and the disease/evidence-role question after it.  Bind the exact
    # mentions across those sibling clauses instead of inventing an implicit
    # event participant.
    disease_mentions = [m for m in mentions if m["entity_type"] == "disease" and m["assertion_status"] == "AFFIRMED"]
    clue_mentions = [
        m for m in mentions
        if m["entity_type"] in {"behavior", "diagnostic_method"}
        and m["assertion_status"] == "AFFIRMED"
    ]
    if disease_mentions and clue_mentions and _contains_any(
        query, ("证据", "线索", "辅助", "意义", "说明")
    ):
        existing_pairs = {
            (
                tuple(r["subject_selector"]["entity_ids"]),
                tuple(r["object_selector"]["entity_ids"]),
            )
            for r in relations if r["predicate"] == "has_diagnostic_clue"
        }
        for clue in clue_mentions:
            pair = ((disease_mentions[0]["entity_id"],), (clue["entity_id"],))
            if pair in existing_pairs:
                continue
            clause_ids = sorted(
                {disease_mentions[0]["clause_id"], clue["clause_id"]},
                key=lambda cid: int(cid[1:]),
            )
            bound_clauses = [next(c for c in clauses if c.clause_id == cid) for cid in clause_ids]
            relations.append({
                "intent_id": f"R{len(relations) + 1:02d}",
                "clause_ids": clause_ids,
                "source_spans": [c.span.public() for c in bound_clauses],
                "predicate": "has_diagnostic_clue",
                "subject_selector": _selector((disease_mentions[0]["entity_id"],), ()),
                "object_selector": _selector((clue["entity_id"],), ()),
                "assertion_status": "AFFIRMED",
                "temporal_scope": clue["temporal_scope"],
                "activation_policy": "REQUIRED",
                "derivation_mode": "DIRECT_MENTION_DERIVED",
                "basis_ids": [disease_mentions[0]["mention_id"], clue["mention_id"]],
            })

    # A reviewed clue that is explicitly described as non-confirmatory must
    # carry its pathogen-confirmation comparator.  This rule is closed: it
    # emits only a typed open diagnostic-method slot and never a claim ID.
    nonconfirmatory = _contains_any(
        query,
        (
            "不能单独确诊", "不能作为确证", "不属于确证", "不是确证",
            "只是线索", "仅是线索", "非确证", "辅助线索",
        ),
    )
    if nonconfirmatory:
        clue_relations = [
            item for item in relations
            if item["predicate"] == "has_diagnostic_clue"
        ]
        for clue_relation in clue_relations:
            clause = next(
                item for item in clauses
                if item.clause_id == clue_relation["clause_ids"][0]
            )
            add_relation(
                "diagnosed_by",
                clause,
                clue_relation["basis_ids"],
                clue_relation["subject_selector"],
                _selector((), ("diagnostic_method",)),
                "CLOSED_CONTRAST_DERIVED",
                "REQUIRED_CONTRAST",
            )

    return relations, prohibitions


def _topics(
    query: str, config: dict[str, Any], clauses: list[ClauseSpec] | None = None
) -> list[str]:
    if clauses is None:
        return [
            topic for topic, cues in config["topic_cues"].items()
            if _contains_any(query, cues)
        ]
    activated: list[str] = []
    for topic, cues in config["topic_cues"].items():
        for clause in clauses:
            if not _contains_any(clause.span.text, cues):
                continue
            if (
                clause.operator == "CONDITION"
                or _contains_any(clause.span.text, config["discourse"]["hypothetical"])
                or _contains_any(clause.span.text, config["discourse"]["exclusion"])
            ):
                continue
            activated.append(topic)
            break
    return activated


def _narratives_and_roles(
    request: dict[str, Any], clauses: list[ClauseSpec], mentions: list[dict[str, Any]],
    events: list[dict[str, Any]], relations: list[dict[str, Any]],
    config: dict[str, Any], superseded_event_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    query = request["query_text"]
    topics = _topics(query, config, clauses)
    narratives: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    superseded_event_ids = superseded_event_ids or set()
    affirmed_mentions = [item for item in mentions if item["assertion_status"] == "AFFIRMED"]

    def add_role(namespace: str, value: str, clause: ClauseSpec, basis: list[str], policy: str = "REQUIRED") -> None:
        key = (namespace, value, tuple(sorted(basis)), policy)
        if any((r["role_namespace"], r["role_value"], tuple(sorted(r["basis_ids"])), r["activation_policy"]) == key for r in roles):
            return
        roles.append({
            "role_id": f"Q{len(roles) + 1:02d}",
            "clause_ids": [clause.clause_id],
            "role_namespace": namespace,
            "role_value": value,
            "activation_policy": policy,
            "basis_ids": sorted(set(basis)),
        })

    for topic in topics:
        basis = [item["mention_id"] for item in affirmed_mentions]
        if basis:
            add_role("TOPIC_SCOPE", topic, clauses[0], basis)

    for role_value, cues in config["role_cues"].items():
        if not _contains_any(query, cues):
            continue
        basis_mentions = [
            item for item in affirmed_mentions
            if item["entity_type"] in {"behavior", "diagnostic_method", "disease", "life_cycle_stage"}
        ] or affirmed_mentions
        if not basis_mentions:
            continue
        clause = _clause_for_span(
            clauses,
            Span(
                basis_mentions[0]["source_span"]["start_char"],
                basis_mentions[0]["source_span"]["end_char"],
                basis_mentions[0]["source_span"]["text"],
            ),
        )
        if role_value == "not_confirmatory":
            boundary_value = (
                "imaging_is_not_confirmation"
                if any(item["entity_id"] == "diagnostic.biliary_imaging" for item in basis_mentions)
                else "exposure_is_not_confirmation"
                if any(item["entity_type"] == "behavior" for item in basis_mentions)
                else "diagnostic_clue_is_not_confirmation"
            )
            add_role(
                "SEMANTIC_BOUNDARY", boundary_value, clause,
                [item["mention_id"] for item in basis_mentions],
            )
        else:
            add_role(
                "EVIDENCE_ROLE", role_value, clause,
                [item["mention_id"] for item in basis_mentions],
            )

    nonconfirmatory = any(
        item["role_value"] in {
            "epidemiologic_exposure_clue", "imaging_auxiliary_clue", "not_confirmatory",
        }
        for item in roles
    )
    contrast_relations = [
        item for item in relations
        if item["derivation_mode"] == "CLOSED_CONTRAST_DERIVED"
    ]
    if nonconfirmatory and contrast_relations:
        for relation in contrast_relations:
            clause = next(
                item for item in clauses
                if item.clause_id == relation["clause_ids"][0]
            )
            add_role(
                "EVIDENCE_ROLE", "pathogen_confirmation", clause,
                relation["basis_ids"], "REQUIRED_CONTRAST",
            )

    for relation in relations:
        if relation["predicate"] == "classified_as":
            clause = next(c for c in clauses if c.clause_id == relation["clause_ids"][0])
            add_role(
                "SEMANTIC_BOUNDARY",
                "hazard_class_is_not_individual_certainty",
                clause,
                relation["basis_ids"],
            )
        elif relation["predicate"] in {"treated_by", "controlled_by"} and _contains_any(
            query, ("疗效", "效果", "根除", "必然", "一定", "百分之百", "100%")
        ):
            clause = next(c for c in clauses if c.clause_id == relation["clause_ids"][0])
            add_role(
                "SEMANTIC_BOUNDARY",
                "recommendation_is_not_quantified_effect",
                clause,
                relation["basis_ids"],
            )

    if "morphology" in topics:
        stage_mentions = [item for item in affirmed_mentions if item["entity_type"] == "life_cycle_stage"]
        if stage_mentions:
            clause = _clause_for_span(
                clauses,
                Span(
                    stage_mentions[0]["source_span"]["start_char"],
                    stage_mentions[0]["source_span"]["end_char"],
                    stage_mentions[0]["source_span"]["text"],
                ),
            )
            narratives.append({
                "narrative_intent_id": "N01",
                "clause_ids": [clause.clause_id],
                "source_spans": [clause.span.public()],
                "entity_selector": _selector((m["entity_id"] for m in stage_mentions), ()),
                "topic_scope": "morphology",
                "semantic_role": "narrative_fact",
                "assertion_status": "AFFIRMED",
                "temporal_scope": "GENERAL",
                "activation_policy": "REQUIRED",
                "derivation_mode": "DIRECT_MENTION_DERIVED",
                "basis_ids": [m["mention_id"] for m in stage_mentions],
                "required_anchor_predicates": [],
            })

    diagnostic_events = [
        event for event in events
        if event["event_type"] in {"DIAGNOSTIC_FINDING", "EXPOSURE"}
        and event["assertion_status"] == "AFFIRMED"
        and event["event_id"] not in superseded_event_ids
    ]
    for semantic_role in ("diagnostic_evidence_integration", "diagnostic_confirmation_limit"):
        if "diagnosis" not in topics:
            continue
        anchors = [item for item in relations if item["predicate"] == "has_diagnostic_clue"]
        if not anchors:
            continue
        anchor = anchors[0]
        basis_mentions = [
            item for item in mentions
            if item["mention_id"] in anchor["basis_ids"]
            and item["entity_type"] in {"diagnostic_method", "disease"}
        ]
        if basis_mentions and all(item.startswith("M") for item in anchor["basis_ids"]):
            narratives.append({
                "narrative_intent_id": f"N{len(narratives) + 1:02d}",
                "clause_ids": anchor["clause_ids"],
                "source_spans": anchor["source_spans"],
                "entity_selector": _selector((m["entity_id"] for m in basis_mentions), ()),
                "topic_scope": "diagnosis",
                "semantic_role": semantic_role,
                "assertion_status": "AFFIRMED",
                "temporal_scope": anchor["temporal_scope"],
                "activation_policy": "REQUIRED",
                "derivation_mode": "DIRECT_MENTION_DERIVED",
                "basis_ids": [m["mention_id"] for m in basis_mentions],
                "required_anchor_predicates": ["has_diagnostic_clue"],
            })
            continue
        if not diagnostic_events:
            continue
        event = diagnostic_events[0]
        event_mentions = [
            item for item in mentions if item["mention_id"] in event["mention_ids"]
            and item["entity_type"] in {"diagnostic_method", "disease"}
        ]
        if event_mentions:
            narratives.append({
                "narrative_intent_id": f"N{len(narratives) + 1:02d}",
                "clause_ids": [event["clause_id"]],
                "source_spans": [event["source_span"]],
                "entity_selector": _selector((m["entity_id"] for m in event_mentions), ()),
                "topic_scope": "diagnosis",
                "semantic_role": semantic_role,
                "assertion_status": "AFFIRMED",
                "temporal_scope": event["temporal_scope"],
                "activation_policy": "REQUIRED",
                "derivation_mode": "EVENT_DERIVED",
                "basis_ids": [event["event_id"]],
                "required_anchor_predicates": ["has_diagnostic_clue"],
            })

    return narratives, roles


def _or_ambiguities(
    clauses: list[ClauseSpec], ambiguities: list[dict[str, Any]]
) -> None:
    groups: dict[str, list[ClauseSpec]] = {}
    for clause in clauses:
        if clause.alternative_group_id:
            groups.setdefault(clause.alternative_group_id, []).append(clause)
    for alt, branches in sorted(groups.items()):
        if len(branches) < 2:
            continue
        ambiguity_number = len(ambiguities) + 1
        option_start = sum(len(item["candidate_options"]) for item in ambiguities) + 1
        ambiguities.append({
            "ambiguity_id": f"A{ambiguity_number:02d}",
            "ambiguity_type": "OR_SELECTION",
            "source_spans": [branch.span.public() for branch in branches],
            "affected_ids": [branch.clause_id for branch in branches],
            "candidate_options": [
                {
                    "option_id": f"OPT{option_start + offset:02d}",
                    "option_kind": "OR_BRANCH",
                    "alternative_group_id": alt,
                    "branch_clause_id": branch.clause_id,
                }
                for offset, branch in enumerate(branches)
            ],
            "resolution_status": "UNRESOLVED",
        })


def interpret_request(
    request: dict[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    """Interpret one validated P9-A request as a closed Scoped QueryIR object."""
    p9b1.validate_request(request, root)
    index = p9b1.build_index(root)
    config = _load_configuration(root)
    mapping = _read_yaml(root / MAPPING_PATH)
    clauses = _clause_specs(request["query_text"], config)
    mentions = _mention_objects(request, clauses, index, config)
    events, ambiguities = _event_objects(
        request, clauses, mentions, index, config, mapping
    )
    overrides = _resolve_event_overrides(clauses, events)
    superseded_event_ids = {item["earlier_event_id"] for item in overrides}
    relations, prohibitions = _relation_intents(
        request, clauses, mentions, events, config, mapping, superseded_event_ids
    )
    narratives, roles = _narratives_and_roles(
        request, clauses, mentions, events, relations, config, superseded_event_ids
    )
    _or_ambiguities(clauses, ambiguities)

    if ambiguities:
        status = "AMBIGUOUS"
        relations = []
        narratives = []
        roles = []
    elif not relations and not narratives:
        status = "UNSUPPORTED"
        ambiguities = [{
            "ambiguity_id": "A01",
            "ambiguity_type": "UNSUPPORTED_INTENT",
            "source_spans": [clauses[0].span.public()],
            "affected_ids": [clauses[0].clause_id],
            "candidate_options": [
                {"option_id": "OPT01", "option_kind": "UNSUPPORTED"}
            ],
            "resolution_status": "UNRESOLVED",
        }]
    else:
        status = "VALID"

    configuration_sha = file_sha256(root / CONFIG_PATH)
    query_ir = {
        "query_ir_version": "0.3-candidate",
        "request_id": request["request_id"],
        "request_sha256": canonical_sha256(request),
        "knowledge_version": request["knowledge_version"],
        "span_basis": "REQUEST_QUERY_TEXT_UNICODE_CODEPOINT_ZERO_BASED_HALF_OPEN",
        "interpretation_status": status,
        "producer": {
            **config["producer"],
            "implementation_kind": "DETERMINISTIC",
            "configuration_sha256": configuration_sha,
        },
        "clauses": [item.public() for item in clauses],
        "mentions": mentions,
        "events": events,
        "relation_intents": relations,
        "narrative_intents": narratives,
        "required_roles": roles,
        "forbidden_relation_intents": prohibitions,
        "resolved_references": [],
        "resolved_overrides": overrides,
        "ambiguities": ambiguities,
    }
    return query_ir


def _id_sort_key(value: str) -> tuple[int, int, bytes]:
    match = _ID_RE.match(value)
    if match is None:
        raise ValueError(f"invalid prefixed ID: {value}")
    suffix = match.group("suffix")
    return int(suffix, 10), len(suffix), value.encode("utf-8")


def _ordered_ids(values: Iterable[str]) -> list[str]:
    return sorted(set(values), key=_id_sort_key)


def _failure_result(
    request: dict[str, Any], query_ir: dict[str, Any], fail_codes: Iterable[str],
    *, root: Path,
) -> dict[str, Any]:
    contract = _read_yaml(root / VALIDATOR_CONTRACT_PATH)
    order = {code: index for index, code in enumerate(contract["fail_codes"])}
    codes = sorted(set(fail_codes), key=lambda item: order[item])
    return {
        "schema_version": "0.2-candidate",
        "validation_id": f"SV-{canonical_sha256(query_ir)[:24]}",
        "request_schema_valid": True,
        "request_id": request["request_id"],
        "request_sha256": canonical_sha256(request),
        "query_ir_sha256": canonical_sha256(query_ir),
        "knowledge_version": request["knowledge_version"],
        "query_ir_schema_valid": "QUERY_IR_SCHEMA_INVALID" not in codes,
        "query_ir_interpretation_status": (
            None if "QUERY_IR_SCHEMA_INVALID" in codes else query_ir.get("interpretation_status")
        ),
        "query_ir_schema_sha256": file_sha256(root / QUERY_IR_SCHEMA_PATH),
        "semantic_contract_sha256": file_sha256(root / SEMANTIC_CONTRACT_PATH),
        "semantic_validator_contract_sha256": file_sha256(root / VALIDATOR_CONTRACT_PATH),
        "event_mapping_sha256": file_sha256(root / MAPPING_PATH),
        "result": "FAIL_CLOSED",
        "fail_codes": codes,
        "executable_relation_intent_ids": [],
        "executable_narrative_intent_ids": [],
        "prohibited_relation_intent_ids": _ordered_ids(
            item.get("prohibition_id", "F00") for item in query_ir.get("forbidden_relation_intents", [])
        ),
        "superseded_event_ids": [],
    }


def validate_query_ir(
    request: dict[str, Any], query_ir: dict[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    """Execute the deterministic semantic contract and return its closed result."""
    p9b1.validate_request(request, root)
    fail_codes: list[str] = []
    if query_ir.get("request_id") != request["request_id"] or query_ir.get("request_sha256") != canonical_sha256(request):
        fail_codes.append("REQUEST_HASH_OR_ID_MISMATCH")
    try:
        validate_schema(query_ir, QUERY_IR_SCHEMA_PATH, root)
    except (SchemaValidationError, ValueError):
        fail_codes.append("QUERY_IR_SCHEMA_INVALID")
    if fail_codes:
        result = _failure_result(request, query_ir, fail_codes, root=root)
        validate_schema(result, SEMANTIC_SCHEMA_PATH, root)
        return result

    query = request["query_text"]
    ids: dict[str, dict[str, Any]] = {}
    identifier_fields = {
        "clauses": "clause_id",
        "mentions": "mention_id",
        "events": "event_id",
        "relation_intents": "intent_id",
        "narrative_intents": "narrative_intent_id",
        "required_roles": "role_id",
        "forbidden_relation_intents": "prohibition_id",
        "resolved_references": "reference_id",
        "resolved_overrides": "override_id",
        "ambiguities": "ambiguity_id",
    }
    for collection in (
        "clauses", "mentions", "events", "relation_intents", "narrative_intents",
        "required_roles", "forbidden_relation_intents", "resolved_references",
        "resolved_overrides", "ambiguities",
    ):
        for item in query_ir[collection]:
            identifier = item.get(identifier_fields[collection])
            if identifier and identifier in ids:
                fail_codes.append("DUPLICATE_OR_DANGLING_ID")
            elif identifier:
                ids[identifier] = item

    def check_span(span: dict[str, Any]) -> bool:
        start, end = span["start_char"], span["end_char"]
        return 0 <= start < end <= len(query) and query[start:end] == span["text"]

    for collection in query_ir.values():
        if isinstance(collection, list):
            for item in collection:
                if not isinstance(item, dict):
                    continue
                spans: list[dict[str, Any]] = []
                if "source_span" in item:
                    spans.append(item["source_span"])
                spans.extend(item.get("source_spans", []))
                if "anaphor_span" in item:
                    spans.append(item["anaphor_span"])
                if any(not check_span(span) for span in spans):
                    fail_codes.append("SPAN_MISMATCH")

    clause_ids = {item["clause_id"] for item in query_ir["clauses"]}
    clause_by_id = {item["clause_id"]: item for item in query_ir["clauses"]}
    if len(clause_ids) != len(query_ir["clauses"]):
        fail_codes.append("CLAUSE_GRAPH_INVALID")
    for item in query_ir["clauses"]:
        if item["parent_clause_id"] is not None and item["parent_clause_id"] not in clause_ids:
            fail_codes.append("CLAUSE_GRAPH_INVALID")
    index = p9b1.build_index(root)
    for mention in query_ir["mentions"]:
        entity = index.entities.get(mention["entity_id"])
        if entity is None:
            fail_codes.append("UNKNOWN_OR_UNREVIEWED_ENTITY")
        elif entity["entity_type"] != mention["entity_type"]:
            fail_codes.append("ENTITY_TYPE_MISMATCH")

    mapping = _read_yaml(root / MAPPING_PATH)
    mentions = {item["mention_id"]: item for item in query_ir["mentions"]}
    events = {item["event_id"]: item for item in query_ir["events"]}
    superseded: set[str] = set()
    for override in query_ir["resolved_overrides"]:
        earlier = events.get(override["earlier_event_id"])
        later = events.get(override["later_event_id"])
        clause = clause_by_id.get(override["override_clause_id"])
        if earlier is None or later is None or clause is None:
            fail_codes.append("OVERRIDE_INVALID_OR_AMBIGUOUS")
            continue
        earlier_identity = (
            earlier["event_type"], tuple(earlier["actor_entity_ids"]),
            earlier["method_entity_id"], earlier["specimen_code"],
            earlier["target_entity_id"],
        )
        later_identity = (
            later["event_type"], tuple(later["actor_entity_ids"]),
            later["method_entity_id"], later["specimen_code"],
            later["target_entity_id"],
        )
        if (
            earlier_identity != later_identity
            or later["source_span"]["start_char"] <= earlier["source_span"]["start_char"]
            or clause["discourse_operator"] != "OVERRIDE"
            or (
                earlier["finding_polarity"] == later["finding_polarity"]
                and earlier["assertion_status"] == later["assertion_status"]
            )
        ):
            fail_codes.append("OVERRIDE_INVALID_OR_AMBIGUOUS")
        superseded.add(earlier["event_id"])
    for event in events.values():
        rule = mapping["event_mapping"].get(event["event_type"])
        if rule is None:
            fail_codes.append("EVENT_FIELD_OR_TYPE_MISMATCH")
            continue
        if any(mid not in mentions for mid in event["mention_ids"]):
            fail_codes.append("DUPLICATE_OR_DANGLING_ID")
        clause = clause_by_id.get(event["clause_id"])
        if clause is None or not (
            clause["source_span"]["start_char"] <= event["source_span"]["start_char"]
            and event["source_span"]["end_char"] <= clause["source_span"]["end_char"]
        ):
            fail_codes.append("EVENT_FIELD_OR_TYPE_MISMATCH")
        actor_types = {
            index.entities[entity_id]["entity_type"]
            for entity_id in event["actor_entity_ids"]
            if entity_id in index.entities
        }
        if actor_types - set(rule["allowed_actor_types"]):
            fail_codes.append("EVENT_FIELD_OR_TYPE_MISMATCH")
        if event["target_entity_id"]:
            target = index.entities.get(event["target_entity_id"])
            if target is None or target["entity_type"] not in rule.get("allowed_target_types", []):
                fail_codes.append("EVENT_FIELD_OR_TYPE_MISMATCH")
        if event["event_type"] == "DIAGNOSTIC_FINDING":
            if event["finding_polarity"] not in {"POSITIVE", "NEGATIVE"} and query_ir["interpretation_status"] == "VALID":
                fail_codes.append("EVENT_FIELD_OR_TYPE_MISMATCH")
        elif event["method_entity_id"] is not None or event["specimen_code"] != "NOT_APPLICABLE" or event["finding_polarity"] != "NOT_APPLICABLE":
            fail_codes.append("EVENT_FIELD_OR_TYPE_MISMATCH")

    executable_relations: list[str] = []
    for relation in query_ir["relation_intents"]:
        predicate = relation["predicate"]
        matrix = mapping["predicate_type_matrix"].get(predicate)
        if matrix is None:
            fail_codes.append("UNKNOWN_PREDICATE_OR_ROLE")
            continue
        subject_types = set(relation["subject_selector"]["entity_types"])
        object_types = set(relation["object_selector"]["entity_types"])
        for entity_id in relation["subject_selector"]["entity_ids"]:
            entity = index.entities.get(entity_id)
            if entity is None or entity["entity_type"] not in matrix["subject_types"]:
                fail_codes.append("RELATION_DIRECTION_OR_SELECTOR_INVALID")
        for entity_id in relation["object_selector"]["entity_ids"]:
            entity = index.entities.get(entity_id)
            if entity is None or entity["entity_type"] not in matrix["object_types"]:
                fail_codes.append("RELATION_DIRECTION_OR_SELECTOR_INVALID")
        if subject_types - set(matrix["subject_types"]) or object_types - set(matrix["object_types"]):
            fail_codes.append("RELATION_DIRECTION_OR_SELECTOR_INVALID")
        for basis in relation["basis_ids"]:
            if basis.startswith("E"):
                event = events.get(basis)
                if event is None:
                    fail_codes.append("DUPLICATE_OR_DANGLING_ID")
                elif predicate not in mapping["event_mapping"][event["event_type"]].get("predicates", {}):
                    fail_codes.append("EVENT_INTENT_DERIVATION_MISMATCH")
                elif event["assertion_status"] != "AFFIRMED" or (
                    event["event_type"] == "DIAGNOSTIC_FINDING" and event["finding_polarity"] != "POSITIVE"
                ):
                    fail_codes.append("NO_AFFIRMED_SEMANTIC_ROOT")
                elif event["event_id"] in superseded:
                    fail_codes.append("NO_AFFIRMED_SEMANTIC_ROOT")
            elif basis.startswith("M"):
                mention = mentions.get(basis)
                if mention is None:
                    fail_codes.append("DUPLICATE_OR_DANGLING_ID")
                elif mention["assertion_status"] != "AFFIRMED":
                    fail_codes.append("NO_AFFIRMED_SEMANTIC_ROOT")
        executable_relations.append(relation["intent_id"])

    role_catalog = mapping["role_catalog"]
    contrast_relation_bases = {
        tuple(item["basis_ids"])
        for item in query_ir["relation_intents"]
        if item["derivation_mode"] == "CLOSED_CONTRAST_DERIVED"
        and item["activation_policy"] == "REQUIRED_CONTRAST"
    }
    for role in query_ir["required_roles"]:
        catalog = role_catalog.get(role["role_namespace"], {})
        if role["role_value"] not in catalog:
            fail_codes.append("UNKNOWN_PREDICATE_OR_ROLE")
        if role["activation_policy"] == "REQUIRED_CONTRAST" and tuple(role["basis_ids"]) not in contrast_relation_bases:
            fail_codes.append("ROLE_AUTHORITY_OR_CONTRAST_INVALID")
        for basis in role["basis_ids"]:
            if basis.startswith("E") and (
                basis not in events
                or events[basis]["assertion_status"] != "AFFIRMED"
                or basis in superseded
            ):
                fail_codes.append("ROLE_AUTHORITY_OR_CONTRAST_INVALID")
            elif basis.startswith("M") and (
                basis not in mentions or mentions[basis]["assertion_status"] != "AFFIRMED"
            ):
                fail_codes.append("ROLE_AUTHORITY_OR_CONTRAST_INVALID")

    executable_narratives: list[str] = []
    for narrative in query_ir["narrative_intents"]:
        if narrative["semantic_role"] not in mapping["narrative_intent_mapping"]:
            fail_codes.append("NARRATIVE_INTENT_INVALID")
        executable_narratives.append(narrative["narrative_intent_id"])

    for relation in query_ir["relation_intents"]:
        for prohibition in query_ir["forbidden_relation_intents"]:
            if (
                relation["predicate"] == prohibition["predicate"]
                and canonical_bytes(relation["subject_selector"])
                == canonical_bytes(prohibition["subject_selector"])
                and canonical_bytes(relation["object_selector"])
                == canonical_bytes(prohibition["object_selector"])
            ):
                fail_codes.append("REQUIRED_FORBIDDEN_INTENT_CONFLICT")

    if query_ir["interpretation_status"] != "VALID" or query_ir["ambiguities"]:
        fail_codes.append("UNRESOLVED_AMBIGUITY")
    if not executable_relations and not executable_narratives:
        fail_codes.append("NO_EXECUTABLE_INTENT")

    if fail_codes:
        result = _failure_result(request, query_ir, fail_codes, root=root)
    else:
        result = {
            "schema_version": "0.2-candidate",
            "validation_id": f"SV-{canonical_sha256(query_ir)[:24]}",
            "request_schema_valid": True,
            "request_id": request["request_id"],
            "request_sha256": canonical_sha256(request),
            "query_ir_sha256": canonical_sha256(query_ir),
            "knowledge_version": request["knowledge_version"],
            "query_ir_schema_valid": True,
            "query_ir_interpretation_status": "VALID",
            "query_ir_schema_sha256": file_sha256(root / QUERY_IR_SCHEMA_PATH),
            "semantic_contract_sha256": file_sha256(root / SEMANTIC_CONTRACT_PATH),
            "semantic_validator_contract_sha256": file_sha256(root / VALIDATOR_CONTRACT_PATH),
            "event_mapping_sha256": file_sha256(root / MAPPING_PATH),
            "result": "PASS",
            "fail_codes": [],
            "executable_relation_intent_ids": _ordered_ids(executable_relations),
            "executable_narrative_intent_ids": _ordered_ids(executable_narratives),
            "prohibited_relation_intent_ids": _ordered_ids(
                item["prohibition_id"] for item in query_ir["forbidden_relation_intents"]
            ),
            "superseded_event_ids": _ordered_ids(
                item["earlier_event_id"] for item in query_ir["resolved_overrides"]
            ),
        }
    validate_schema(result, SEMANTIC_SCHEMA_PATH, root)
    return result


def _selector_matches(
    selector: dict[str, Any], entity_id: str | None, index: p9b1.RetrievalIndex
) -> bool:
    if entity_id is None:
        return False
    if selector["entity_ids"] and entity_id not in selector["entity_ids"]:
        return False
    if selector["entity_types"] and index.entities[entity_id]["entity_type"] not in selector["entity_types"]:
        return False
    return True


def _license_record(
    record: p9b1.ClaimRecord, query_ir: dict[str, Any], index: p9b1.RetrievalIndex
) -> list[str]:
    licenses: list[str] = []
    for relation in query_ir["relation_intents"]:
        if record.claim_kind != "relation" or record.predicate != relation["predicate"]:
            continue
        if _selector_matches(relation["subject_selector"], record.subject, index) and _selector_matches(relation["object_selector"], record.object, index):
            licenses.append(relation["intent_id"])
    for narrative in query_ir["narrative_intents"]:
        if record.claim_kind != "narrative":
            continue
        selector = narrative["entity_selector"]
        if any(_selector_matches(selector, entity_id, index) for entity_id in record.entity_ids):
            if narrative["semantic_role"] == "narrative_fact" or narrative["semantic_role"] in record.semantic_roles:
                licenses.append(narrative["narrative_intent_id"])
    return _ordered_ids(licenses)


def _matching_prohibition(
    record: p9b1.ClaimRecord, query_ir: dict[str, Any], index: p9b1.RetrievalIndex
) -> str | None:
    if record.claim_kind != "relation":
        return None
    for prohibition in query_ir["forbidden_relation_intents"]:
        if record.predicate != prohibition["predicate"]:
            continue
        if _selector_matches(prohibition["subject_selector"], record.subject, index) and _selector_matches(prohibition["object_selector"], record.object, index):
            return prohibition["prohibition_id"]
    return None


def execute_query_ir(
    request: dict[str, Any], query_ir: dict[str, Any], semantic_validation: dict[str, Any],
    *, root: Path = ROOT, top_k: int = 12,
) -> tuple[dict[str, Any] | None, dict[str, list[str]], list[dict[str, Any]]]:
    """Execute only candidates licensed by an exact matching R/N intent."""
    if semantic_validation["result"] != "PASS":
        return None, {}, []
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 50:
        raise ValueError("top_k must be an integer from 1 through 50")
    index = p9b1.build_index(root)
    licensed: list[tuple[p9b1.ClaimRecord, list[str]]] = []
    excluded: list[dict[str, Any]] = []
    all_intent_ids = _ordered_ids([
        *(item["intent_id"] for item in query_ir["relation_intents"]),
        *(item["narrative_intent_id"] for item in query_ir["narrative_intents"]),
    ])
    for record in index.records:
        prohibition_id = _matching_prohibition(record, query_ir, index)
        license_ids = _license_record(record, query_ir, index)
        if license_ids and prohibition_id is None:
            licensed.append((record, license_ids))
        else:
            excluded.append({
                "claim_id": record.claim_id,
                "reason": (
                    "FORBIDDEN_RELATION_MATCH" if prohibition_id
                    else "NO_AFFIRMED_INTENT_LICENSE"
                ),
                "prohibition_id": prohibition_id,
                "evaluated_intent_ids": all_intent_ids,
            })
    relation_order = {
        intent_id: index_no
        for index_no, intent_id in enumerate([
            *semantic_validation["executable_relation_intent_ids"],
            *semantic_validation["executable_narrative_intent_ids"],
        ])
    }
    licensed.sort(key=lambda item: (
        min(relation_order[intent] for intent in item[1]), item[0].claim_id
    ))
    selected = licensed[:top_k]
    candidates: list[dict[str, Any]] = []
    license_map: dict[str, list[str]] = {}
    for rank, (record, license_ids) in enumerate(selected, 1):
        license_map[record.claim_id] = license_ids
        candidates.append({
            "rank": rank,
            "score": 20_000 - rank,
            "score_features": [f"query_ir_license:{intent}" for intent in license_ids],
            **record.payload(),
        })
    result = {
        "schema_version": "1.1",
        "request_id": request["request_id"],
        "request_sha256": canonical_sha256(request),
        "knowledge_version": request["knowledge_version"],
        "normalized_query": p9b1.normalize_query(request["query_text"]),
        "status": "RETRIEVED" if candidates else "NO_MATCH",
        "top_k": top_k,
        "candidate_count": len(candidates),
        "excluded_candidate_count": len(index.records) - len(licensed),
        "runtime_bundle_sha256": index.bundle_sha256,
        "index_sha256": index.index_sha256,
        "candidates": candidates,
    }
    validate_schema(result, PHASE9 / "retrieval-result-schema.yml", root)
    return result, license_map, excluded


def run_scoped_query(
    request: dict[str, Any], *, root: Path = ROOT, top_k: int = 12
) -> dict[str, Any]:
    query_ir = interpret_request(request, root=root)
    semantic_validation = validate_query_ir(request, query_ir, root=root)
    retrieval_result, licenses, exclusions = execute_query_ir(
        request, query_ir, semantic_validation, root=root, top_k=top_k
    )
    return {
        "request": copy.deepcopy(request),
        "query_ir": query_ir,
        "semantic_validation": semantic_validation,
        "retrieval_result": retrieval_result,
        "candidate_license_intent_ids": licenses,
        "query_semantic_exclusions": exclusions,
    }


class BindingValidationError(ValueError):
    def __init__(self, stage: str, message: str):
        super().__init__(f"{stage}: {message}")
        self.stage = stage


class ContentAddressedStore:
    """Small deterministic private store used by the binding contract/tests."""

    def __init__(self) -> None:
        self._bytes: dict[str, bytes] = {}

    def put_bytes(self, data: bytes, *, artifact: bool) -> tuple[str, str, int]:
        digest = hashlib.sha256(data).hexdigest()
        kind = "artifacts" if artifact else "objects"
        address = f"private-audit://{kind}/sha256/{digest}"
        self._bytes[address] = bytes(data)
        return digest, address, len(data)

    def put_object(self, value: Any) -> dict[str, Any]:
        digest, address, length = self.put_bytes(canonical_bytes(value), artifact=False)
        return {
            "content_sha256": digest,
            "content_address": address,
            "media_type": "application/json",
            "byte_length": length,
        }

    def put_artifact(self, data: bytes) -> dict[str, Any]:
        digest, address, length = self.put_bytes(data, artifact=True)
        return {
            "artifact_sha256": digest,
            "content_address": address,
            "byte_length": length,
        }

    def resolve(self, address: str) -> bytes:
        try:
            return self._bytes[address]
        except KeyError as exc:
            raise BindingValidationError(
                "RESOLVE_ALL_NON_NULL_OBJECT_AND_ARTIFACT_ADDRESSES",
                f"unresolvable address {address}",
            ) from exc

    def clone(self) -> "ContentAddressedStore":
        other = ContentAddressedStore()
        other._bytes = dict(self._bytes)
        return other

    def replace_for_test(self, address: str, data: bytes) -> None:
        """Explicit test-only mutation; validation must reject it."""
        self._bytes[address] = bytes(data)


def _artifact_ref(store: ContentAddressedStore, path: Path) -> dict[str, Any]:
    return store.put_artifact(path.read_bytes())


def _object_ref(
    store: ContentAddressedStore, kind: str, value: dict[str, Any]
) -> dict[str, Any]:
    return {"object_kind": kind, **store.put_object(value)}


def _component_ref(
    store: ContentAddressedStore, component_kind: str, implementation_kind: str,
    executable: bytes, configuration: bytes,
) -> dict[str, Any]:
    executable_ref = store.put_artifact(executable)
    configuration_ref = store.put_artifact(configuration)
    build_manifest = canonical_bytes({
        "component_kind": component_kind,
        "implementation_kind": implementation_kind,
        "executable_artifact_sha256": executable_ref["artifact_sha256"],
        "configuration_sha256": configuration_ref["artifact_sha256"],
        "build_format": "P9B1Q_DETERMINISTIC_COMPONENT_V1",
    })
    build_ref = store.put_artifact(build_manifest)
    return {
        "component_kind": component_kind,
        "implementation_kind": implementation_kind,
        "executable_artifact_sha256": executable_ref["artifact_sha256"],
        "executable_artifact_address": executable_ref["content_address"],
        "executable_artifact_byte_length": executable_ref["byte_length"],
        "build_manifest_sha256": build_ref["artifact_sha256"],
        "build_manifest_address": build_ref["content_address"],
        "build_manifest_byte_length": build_ref["byte_length"],
        "configuration_sha256": configuration_ref["artifact_sha256"],
        "configuration_address": configuration_ref["content_address"],
        "configuration_byte_length": configuration_ref["byte_length"],
    }


def _p9a_response_and_audit(
    request: dict[str, Any], execution: dict[str, Any], *, root: Path
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    retrieval = execution["retrieval_result"]
    request_hash = canonical_sha256(request)
    runtime = _read_yaml(root / PHASE9 / "runtime-contract.yml")
    source_commit = runtime["authority"]["source_commit"]
    canonical_input = runtime["authority"]["canonical_input_sha256"]
    bundle_sha = p9b1.verify_runtime_bundle(root)["bundle_sha256"]
    audit_id = f"AUD-{request_hash[:24]}"
    if retrieval is None:
        response = None
        audit = {
            "schema_version": "1.3",
            "audit_id": audit_id,
            "request_schema_version": "1.0",
            "request_id": request["request_id"],
            "request_sha256": request_hash,
            "response_schema_version": "1.2",
            "response_sha256": None,
            "started_at": "1970-01-01T00:00:00Z",
            "completed_at": "1970-01-01T00:00:00Z",
            "knowledge_authority": {
                "knowledge_version": request["knowledge_version"],
                "source_commit": source_commit,
                "canonical_input_sha256": canonical_input,
                "runtime_bundle_sha256": bundle_sha,
                "hash_verified": True,
            },
            "retrieval": {
                "candidate_claim_ids": [],
                "admitted_claim_ids": [],
                "excluded_candidates": [],
            },
            "decision": {
                "disposition": "ABSTAIN",
                "reason_codes": ["HARD_GATE_FAILED"],
                "material_claim_ids": [],
                "coverage_gaps": ["NOT_COVERED"],
            },
            "output_validation": {
                "result": "FAIL_CLOSED",
                "hard_fail_codes": ["NO_SAFE_ADMITTED_ANSWER"],
                "student_visible_citation_count": 0,
            },
            "privacy": {
                "student_identifier_logged": False,
                "public_export_allowed": False,
            },
        }
        validate_schema(audit, PHASE9 / "audit-log-schema.yml", root)
        return response, audit

    candidates = retrieval["candidates"]
    citations: list[dict[str, Any]] = []
    material_claims: list[dict[str, Any]] = []
    answer_units: list[dict[str, Any]] = []
    statements: list[str] = []
    for claim_number, candidate in enumerate(candidates, 1):
        citation_ids: list[str] = []
        for citation in candidate["citations"]:
            citation_id = f"CIT-{len(citations) + 1:03d}"
            citation_ids.append(citation_id)
            citations.append({
                "citation_id": citation_id,
                "claim_id": candidate["claim_id"],
                **citation,
                "visible_to_student": True,
            })
        scalar_qualifiers = {
            key: value for key, value in candidate["qualifiers"].items()
            if isinstance(value, (str, int, float, bool)) and not isinstance(value, (list, dict))
        }
        material_claims.append({
            "claim_id": candidate["claim_id"],
            "entity_ids": candidate["entity_ids"],
            "qualifiers": scalar_qualifiers,
        })
        answer_units.append({
            "unit_id": f"UNIT-{claim_number:03d}",
            "unit_type": "MATERIAL_CLAIM",
            "claim_id": candidate["claim_id"],
            "citation_ids": citation_ids,
        })
        statements.append(candidate["statement_zh"])
    response = {
        "schema_version": "1.2",
        "request_id": request["request_id"],
        "knowledge_version": request["knowledge_version"],
        "source_commit": source_commit,
        "runtime_bundle_sha256": bundle_sha,
        "disposition": "ANSWER",
        "answer_units": answer_units,
        "answer_text": "；".join(statements) + "。",
        "material_claims": material_claims,
        "citations": citations,
        "coverage_gaps": [],
        "validation": {
            "result": "PASS",
            "checked_contract_id": "clonorchis_p9a_controlled_rag_v1",
            "hard_fail_codes": [],
        },
    }
    validate_schema(response, PHASE9 / "response-schema.yml", root)
    response_hash = canonical_sha256(response)
    claim_ids = [candidate["claim_id"] for candidate in candidates]
    audit = {
        "schema_version": "1.3",
        "audit_id": audit_id,
        "request_schema_version": "1.0",
        "request_id": request["request_id"],
        "request_sha256": request_hash,
        "response_schema_version": "1.2",
        "response_sha256": response_hash,
        "started_at": "1970-01-01T00:00:00Z",
        "completed_at": "1970-01-01T00:00:00Z",
        "knowledge_authority": {
            "knowledge_version": request["knowledge_version"],
            "source_commit": source_commit,
            "canonical_input_sha256": canonical_input,
            "runtime_bundle_sha256": bundle_sha,
            "hash_verified": True,
        },
        "retrieval": {
            "candidate_claim_ids": claim_ids,
            "admitted_claim_ids": claim_ids,
            "excluded_candidates": [],
        },
        "decision": {
            "disposition": "ANSWER",
            "reason_codes": ["FULLY_COVERED"],
            "material_claim_ids": claim_ids,
            "coverage_gaps": [],
        },
        "output_validation": {
            "result": "PASS",
            "hard_fail_codes": [],
            "student_visible_citation_count": len(citations),
        },
        "privacy": {
            "student_identifier_logged": False,
            "public_export_allowed": False,
        },
    }
    validate_schema(audit, PHASE9 / "audit-log-schema.yml", root)
    return response, audit


def build_bound_execution(
    request: dict[str, Any], *, root: Path = ROOT, top_k: int = 12
) -> tuple[dict[str, Any], ContentAddressedStore, dict[str, Any]]:
    """Create one complete content-addressed private execution chain."""
    execution = run_scoped_query(request, root=root, top_k=top_k)
    response, audit = _p9a_response_and_audit(request, execution, root=root)
    store = ContentAddressedStore()

    schema_artifacts = {
        name: _artifact_ref(store, root / path)
        for name, path in NORMATIVE_SCHEMA_PATHS.items()
    }
    authority_artifacts = {
        name: _artifact_ref(store, root / path)
        for name, path in NORMATIVE_AUTHORITY_PATHS.items()
    }
    objects: dict[str, Any] = {
        "request": _object_ref(store, "REQUEST", request),
        "query_ir": _object_ref(store, "QUERY_IR", execution["query_ir"]),
        "semantic_validation": _object_ref(
            store, "SEMANTIC_VALIDATION", execution["semantic_validation"]
        ),
        "retrieval_result": (
            _object_ref(store, "RETRIEVAL_RESULT", execution["retrieval_result"])
            if execution["retrieval_result"] is not None else None
        ),
        "audit_record": _object_ref(store, "AUDIT_RECORD", audit),
        "response": _object_ref(store, "RESPONSE", response) if response else None,
    }
    executable = (root / Path(__file__).relative_to(ROOT)).read_bytes()
    interpreter_config = (root / CONFIG_PATH).read_bytes()
    validator_config = canonical_bytes({
        "semantic_contract_sha256": file_sha256(root / SEMANTIC_CONTRACT_PATH),
        "validator_contract_sha256": file_sha256(root / VALIDATOR_CONTRACT_PATH),
        "mapping_sha256": file_sha256(root / MAPPING_PATH),
    })
    executor_config = canonical_bytes({
        "mapping_sha256": file_sha256(root / MAPPING_PATH),
        "retrieval_contract_sha256": file_sha256(root / PHASE9 / "p9b1-retrieval-contract.yml"),
        "top_k": top_k,
    })
    components = {
        "interpreter": _component_ref(
            store, "QUERY_INTERPRETER", "DETERMINISTIC", executable, interpreter_config
        ),
        "semantic_validator": _component_ref(
            store, "QUERY_IR_SEMANTIC_VALIDATOR", "DETERMINISTIC", executable, validator_config
        ),
        "graph_executor": _component_ref(
            store, "GRAPH_EXECUTOR", "DETERMINISTIC", executable, executor_config
        ),
    }
    semantic = execution["semantic_validation"]
    disposition = (
        "QUERY_IR_VALID_RETRIEVED" if semantic["result"] == "PASS"
        else "QUERY_IR_FAIL_CLOSED"
    )
    response_hash = canonical_sha256(response) if response else None
    state_summary = {
        "semantic_validation_result": semantic["result"],
        "semantic_executable_intent_count": len(
            semantic["executable_relation_intent_ids"]
        ) + len(semantic["executable_narrative_intent_ids"]),
        "retrieval_present": execution["retrieval_result"] is not None,
        "audit_disposition": audit["decision"]["disposition"],
        "audit_output_validation_result": audit["output_validation"]["result"],
        "audit_hard_fail_codes": audit["output_validation"]["hard_fail_codes"],
        "audit_response_sha256": audit["response_sha256"],
        "response_present": response is not None,
        "response_disposition": response["disposition"] if response else None,
        "response_validation_result": response["validation"]["result"] if response else None,
    }
    runtime_manifest = _read_yaml(root / PHASE9 / "runtime-bundle-manifest.yml")
    sidecar = {
        "binding_schema_version": "0.2-candidate",
        "binding_id": f"BIND-{canonical_sha256(request)[:24]}",
        "audit_id": audit["audit_id"],
        "request_id": request["request_id"],
        "knowledge_version": request["knowledge_version"],
        "disposition": disposition,
        "canonicalization": "SORTED_UTF8_JSON_NO_INSIGNIFICANT_WHITESPACE_SHA256",
        "created_at": "1970-01-01T00:00:00Z",
        "runtime_bundle_sha256": runtime_manifest["bundle_sha256"],
        "schema_artifacts": schema_artifacts,
        "authority_artifacts": authority_artifacts,
        "objects": objects,
        "state_summary": state_summary,
        "components": components,
        "query_semantic_exclusions": execution["query_semantic_exclusions"][:50],
    }
    validate_schema(sidecar, SIDECAR_SCHEMA_PATH, root)
    bundle = {
        "execution": execution,
        "response": response,
        "audit": audit,
        "sidecar": sidecar,
        "sidecar_sha256": canonical_sha256(sidecar),
        "response_sha256": response_hash,
    }
    return sidecar, store, bundle


def _resolve_checked(
    store: ContentAddressedStore, ref: dict[str, Any], *, artifact: bool,
    stage: str,
) -> bytes:
    address_key = "content_address"
    digest_key = "artifact_sha256" if artifact else "content_sha256"
    data = store.resolve(ref[address_key])
    digest = hashlib.sha256(data).hexdigest()
    if digest != ref[digest_key] or len(data) != ref["byte_length"]:
        raise BindingValidationError(stage, "digest or byte length mismatch")
    if not ref[address_key].endswith(digest):
        raise BindingValidationError(stage, "content address suffix mismatch")
    return data


def validate_bound_execution(
    sidecar: dict[str, Any], store: ContentAddressedStore, *, root: Path = ROOT,
) -> dict[str, Any]:
    """Resolve and deterministically recompute the full bound execution chain."""
    try:
        validate_schema(sidecar, SIDECAR_SCHEMA_PATH, root)
    except Exception as exc:
        raise BindingValidationError("SIDECAR_SCHEMA", str(exc)) from exc

    artifacts: dict[str, bytes] = {}
    for group_name, paths in (
        ("schema_artifacts", NORMATIVE_SCHEMA_PATHS),
        ("authority_artifacts", NORMATIVE_AUTHORITY_PATHS),
    ):
        actual_group = sidecar[group_name]
        if set(actual_group) != set(paths):
            raise BindingValidationError(
                "PARSE_AND_VALIDATE_NORMATIVE_ARTIFACTS", "artifact key set mismatch"
            )
        for name, path in paths.items():
            data = _resolve_checked(
                store, actual_group[name], artifact=True,
                stage="VERIFY_BYTE_LENGTH_AND_ADDRESS_DIGEST",
            )
            if data != (root / path).read_bytes():
                raise BindingValidationError(
                    "PARSE_AND_VALIDATE_NORMATIVE_ARTIFACTS",
                    f"normative artifact substitution: {name}",
                )
            artifacts[name] = data

    objects: dict[str, Any] = {}
    for name, ref in sidecar["objects"].items():
        if ref is None:
            objects[name] = None
            continue
        data = _resolve_checked(
            store, ref, artifact=False, stage="VERIFY_BYTE_LENGTH_AND_ADDRESS_DIGEST"
        )
        try:
            value = json.loads(data)
        except json.JSONDecodeError as exc:
            raise BindingValidationError("PARSE_AND_VALIDATE_ACTUAL_OBJECTS", str(exc)) from exc
        if canonical_bytes(value) != data:
            raise BindingValidationError(
                "PARSE_AND_VALIDATE_ACTUAL_OBJECTS", "object bytes are not canonical"
            )
        objects[name] = value

    request = objects["request"]
    query_ir = objects["query_ir"]
    semantic = objects["semantic_validation"]
    retrieval = objects["retrieval_result"]
    audit = objects["audit_record"]
    response = objects["response"]
    try:
        p9b1.validate_request(request, root)
        validate_schema(query_ir, QUERY_IR_SCHEMA_PATH, root)
        validate_schema(semantic, SEMANTIC_SCHEMA_PATH, root)
        validate_schema(audit, PHASE9 / "audit-log-schema.yml", root)
        if retrieval is not None:
            validate_schema(retrieval, PHASE9 / "retrieval-result-schema.yml", root)
        if response is not None:
            validate_schema(response, PHASE9 / "response-schema.yml", root)
    except Exception as exc:
        raise BindingValidationError("PARSE_AND_VALIDATE_ACTUAL_OBJECTS", str(exc)) from exc

    if query_ir != interpret_request(request, root=root):
        raise BindingValidationError(
            "VERIFY_REQUEST_QUERY_IR_AND_SEMANTIC_VALIDATION_BINDING",
            "QueryIR deterministic recomputation mismatch",
        )
    recomputed_semantic = validate_query_ir(request, query_ir, root=root)
    if semantic != recomputed_semantic:
        raise BindingValidationError(
            "RECOMPUTE_QUERY_IR_SEMANTIC_VALIDATION",
            "semantic validation deterministic recomputation mismatch",
        )

    component_artifacts: dict[str, dict[str, bytes]] = {}
    for component_name, component in sidecar["components"].items():
        component_artifacts[component_name] = {}
        for prefix in ("executable_artifact", "build_manifest", "configuration"):
            ref = {
                "artifact_sha256": component[f"{prefix}_sha256"] if prefix != "build_manifest" else component["build_manifest_sha256"],
                "content_address": component[f"{prefix}_address"] if prefix != "build_manifest" else component["build_manifest_address"],
                "byte_length": component[f"{prefix}_byte_length"] if prefix != "build_manifest" else component["build_manifest_byte_length"],
            }
            component_artifacts[component_name][prefix] = _resolve_checked(
                store, ref, artifact=True,
                stage="VERIFY_COMPONENT_EXECUTABLE_BUILD_AND_CONFIGURATION_HASHES",
            )
    current_executable = (root / Path(__file__).relative_to(ROOT)).read_bytes()
    for component_name, component in sidecar["components"].items():
        executable_data = component_artifacts[component_name]["executable_artifact"]
        if executable_data != current_executable:
            raise BindingValidationError(
                "VERIFY_COMPONENT_EXECUTABLE_BUILD_AND_CONFIGURATION_HASHES",
                "component executable drift",
            )
        expected_build = canonical_bytes({
            "component_kind": component["component_kind"],
            "implementation_kind": component["implementation_kind"],
            "executable_artifact_sha256": component["executable_artifact_sha256"],
            "configuration_sha256": component["configuration_sha256"],
            "build_format": "P9B1Q_DETERMINISTIC_COMPONENT_V1",
        })
        if component_artifacts[component_name]["build_manifest"] != expected_build:
            raise BindingValidationError(
                "VERIFY_COMPONENT_EXECUTABLE_BUILD_AND_CONFIGURATION_HASHES",
                "component build manifest mismatch",
            )

    expected_configs = {
        "interpreter": (root / CONFIG_PATH).read_bytes(),
        "semantic_validator": canonical_bytes({
            "semantic_contract_sha256": file_sha256(root / SEMANTIC_CONTRACT_PATH),
            "validator_contract_sha256": file_sha256(root / VALIDATOR_CONTRACT_PATH),
            "mapping_sha256": file_sha256(root / MAPPING_PATH),
        }),
        "graph_executor": canonical_bytes({
            "mapping_sha256": file_sha256(root / MAPPING_PATH),
            "retrieval_contract_sha256": file_sha256(root / PHASE9 / "p9b1-retrieval-contract.yml"),
            "top_k": retrieval["top_k"] if retrieval is not None else 12,
        }),
    }
    for component_name, expected_config in expected_configs.items():
        if component_artifacts[component_name]["configuration"] != expected_config:
            raise BindingValidationError(
                "VERIFY_COMPONENT_EXECUTABLE_BUILD_AND_CONFIGURATION_HASHES",
                f"{component_name} configuration drift",
            )

    runtime_manifest = _read_yaml(root / PHASE9 / "runtime-bundle-manifest.yml")
    logical_bundle_sha = runtime_manifest["bundle_sha256"]
    if sidecar["runtime_bundle_sha256"] != logical_bundle_sha:
        raise BindingValidationError(
            "VERIFY_SIDECAR_DISPOSITION_CONDITIONS",
            "logical runtime bundle digest mismatch",
        )
    if retrieval is not None and retrieval["runtime_bundle_sha256"] != logical_bundle_sha:
        raise BindingValidationError(
            "VERIFY_SIDECAR_DISPOSITION_CONDITIONS",
            "retrieval runtime bundle mismatch",
        )
    if audit["knowledge_authority"]["runtime_bundle_sha256"] != logical_bundle_sha:
        raise BindingValidationError(
            "VERIFY_SIDECAR_DISPOSITION_CONDITIONS",
            "audit runtime bundle mismatch",
        )
    if response is not None and response["runtime_bundle_sha256"] != logical_bundle_sha:
        raise BindingValidationError(
            "VERIFY_SIDECAR_DISPOSITION_CONDITIONS",
            "response runtime bundle mismatch",
        )

    if semantic["result"] == "PASS":
        expected_retrieval, expected_licenses, expected_exclusions = execute_query_ir(
            request, query_ir, semantic, root=root,
            top_k=retrieval["top_k"] if retrieval else 12,
        )
        if retrieval != expected_retrieval:
            raise BindingValidationError(
                "RECOMPUTE_RETRIEVAL_FROM_EXACT_QUERY_IR_AND_COMPONENTS_IF_STARTED",
                "retrieval deterministic recomputation mismatch",
            )
        expected_exclusions = expected_exclusions[:50]
        if sidecar["query_semantic_exclusions"] != expected_exclusions:
            raise BindingValidationError(
                "VERIFY_CANDIDATE_LICENSE_AND_PRIVATE_SEMANTIC_EXCLUSIONS",
                "query semantic exclusions mismatch",
            )
        for candidate in retrieval["candidates"]:
            features = {
                item.removeprefix("query_ir_license:")
                for item in candidate["score_features"]
                if item.startswith("query_ir_license:")
            }
            if features != set(expected_licenses[candidate["claim_id"]]):
                raise BindingValidationError(
                    "VERIFY_CANDIDATE_LICENSE_AND_PRIVATE_SEMANTIC_EXCLUSIONS",
                    "candidate intent license mismatch",
                )
    elif retrieval is not None:
        raise BindingValidationError(
            "VERIFY_SIDECAR_DISPOSITION_CONDITIONS",
            "FAIL_CLOSED semantic result has a retrieval object",
        )

    expected_response, expected_audit = _p9a_response_and_audit(
        request,
        {
            "retrieval_result": retrieval,
            "semantic_validation": semantic,
        },
        root=root,
    )
    if response != expected_response or audit != expected_audit:
        raise BindingValidationError(
            "VERIFY_P9A_RESPONSE_AND_AUDIT_CROSS_OBJECT_SEMANTICS",
            "response or audit recomputation mismatch",
        )
    expected_summary = {
        "semantic_validation_result": semantic["result"],
        "semantic_executable_intent_count": len(semantic["executable_relation_intent_ids"]) + len(semantic["executable_narrative_intent_ids"]),
        "retrieval_present": retrieval is not None,
        "audit_disposition": audit["decision"]["disposition"],
        "audit_output_validation_result": audit["output_validation"]["result"],
        "audit_hard_fail_codes": audit["output_validation"]["hard_fail_codes"],
        "audit_response_sha256": audit["response_sha256"],
        "response_present": response is not None,
        "response_disposition": response["disposition"] if response else None,
        "response_validation_result": response["validation"]["result"] if response else None,
    }
    if sidecar["state_summary"] != expected_summary:
        raise BindingValidationError(
            "VERIFY_SIDECAR_DISPOSITION_CONDITIONS", "state summary mismatch"
        )
    if sidecar["audit_id"] != audit["audit_id"] or sidecar["request_id"] != request["request_id"]:
        raise BindingValidationError(
            "VERIFY_SIDECAR_DISPOSITION_CONDITIONS", "sidecar identity mismatch"
        )
    return {
        "binding_id": sidecar["binding_id"],
        "result": "PASS",
        "request_sha256": canonical_sha256(request),
        "query_ir_sha256": canonical_sha256(query_ir),
        "semantic_validation_sha256": canonical_sha256(semantic),
        "retrieval_result_sha256": canonical_sha256(retrieval) if retrieval else None,
        "audit_sha256": canonical_sha256(audit),
        "response_sha256": canonical_sha256(response) if response else None,
        "sidecar_sha256": canonical_sha256(sidecar),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--top-k", type=int, default=12)
    args = parser.parse_args()
    request = _read_yaml(args.request)
    execution = run_scoped_query(request, top_k=args.top_k)
    output = json.dumps(execution, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
