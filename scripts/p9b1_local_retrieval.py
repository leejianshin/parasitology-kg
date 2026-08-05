#!/usr/bin/env python3
"""Deterministic, allowlist-only evidence retrieval for Clonorchis PCMS v1.

P9-B1 deliberately does not call a model, the network, or student data.  Every
public retrieval and every public result validation rebuilds a verified index
from the five P9-A allowlisted files.  Callers cannot inject an index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


ROOT = Path(__file__).resolve().parents[1]
PHASE9 = Path("phase9/clonorchis-sinensis")
RUNTIME_CONTRACT_PATH = PHASE9 / "runtime-contract.yml"
BUNDLE_MANIFEST_PATH = PHASE9 / "runtime-bundle-manifest.yml"
REQUEST_SCHEMA_PATH = PHASE9 / "request-schema.yml"
RETRIEVAL_CONTRACT_PATH = PHASE9 / "p9b1-retrieval-contract.yml"
RESULT_SCHEMA_PATH = PHASE9 / "retrieval-result-schema.yml"
FROZEN_RUNTIME_CONTRACT_SHA256 = "bc651a19acd3f81ed14f0f6aada08462129b185bb960ffafd2c2188171cab046"
FROZEN_REQUEST_SCHEMA_SHA256 = "da98c6e6427a52cb17501177da6aa97c73c7417edbec39b019d1b46b4fcdbd56"
FROZEN_RESULT_SCHEMA_SHA256 = "3a44d7d457af16f4850ab812b009e59b10fdd5255ca920bb913670d1bb7ae4d6"
FROZEN_RETRIEVAL_CONTRACT_SHA256 = "c4d35625e16cdd0fb8d46dfb73a999f2da03e9813c731de18bb1dba05393fe3e"

ALLOWED_RUNTIME_INPUTS = (
    "derived/clonorchis-sinensis/pcms-v1/nodes.jsonl",
    "derived/clonorchis-sinensis/pcms-v1/edges.jsonl",
    "phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml",
    "sources/registry.yml",
    "phase9/clonorchis-sinensis/runtime-authority-projection.yml",
)

_SCHEMA_ANNOTATIONS = {
    "$schema", "$id", "title", "description", "default", "examples",
}
_SCHEMA_KEYWORDS = _SCHEMA_ANNOTATIONS | {
    "type", "const", "enum", "required", "additionalProperties",
    "properties", "pattern", "minLength", "maxLength", "minimum",
    "maximum", "minItems", "maxItems", "uniqueItems", "items", "allOf",
    "anyOf", "oneOf", "not", "if", "then", "else",
}


def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_equal(left: Any, right: Any) -> bool:
    return canonical_json(left) == canonical_json(right)


def _schema_error(path: str, message: str) -> ValueError:
    return ValueError(f"schema validation failed at {path}: {message}")


def _type_matches(instance: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "null":
        return instance is None
    raise ValueError(f"unsupported JSON Schema type: {expected}")


def _assert_supported_schema(schema: Any, path: str = "$") -> None:
    """Fail closed if a frozen schema uses a keyword this executor ignores."""
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise ValueError(f"invalid schema node at {path}")
    unknown = set(schema) - _SCHEMA_KEYWORDS
    if unknown:
        raise ValueError(
            f"unsupported JSON Schema keyword(s) at {path}: {sorted(unknown)}"
        )
    for key in ("properties",):
        for name, child in schema.get(key, {}).items():
            _assert_supported_schema(child, f"{path}.{key}.{name}")
    child = schema.get("additionalProperties")
    if isinstance(child, dict):
        _assert_supported_schema(child, f"{path}.additionalProperties")
    child = schema.get("items")
    if isinstance(child, (dict, bool)):
        _assert_supported_schema(child, f"{path}.items")
    for key in ("allOf", "anyOf", "oneOf"):
        for index, child in enumerate(schema.get(key, [])):
            _assert_supported_schema(child, f"{path}.{key}[{index}]")
    for key in ("not", "if", "then", "else"):
        if key in schema:
            _assert_supported_schema(schema[key], f"{path}.{key}")


def _is_valid(instance: Any, schema: Any) -> bool:
    try:
        _validate_schema(instance, schema, "$")
    except ValueError:
        return False
    return True


def _validate_schema(instance: Any, schema: Any, path: str) -> None:
    """Execute every constraint used by the frozen request/result schemas."""
    if schema is True:
        return
    if schema is False:
        raise _schema_error(path, "false schema")

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = (
            expected_type if isinstance(expected_type, list) else [expected_type]
        )
        if not any(_type_matches(instance, item) for item in expected_types):
            raise _schema_error(path, f"expected type {expected_types}")

    if "const" in schema and not _json_equal(instance, schema["const"]):
        raise _schema_error(path, f"does not equal const {schema['const']!r}")
    if "enum" in schema and not any(
        _json_equal(instance, option) for option in schema["enum"]
    ):
        raise _schema_error(path, "is not in enum")

    if isinstance(instance, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in instance]
        if missing:
            raise _schema_error(path, f"missing required properties {missing}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                _validate_schema(value, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise _schema_error(path, f"unexpected property {key!r}")
            elif isinstance(schema.get("additionalProperties"), dict):
                _validate_schema(
                    value, schema["additionalProperties"], f"{path}.{key}"
                )

    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            raise _schema_error(path, "has too few items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            raise _schema_error(path, "has too many items")
        if schema.get("uniqueItems"):
            canonical = [canonical_json(item) for item in instance]
            if len(set(canonical)) != len(canonical):
                raise _schema_error(path, "items are not unique")
        if "items" in schema:
            for index, item in enumerate(instance):
                _validate_schema(item, schema["items"], f"{path}[{index}]")

    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            raise _schema_error(path, "is shorter than minLength")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            raise _schema_error(path, "is longer than maxLength")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            raise _schema_error(path, f"does not match {schema['pattern']!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise _schema_error(path, "is below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise _schema_error(path, "is above maximum")

    for child in schema.get("allOf", []):
        _validate_schema(instance, child, path)
    if "anyOf" in schema and not any(
        _is_valid(instance, child) for child in schema["anyOf"]
    ):
        raise _schema_error(path, "does not satisfy anyOf")
    if "oneOf" in schema:
        count = sum(_is_valid(instance, child) for child in schema["oneOf"])
        if count != 1:
            raise _schema_error(path, f"satisfies {count} oneOf branches")
    if "not" in schema and _is_valid(instance, schema["not"]):
        raise _schema_error(path, "matches forbidden schema")
    if "if" in schema:
        branch = "then" if _is_valid(instance, schema["if"]) else "else"
        if branch in schema:
            _validate_schema(instance, schema[branch], path)


def validate_schema_instance(instance: Any, schema: Any) -> None:
    _assert_supported_schema(schema)
    _validate_schema(instance, schema, "$")


def validate_request(request: dict[str, Any], root: Path = ROOT) -> None:
    validate_schema_instance(request, _read_yaml(root / REQUEST_SCHEMA_PATH))


def verify_runtime_bundle(root: Path = ROOT) -> dict[str, Any]:
    runtime = _read_yaml(root / RUNTIME_CONTRACT_PATH)
    manifest_path = root / BUNDLE_MANIFEST_PATH
    manifest = _read_yaml(manifest_path)
    authority = runtime["authority"]

    if tuple(authority["allowed_runtime_inputs"]) != ALLOWED_RUNTIME_INPUTS:
        raise ValueError("runtime allowlist changed")
    if file_sha256(manifest_path) != authority["runtime_bundle_manifest"]["sha256"]:
        raise ValueError("runtime bundle manifest SHA mismatch")
    if manifest["bundle_sha256"] != authority["runtime_bundle_manifest"]["bundle_sha256"]:
        raise ValueError("runtime bundle identity mismatch")
    canonical_manifest = dict(manifest)
    expected_bundle = canonical_manifest.pop("bundle_sha256")
    if canonical_sha256(canonical_manifest) != expected_bundle:
        raise ValueError("runtime bundle canonical SHA mismatch")

    entries = manifest.get("files", [])
    if tuple(entry.get("path") for entry in entries) != ALLOWED_RUNTIME_INPUTS:
        raise ValueError("runtime bundle file allowlist mismatch")
    for entry in entries:
        path = root / entry["path"]
        if not path.is_file():
            raise ValueError(f"runtime file missing: {entry['path']}")
        if path.stat().st_size != entry["size_bytes"]:
            raise ValueError(f"runtime file size mismatch: {entry['path']}")
        if file_sha256(path) != entry["sha256"]:
            raise ValueError(f"runtime file SHA mismatch: {entry['path']}")
    return manifest


def _verify_control_files(root: Path) -> dict[str, Any]:
    if file_sha256(root / RETRIEVAL_CONTRACT_PATH) != FROZEN_RETRIEVAL_CONTRACT_SHA256:
        raise ValueError("frozen P9-B1 retrieval contract SHA mismatch")
    control = _read_yaml(root / RETRIEVAL_CONTRACT_PATH)
    expected = {
        str(RUNTIME_CONTRACT_PATH): FROZEN_RUNTIME_CONTRACT_SHA256,
        str(REQUEST_SCHEMA_PATH): FROZEN_REQUEST_SCHEMA_SHA256,
        str(RESULT_SCHEMA_PATH): FROZEN_RESULT_SCHEMA_SHA256,
    }
    declared = control["frozen_controls"]
    if declared != {
        "runtime_contract_sha256": FROZEN_RUNTIME_CONTRACT_SHA256,
        "request_schema_sha256": FROZEN_REQUEST_SCHEMA_SHA256,
        "result_schema_sha256": FROZEN_RESULT_SCHEMA_SHA256,
    }:
        raise ValueError("P9-B1 declared frozen control hashes changed")
    for relative, digest in expected.items():
        if file_sha256(root / relative) != digest:
            raise ValueError(f"frozen control SHA mismatch: {relative}")
    if tuple(control["authority"]["allowed_runtime_inputs"]) != ALLOWED_RUNTIME_INPUTS:
        raise ValueError("P9-B1 allowlist changed")
    projection_control = control["authority"].get("authority_projection")
    if projection_control != {
        "path": ALLOWED_RUNTIME_INPUTS[4],
        "sha256": (
            "3ce4adb9808f677e7e99e9eb7e5d1ba9"
            "705bec5c3ead3266ed90c721afa15353"
        ),
        "claim_ids": ["W2-ATOM-024", "W2-ATOM-025"],
    }:
        raise ValueError("P9-B1 authority projection control changed")
    planning = control.get("query_planning", {})
    if planning.get("mode") != "DETERMINISTIC_STRUCTURED_GRAPH_QUERY_PLAN":
        raise ValueError("P9-B1 structured query planning changed")
    if planning.get("entity_alias_authority") != (
        "REVIEWED_RUNTIME_ENTITIES_NAME_AND_ALIASES"
    ):
        raise ValueError("P9-B1 entity alias authority changed")
    if planning.get("required_dimensions") != [
        "entity_ids", "entity_types", "relation_intents", "semantic_roles",
        "evidence_roles", "negated_evidence_roles", "topic_scopes",
        "coverage_groups",
    ]:
        raise ValueError("P9-B1 query-plan dimensions changed")
    blind = control.get("revision_3_acceptance", {}).get(
        "blind_independent_suite_commitment"
    )
    if blind != {
        "suite_id": "clonorchis_p9b1_revision3_blind_heldout_v1",
        "cases": 8,
        "canonical_content_sha256": "01e4d49b2323c51b57402304db9266f6266f5f6c1a00a7cdb6d8385b90a34394",
        "frozen_at": "2026-08-05T18:07:00+09:00",
        "contents_available_to_implementation": False,
        "reveal_timing": "AFTER_REVISION_3_LOCAL_COMMIT",
    }:
        raise ValueError("P9-B1 blind held-out commitment changed")
    revision_4_blind = control.get("revision_4_acceptance", {}).get(
        "blind_independent_suite_commitment"
    )
    if revision_4_blind != {
        "suite_id": "clonorchis_p9b1_revision4_blind_heldout_v1",
        "cases": 15,
        "canonical_content_sha256": (
            "fc38df6ebb0876aa5ac8c5f23e9b6b02"
            "85f476069dd5fb2107aef0cae9c6dd81"
        ),
        "frozen_at": "2026-08-05T09:30:03Z",
        "contents_available_to_implementation": False,
        "reveal_timing": "AFTER_REVISION_4_LOCAL_COMMIT",
    }:
        raise ValueError("P9-B1 revision-4 blind commitment changed")
    return control


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _source_registry(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = registry.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("source registry must contain a sources list")
    result: dict[str, dict[str, Any]] = {}
    for source in sources:
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("registered source lacks source_id")
        if source_id in result:
            raise ValueError(f"duplicate registered source: {source_id}")
        result[source_id] = source
    return result


@dataclass(frozen=True)
class Citation:
    source_id: str
    source_label: str
    locator: str

    def public(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "source_label": self.source_label,
            "locator": self.locator,
        }


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    claim_kind: str
    subject: str | None
    predicate: str | None
    object: str | None
    entity_ids: tuple[str, ...]
    entity_types: tuple[str, ...]
    semantic_roles: tuple[str, ...]
    statement_zh: str
    qualifiers: dict[str, Any]
    citations: tuple[Citation, ...]
    search_text: str

    def payload(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_kind": self.claim_kind,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "entity_ids": list(self.entity_ids),
            "statement_zh": self.statement_zh,
            "qualifiers": self.qualifiers,
            "citations": [citation.public() for citation in self.citations],
        }


@dataclass(frozen=True)
class RetrievalIndex:
    bundle_sha256: str
    index_sha256: str
    entities: dict[str, dict[str, Any]]
    sources: dict[str, dict[str, Any]]
    records: tuple[ClaimRecord, ...]


@dataclass(frozen=True)
class QueryPlan:
    """Deterministic query interpretation over the frozen graph vocabulary."""

    normalized_surface: str
    entity_ids: tuple[str, ...]
    entity_types: tuple[str, ...]
    relation_intents: tuple[str, ...]
    semantic_roles: tuple[str, ...]
    evidence_roles: tuple[str, ...]
    negated_evidence_roles: tuple[str, ...]
    topic_scopes: tuple[str, ...]
    coverage_groups: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        return {
            "normalized_surface": self.normalized_surface,
            "entity_ids": list(self.entity_ids),
            "entity_types": list(self.entity_types),
            "relation_intents": list(self.relation_intents),
            "semantic_roles": list(self.semantic_roles),
            "evidence_roles": list(self.evidence_roles),
            "negated_evidence_roles": list(self.negated_evidence_roles),
            "topic_scopes": list(self.topic_scopes),
            "coverage_groups": list(self.coverage_groups),
        }


def _citation_tuple(
    evidence: Iterable[dict[str, Any]], sources: dict[str, dict[str, Any]]
) -> tuple[Citation, ...]:
    citations: list[Citation] = []
    for item in evidence:
        source_id = item.get("source_id")
        locator = item.get("locator")
        if source_id not in sources:
            raise ValueError(f"unregistered source in admitted claim: {source_id}")
        if not isinstance(locator, str) or not locator.strip():
            raise ValueError(f"missing locator for source {source_id}")
        title = sources[source_id].get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"registered source lacks title: {source_id}")
        citations.append(Citation(source_id, title, locator))
    if not citations:
        raise ValueError("admitted claim has no citation")
    unique = {canonical_json(item.public()): item for item in citations}
    return tuple(unique[key] for key in sorted(unique))


def _entity_search_text(entity: dict[str, Any]) -> str:
    values = [
        entity.get("id", ""), entity.get("name_zh", ""),
        entity.get("name_en", ""), entity.get("scientific_name", ""),
        entity.get("summary", ""), *entity.get("aliases", []),
    ]
    return " ".join(str(value) for value in values if value)


def _review_claims(review: dict[str, Any]) -> dict[str, dict[str, Any]]:
    claims: dict[str, dict[str, Any]] = {}
    for group in review.get("candidate_groups", []):
        common = group.get("common_evidence", [])
        for claim in group.get("claims", []):
            claim_id = claim.get("claim_id")
            if claim_id:
                merged = dict(claim)
                if "evidence" not in merged and common:
                    merged["evidence"] = common
                claims[claim_id] = merged
    return claims


_SEMANTIC_QUALIFIER_KEYS = (
    "role",
    "confirmation_status",
    "confirmation_limit",
    "confirmation_role",
    "evidence_scope",
)


def _formal_semantic_roles(
    qualifiers: dict[str, Any], explicit_role: str | None = None
) -> tuple[str, ...]:
    """Read semantic roles only from admitted claim metadata."""
    roles: set[str] = set()
    if explicit_role:
        roles.add(explicit_role)
    for key in _SEMANTIC_QUALIFIER_KEYS:
        value = qualifiers.get(key)
        if isinstance(value, str) and value:
            roles.add(value)
    if qualifiers.get("cannot_confirm_alone") is True:
        roles.add("cannot_confirm_alone")
    if qualifiers.get("evidence_integration_required") is True:
        roles.add("evidence_integration_required")
    return tuple(sorted(roles))


def _record_entity_types(
    entity_ids: Iterable[str], entities: dict[str, dict[str, Any]]
) -> tuple[str, ...]:
    types: set[str] = set()
    for entity_id in entity_ids:
        entity_type = entities[entity_id].get("entity_type")
        if not isinstance(entity_type, str) or not entity_type:
            raise ValueError("reviewed entity lacks entity_type")
        types.add(entity_type)
    return tuple(sorted(types))


def build_index(root: Path = ROOT) -> RetrievalIndex:
    """Build and seal an index after all P9-A/P9-B1 authority checks pass."""
    manifest = verify_runtime_bundle(root)
    control = _verify_control_files(root)
    nodes = _load_jsonl(root / ALLOWED_RUNTIME_INPUTS[0])
    edges = _load_jsonl(root / ALLOWED_RUNTIME_INPUTS[1])
    review = _read_yaml(root / ALLOWED_RUNTIME_INPUTS[2])
    registry = _read_yaml(root / ALLOWED_RUNTIME_INPUTS[3])
    projection = _read_yaml(root / ALLOWED_RUNTIME_INPUTS[4])
    sources = _source_registry(registry)

    entities: dict[str, dict[str, Any]] = {}
    for node in nodes:
        entity_id = node.get("id")
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError("entity lacks ID")
        if entity_id in entities:
            raise ValueError(f"duplicate entity ID: {entity_id}")
        if node.get("review_status") != "reviewed":
            raise ValueError(f"unreviewed entity: {entity_id}")
        entities[entity_id] = node

    review_claims = _review_claims(review)
    records: list[ClaimRecord] = []
    declared_supporting_ids: set[str] = set()
    for edge in edges:
        if edge.get("relation_status") != "reviewed":
            raise ValueError("unreviewed relation claim")
        source_qualifiers = edge.get("qualifiers", {})
        qualifiers = {
            key: value
            for key, value in source_qualifiers.items()
            if key != "supporting_narrative_atom_ids"
        }
        claim_id = qualifiers.get("source_atom_id")
        subject = edge.get("subject")
        object_id = edge.get("object")
        if subject not in entities or object_id not in entities:
            raise ValueError(f"unknown entity in relation {claim_id}")
        if not isinstance(claim_id, str) or not claim_id:
            raise ValueError("reviewed relation lacks claim ID")
        citations = _citation_tuple(edge.get("evidence", []), sources)
        search = " ".join(
            [edge.get("statement_zh", ""), edge.get("predicate", ""),
             _entity_search_text(entities[subject]),
             _entity_search_text(entities[object_id]),
             " ".join(item.source_label for item in citations)]
        )
        records.append(ClaimRecord(
            claim_id=claim_id, claim_kind="relation", subject=subject,
            predicate=edge.get("predicate"), object=object_id,
            entity_ids=(subject, object_id),
            entity_types=_record_entity_types((subject, object_id), entities),
            semantic_roles=_formal_semantic_roles(qualifiers),
            statement_zh=edge["statement_zh"],
            qualifiers=qualifiers, citations=citations, search_text=search,
        ))
        supporting_ids = source_qualifiers.get(
            "supporting_narrative_atom_ids", []
        )
        if not isinstance(supporting_ids, list):
            raise ValueError("supporting narrative IDs must be a list")
        for supporting_id in supporting_ids:
            if not isinstance(supporting_id, str) or not supporting_id:
                raise ValueError("invalid supporting narrative claim ID")
            if supporting_id in declared_supporting_ids:
                raise ValueError(
                    f"duplicate supporting narrative declaration: {supporting_id}"
                )
            declared_supporting_ids.add(supporting_id)

    if projection.get("status") != "COURSE_LEAD_AUTHORIZED_RUNTIME_PROJECTION":
        raise ValueError("authority projection is not course-lead authorized")
    if projection.get("scope") != "W2-ATOM-024_AND_W2-ATOM-025_ONLY":
        raise ValueError("authority projection scope changed")
    if projection.get("knowledge_version") != "clonorchis_pcms_v1":
        raise ValueError("authority projection knowledge version changed")
    rules = projection.get("projection_rules", {})
    if rules.get("knowledge_addition") is not False:
        raise ValueError("authority projection cannot add knowledge")
    if rules.get("new_graph_edge") is not False:
        raise ValueError("authority projection cannot add graph edges")

    projected_claims = projection.get("claims")
    if not isinstance(projected_claims, list):
        raise ValueError("authority projection claims must be a list")
    projected_ids = [item.get("claim_id") for item in projected_claims]
    expected_supporting_ids = {"W2-ATOM-024", "W2-ATOM-025"}
    if set(projected_ids) != expected_supporting_ids:
        raise ValueError("authority projection claim IDs changed")
    if len(projected_ids) != len(set(projected_ids)):
        raise ValueError("authority projection contains duplicate claim IDs")
    if declared_supporting_ids != expected_supporting_ids:
        raise ValueError("reviewed relation supporting declarations changed")

    for claim in projected_claims:
        claim_id = claim["claim_id"]
        if claim.get("claim_kind") != "supporting_narrative":
            raise ValueError(f"invalid projected claim kind: {claim_id}")
        if claim.get("anchor_claim_id") != "W2-ATOM-023":
            raise ValueError(f"invalid projected claim anchor: {claim_id}")
        if claim.get("predicate") is not None or claim.get("object") is not None:
            raise ValueError(
                f"projected narrative must not fabricate direction: {claim_id}"
            )
        semantic_role = claim.get("semantic_role")
        if not isinstance(semantic_role, str) or not semantic_role:
            raise ValueError(f"projected claim lacks semantic role: {claim_id}")
        subject = claim.get("subject")
        entity_ids = claim.get("entity_ids")
        if (
            not isinstance(entity_ids, list)
            or not entity_ids
            or len(entity_ids) != len(set(entity_ids))
            or subject not in entity_ids
            or any(entity_id not in entities for entity_id in entity_ids)
        ):
            raise ValueError(f"invalid projected entity binding: {claim_id}")
        statement = claim.get("statement_zh")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError(f"projected claim lacks statement: {claim_id}")
        qualifiers = claim.get("qualifiers")
        if not isinstance(qualifiers, dict):
            raise ValueError(f"projected claim lacks qualifiers: {claim_id}")
        if qualifiers.get("source_atom_id") != claim_id:
            raise ValueError(f"projected claim ID binding mismatch: {claim_id}")
        if any(isinstance(value, (dict, list)) for value in qualifiers.values()):
            raise ValueError(f"projected qualifiers must be scalar: {claim_id}")
        citations = _citation_tuple(claim.get("citations", []), sources)
        projected_qualifiers = {
            **qualifiers,
            "semantic_role": semantic_role,
            "anchor_claim_id": claim["anchor_claim_id"],
        }
        search = " ".join(
            [statement, semantic_role]
            + [_entity_search_text(entities[item]) for item in entity_ids]
            + [item.source_label for item in citations]
        )
        records.append(ClaimRecord(
            claim_id=claim_id,
            claim_kind="supporting_narrative",
            subject=subject,
            predicate=None,
            object=None,
            entity_ids=tuple(entity_ids),
            entity_types=_record_entity_types(entity_ids, entities),
            semantic_roles=_formal_semantic_roles(
                projected_qualifiers, semantic_role
            ),
            statement_zh=statement,
            qualifiers=projected_qualifiers,
            citations=citations,
            search_text=search,
        ))

    for claim_id in [f"PCMS-{number:03d}" for number in range(1, 7)]:
        claim = review_claims.get(claim_id)
        if not claim or claim.get("claim_role") != "narrative_fact":
            raise ValueError(f"reviewed narrative claim missing: {claim_id}")
        # Narrative facts have no relation edge, so their reviewed entity binding
        # is frozen in the P9-B1 control contract rather than inferred at query time.
        entity_id = control["index_contract"]["narrative_entity_bindings"][claim_id]
        if entity_id not in entities:
            raise ValueError(f"unknown narrative entity: {entity_id}")
        citations = _citation_tuple(claim.get("evidence", []), sources)
        qualifiers = {}
        if claim.get("qualifier"):
            qualifiers["boundary_note"] = claim["qualifier"]
        search = " ".join(
            [claim["claim"], _entity_search_text(entities[entity_id]),
             " ".join(item.source_label for item in citations)]
        )
        records.append(ClaimRecord(
            claim_id=claim_id, claim_kind="narrative", subject=entity_id,
            predicate=None, object=None, entity_ids=(entity_id,),
            entity_types=_record_entity_types((entity_id,), entities),
            semantic_roles=(claim["claim_role"],),
            statement_zh=claim["claim"], qualifiers=qualifiers,
            citations=citations, search_text=search,
        ))

    records.sort(key=lambda item: item.claim_id)
    identifiers = [record.claim_id for record in records]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate claim ID in retrieval index")
    if len(entities) != 31 or len(records) != 48:
        raise ValueError(
            f"authority counts changed: entities={len(entities)}, records={len(records)}"
        )
    index_payload = {
        "bundle_sha256": manifest["bundle_sha256"],
        "entities": {key: entities[key] for key in sorted(entities)},
        "records": [record.payload() for record in records],
    }
    return RetrievalIndex(
        bundle_sha256=manifest["bundle_sha256"],
        index_sha256=canonical_sha256(index_payload),
        entities=entities, sources=sources, records=tuple(records),
    )


def normalize_query(query: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", query.lower())


_SURFACE_NORMALIZATION = (
    ("没熟透", "未充分加热"),
    ("没熟", "未充分加热"),
    ("未熟透", "未充分加热"),
    ("未煮熟", "未充分加热"),
    ("生腌", "生食"),
    ("b超", "超声"),
    ("胆管", "胆道"),
    ("大便", "粪便"),
    ("粪样", "粪便标本"),
    ("粪标本", "粪便标本"),
    ("看到", "检出"),
    ("发现", "检出"),
    ("狗", "犬"),
)

_SEQUENCE_MARKERS = (
    "生活史", "发育", "顺序", "依次", "先后", "中途", "变化", "演变",
    "转变", "路线", "路径", "衔接", "串联", "串起来", "经过哪些虫期",
)
_MORPHOLOGY_MARKERS = (
    "识别", "辨认", "鉴别", "外形", "结构", "大小", "尺寸", "特征",
    "卵盖", "肩峰", "小疣",
)
_CONNECTION_MARKERS = (
    "传播", "连接", "循环", "周而复始", "往复", "维持", "链条", "网络",
)
_DIAGNOSIS_MARKERS = (
    "诊断", "确诊", "确证", "判读", "证据", "依据", "意义", "说明什么",
)
_SOURCE_MARKERS = (
    "来源", "出自", "文献", "机构", "指南", "资料", "权威", "回查", "溯源",
)
_INFECTION_MARKERS = (
    "感染", "侵入", "入侵", "进入", "吃进", "摄入", "建立感染",
)
_PATHOGENIC_MARKERS = (
    "致病", "损伤", "病变", "伤害", "病理", "主要损害", "导致症状",
)
_TREATMENT_MARKERS = ("治疗", "药物", "用药", "处方", "疗法")
_CARCINOGENIC_MARKERS = (
    "致癌", "癌", "肿瘤", "风险分级", "危害分类", "iarc", "group1",
)
_CONTROL_MARKERS = ("防控", "预防", "卫生", "兽医", "消除", "干预")
_DETECTION_ACTION_MARKERS = (
    "检出", "镜检", "显微镜", "检卵", "查见", "查到", "检验", "检测",
    "找到", "观察到", "检获", "见虫卵", "查虫卵", "便检",
)
_NEGATION_MARKERS = (
    "没有", "未检出", "未见", "未查到", "没查到", "找不到", "阴性",
    "未发现", "未能检出", "并无",
)

_FORMAL_ROLE_TO_EVIDENCE_ROLE = {
    "epidemiological_clue": "epidemiologic_exposure_clue",
    "auxiliary": "imaging_auxiliary_clue",
    "parasitological_confirmation": "pathogen_confirmation",
}

_EVIDENCE_ROLE_TO_FORMAL_ROLES = {
    "epidemiologic_exposure_clue": {"epidemiological_clue", "not_confirmatory"},
    "imaging_auxiliary_clue": {
        "auxiliary", "cannot_confirm_alone", "diagnostic_evidence_integration",
        "diagnostic_confirmation_limit", "evidence_integration_required",
        "pathogen_evidence_required_for_confirmation",
    },
    "pathogen_confirmation": {"parasitological_confirmation"},
}

_GROUP_PREDICATES: dict[str, tuple[str, ...]] = {
    "life_cycle_development": ("develops_into",),
    "host_roles": (
        "has_first_intermediate_host", "has_second_intermediate_host",
        "has_definitive_host", "has_reservoir_host",
    ),
    "one_health_transmission": (
        "has_first_intermediate_host", "has_second_intermediate_host",
        "has_reservoir_host", "sheds_stage", "present_in_environment",
        "transmitted_via",
    ),
    "diagnostic_evidence_roles": (
        "has_diagnostic_clue", "diagnosed_by", "diagnostic_stage_for",
    ),
    "infective_pathogenic_stages": (
        "infective_stage_for", "pathogenic_stage_for",
    ),
    "treatment_options": ("treated_by",),
    "carcinogenic_classification": ("classified_as",),
    "control_measures": ("controlled_by", "targets"),
}

_TOPIC_TO_GROUP = {
    "morphology": "morphology_features",
    "life_cycle": "life_cycle_development",
    "host_roles": "host_roles",
    "one_health": "one_health_transmission",
    "diagnosis": "diagnostic_evidence_roles",
    "stage_roles": "infective_pathogenic_stages",
    "treatment": "treatment_options",
    "carcinogenicity": "carcinogenic_classification",
    "control": "control_measures",
}

_TOPIC_ORDER = (
    "morphology", "life_cycle", "host_roles", "one_health", "diagnosis",
    "stage_roles", "treatment", "carcinogenicity", "control",
    "source_traceability",
)


def _surface_query(query: str) -> str:
    value = query.lower()
    for source, replacement in _SURFACE_NORMALIZATION:
        value = value.replace(source, replacement)
    return normalize_query(value)


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(normalize_query(term) in text for term in terms)


def _formal_entity_aliases(entity: dict[str, Any]) -> set[str]:
    """Derive searchable forms from reviewed names/aliases, not case text."""
    values = [entity.get("name_zh", ""), *entity.get("aliases", [])]
    aliases: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        candidates = {value}
        candidates.update(re.split(r"[、,，/]|或|和", value))
        for candidate in candidates:
            candidate = candidate.replace("华支睾吸虫病", "")
            candidate = candidate.replace("华支睾吸虫", "")
            candidate = candidate.replace("适宜", "")
            normalized = normalize_query(candidate)
            if len(normalized) >= 2 or normalized in {"人", "鱼", "螺", "犬", "猫", "猪"}:
                aliases.add(normalized)
        compact = normalize_query(value)
        if compact == "犬猫猪":
            aliases.update({"犬猫", "猫猪", "犬猪"})
    entity_type = entity.get("entity_type")
    joined = " ".join(str(value) for value in values if value)
    if entity_type == "life_cycle_stage":
        for stage_name in ("虫卵", "毛蚴", "胞蚴", "雷蚴", "尾蚴", "囊蚴", "成虫"):
            if stage_name in joined:
                aliases.add(normalize_query(stage_name))
    if entity_type == "host":
        if "淡水螺" in joined:
            aliases.update({"淡水螺", "螺"})
        if "淡水鱼" in joined:
            aliases.update({"淡水鱼", "河鱼", "鱼"})
        for host_name in ("犬", "猫", "猪", "人类"):
            if host_name in joined:
                aliases.add(normalize_query(host_name))
    if entity_type == "environment" and "水" in joined:
        aliases.update({"淡水环境", "水体", "河塘", "水域"})
    if entity_type == "diagnostic_method":
        if "影像" in joined:
            aliases.update({"影像", "影像学", "胆道影像"})
        if "粪便" in joined and "卵" in joined:
            aliases.update({"粪便检卵", "粪检", "便检"})
        if "十二指肠" in joined and "卵" in joined:
            aliases.update({"十二指肠液检卵", "十二指肠引流液检卵"})
    return aliases


def _entities_with_type(index: RetrievalIndex, entity_type: str) -> set[str]:
    return {
        entity_id for entity_id, entity in index.entities.items()
        if entity.get("entity_type") == entity_type
    }


def _roles_for_entities(
    entity_ids: set[str], index: RetrievalIndex
) -> set[str]:
    return {
        role
        for record in index.records
        if set(record.entity_ids) & entity_ids
        for role in record.semantic_roles
    }


def _detect_entities(surface: str, index: RetrievalIndex) -> set[str]:
    detected: set[str] = set()
    for entity_id, entity in index.entities.items():
        if any(alias and alias in surface for alias in _formal_entity_aliases(entity)):
            detected.add(entity_id)

    # Query-language composition chooses among formally typed reviewed entities.
    # It never creates a runtime fact or a synthetic entity.
    if _has_any(surface, ("犬", "猫", "猪", "家畜", "动物")):
        for entity_id in _entities_with_type(index, "host"):
            formal = " ".join(_formal_entity_aliases(index.entities[entity_id]))
            if any(term in formal for term in ("犬", "猫", "猪", "食鱼哺乳动物")):
                detected.add(entity_id)

    raw_food = _has_any(
        surface, ("生食", "未充分加热", "生鱼", "鱼生", "没煮熟")
    )
    if raw_food:
        for entity_id in _entities_with_type(index, "behavior"):
            formal = normalize_query(_entity_search_text(index.entities[entity_id]))
            if _has_any(formal, ("生食", "未充分加热")):
                detected.add(entity_id)

    imaging_context = (
        "胆道" in surface
        and _has_any(surface, ("检查", "改变", "异常", "扩张", "体检"))
    )
    if imaging_context:
        for entity_id in _entities_with_type(index, "diagnostic_method"):
            formal = normalize_query(_entity_search_text(index.entities[entity_id]))
            entity_roles = _roles_for_entities({entity_id}, index)
            if "胆道" in formal and "auxiliary" in entity_roles:
                detected.add(entity_id)

    stool = _has_any(surface, ("粪便", "排泄物", "便检"))
    detection = _has_any(surface, _DETECTION_ACTION_MARKERS)
    egg_detection = "卵" in surface and detection
    if egg_detection:
        diagnostic_methods = _entities_with_type(index, "diagnostic_method")
        candidates = {
            record.object
            for record in index.records
            if record.predicate == "diagnosed_by"
            and record.object in diagnostic_methods
            and "卵" in normalize_query(record.search_text)
        }
        if stool:
            candidates = {
                entity_id for entity_id in candidates
                if "粪便" in normalize_query(_entity_search_text(index.entities[entity_id]))
            }
        detected.update(item for item in candidates if item)
    return {entity_id for entity_id in detected if entity_id in index.entities}


def analyze_query(query: str, index: RetrievalIndex) -> QueryPlan:
    """Split a query into reviewed entities, intent, evidence role and scope."""
    surface = _surface_query(query)
    entities = _detect_entities(surface, index)
    entity_types = {
        index.entities[entity_id]["entity_type"] for entity_id in entities
    }
    stages = {
        item for item in entities
        if index.entities[item]["entity_type"] == "life_cycle_stage"
    }
    hosts = {
        item for item in entities
        if index.entities[item]["entity_type"] == "host"
    }

    semantic_roles = _roles_for_entities(entities, index)
    evidence_roles = {
        evidence_role
        for formal_role, evidence_role in _FORMAL_ROLE_TO_EVIDENCE_ROLE.items()
        if formal_role in semantic_roles
    }
    negated_evidence_roles: set[str] = set()
    if (
        _has_any(surface, _NEGATION_MARKERS)
        and _has_any(surface, _DETECTION_ACTION_MARKERS)
        and "卵" in surface
    ):
        negated_evidence_roles.add("pathogen_confirmation")
        evidence_roles.add("pathogen_confirmation")
        semantic_roles.add("parasitological_confirmation")

    topics: set[str] = set()
    morphology_intent = _has_any(surface, _MORPHOLOGY_MARKERS)
    sequence_intent = _has_any(surface, _SEQUENCE_MARKERS)
    sequence_marker_count = sum(
        normalize_query(marker) in surface for marker in _SEQUENCE_MARKERS
    )
    if morphology_intent and (
        stages or _has_any(surface, ("成虫", "虫卵", "虫体"))
    ):
        topics.add("morphology")
    if (
        (len(stages) >= 2 and sequence_intent)
        or (
            sequence_marker_count >= 1
            and _has_any(surface, ("虫态", "虫期", "幼虫", "虫体", "形态"))
        )
        or "生活史" in surface
        or "发育" in surface
        or (
            "虫体" in surface
            and _has_any(surface, ("变化", "演变", "转变", "路线", "路径"))
        )
    ):
        topics.add("life_cycle")

    host_role_intent = (
        _has_any(
            surface,
            ("宿主", "第一中间", "第二中间", "终宿主", "保虫"),
        )
        or (
            bool(hosts)
            and _has_any(surface, ("承载", "寄居", "繁殖", "处于什么位置"))
        )
    )
    if host_role_intent and (
        len(hosts) >= 1
        or "宿主" in surface
        or _has_any(surface, ("水生动物", "人", "动物"))
    ):
        topics.add("host_roles")

    actor_groups = set()
    if any(
        index.entities[item]["entity_type"] == "host"
        and index.entities[item].get("name_zh") == "人"
        for item in entities
    ) or "人" in surface:
        actor_groups.add("human")
    if any(
        _has_any(
            normalize_query(_entity_search_text(index.entities[item])),
            ("犬", "猫", "猪", "食鱼哺乳动物"),
        )
        for item in hosts
    ) or "动物" in surface:
        actor_groups.add("animal")
    if any("螺" in index.entities[item].get("name_zh", "") for item in hosts):
        actor_groups.add("snail")
    if any("鱼" in index.entities[item].get("name_zh", "") for item in hosts):
        actor_groups.add("fish")
    if "environment" in entity_types or _has_any(surface, ("环境", "水体", "河塘", "水域")):
        actor_groups.add("environment")
    if (
        (_has_any(surface, _CONNECTION_MARKERS) and len(actor_groups) >= 2)
        or len(actor_groups) >= 4
        or _has_any(surface, ("onehealth", "全健康"))
    ):
        topics.add("one_health")

    if len(evidence_roles) >= 2 or (
        evidence_roles and _has_any(surface, _DIAGNOSIS_MARKERS)
    ):
        topics.add("diagnosis")
    infection_intent = _has_any(surface, _INFECTION_MARKERS)
    pathogenic_intent = _has_any(surface, _PATHOGENIC_MARKERS)
    if infection_intent and pathogenic_intent and _has_any(
        surface, ("虫", "阶段", "虫期", "虫态", "形态")
    ):
        topics.add("stage_roles")
    if _has_any(surface, _TREATMENT_MARKERS) or "treatment" in entity_types:
        topics.add("treatment")
    if _has_any(surface, _CARCINOGENIC_MARKERS) or "hazard_classification" in entity_types:
        topics.add("carcinogenicity")
    if _has_any(surface, _CONTROL_MARKERS):
        topics.add("control")
    if _has_any(surface, _SOURCE_MARKERS):
        topics.add("source_traceability")

    ordered_topics = tuple(item for item in _TOPIC_ORDER if item in topics)
    coverage_groups = tuple(
        _TOPIC_TO_GROUP[item]
        for item in ordered_topics
        if item in _TOPIC_TO_GROUP
    )
    relation_intents = sorted({
        predicate
        for group in coverage_groups
        for predicate in _GROUP_PREDICATES.get(group, ())
    })
    return QueryPlan(
        normalized_surface=surface,
        entity_ids=tuple(sorted(entities)),
        entity_types=tuple(sorted(entity_types)),
        relation_intents=tuple(relation_intents),
        semantic_roles=tuple(sorted(semantic_roles)),
        evidence_roles=tuple(sorted(evidence_roles)),
        negated_evidence_roles=tuple(sorted(negated_evidence_roles)),
        topic_scopes=ordered_topics,
        coverage_groups=coverage_groups,
    )


def _ngrams(text: str, size: int) -> set[str]:
    if len(text) < size:
        return {text} if text else set()
    return {text[index:index + size] for index in range(len(text) - size + 1)}


def _score_record(
    query: str, record: ClaimRecord, plan: QueryPlan
) -> tuple[int, list[str]]:
    normalized = normalize_query(query)
    searchable = normalize_query(record.search_text)
    score = 0
    features: list[str] = []

    overlap2 = len(_ngrams(normalized, 2) & _ngrams(searchable, 2))
    overlap3 = len(_ngrams(normalized, 3) & _ngrams(searchable, 3))
    if overlap2:
        score += min(overlap2, 20) * 2
        features.append("lexical_bigram")
    if overlap3:
        score += min(overlap3, 20) * 4
        features.append("lexical_trigram")

    entity_matches = set(record.entity_ids) & set(plan.entity_ids)
    if entity_matches:
        score += 80 * len(entity_matches)
        features.append("entity_alias_match")
    if record.predicate in plan.relation_intents:
        score += 160
        features.append("relation_intent_match")
    if "source_traceability" in plan.topic_scopes and record.citations:
        score += 20
        features.append("source_scope")

    return score, sorted(set(features))


def _ordered_life_cycle(records: Iterable[ClaimRecord]) -> list[ClaimRecord]:
    remaining = {record.subject: record for record in records}
    objects = {record.object for record in remaining.values()}
    starts = sorted(subject for subject in remaining if subject not in objects)
    ordered: list[ClaimRecord] = []
    current = starts[0] if starts else None
    while current in remaining:
        record = remaining.pop(current)
        ordered.append(record)
        current = record.object
    ordered.extend(sorted(remaining.values(), key=lambda item: item.claim_id))
    return ordered


def _record_has_type(record: ClaimRecord, entity_type: str) -> bool:
    return entity_type in record.entity_types


def _record_object_has_type(
    record: ClaimRecord, entity_type: str, index: RetrievalIndex
) -> bool:
    return bool(
        record.object
        and index.entities[record.object].get("entity_type") == entity_type
    )


def _record_roles_match(record: ClaimRecord, formal_roles: set[str]) -> bool:
    return bool(set(record.semantic_roles) & formal_roles)


def _coverage_records(
    plan: QueryPlan, index: RetrievalIndex
) -> dict[str, list[ClaimRecord]]:
    records = list(index.records)
    result: dict[str, list[ClaimRecord]] = {}
    roles = set(plan.evidence_roles)
    for group in plan.coverage_groups:
        selected: list[ClaimRecord]
        if group == "morphology_features":
            selected = sorted(
                (
                    item for item in records
                    if item.claim_kind == "narrative"
                    and _record_has_type(item, "life_cycle_stage")
                ),
                key=lambda item: item.claim_id,
            )
        elif group == "life_cycle_development":
            selected = _ordered_life_cycle(
                item for item in records
                if item.predicate == "develops_into"
                and item.entity_types == ("life_cycle_stage",)
            )
        elif group == "host_roles":
            priority = {
                "has_first_intermediate_host": 0,
                "has_second_intermediate_host": 1,
                "has_definitive_host": 2,
                "has_reservoir_host": 3,
            }
            selected = sorted(
                (
                    item for item in records
                    if item.predicate in priority
                    and _record_object_has_type(item, "host", index)
                ),
                key=lambda item: (priority[item.predicate], item.claim_id),
            )
        elif group == "one_health_transmission":
            priority = {
                "has_first_intermediate_host": 0,
                "has_second_intermediate_host": 1,
                "has_reservoir_host": 2,
                "sheds_stage": 3,
                "present_in_environment": 4,
                "transmitted_via": 5,
            }
            selected = sorted(
                (
                    item for item in records
                    if item.predicate in priority
                    and (
                        _record_has_type(item, "host")
                        or _record_has_type(item, "environment")
                        or _record_has_type(item, "behavior")
                        or _record_has_type(item, "intervention")
                    )
                ),
                key=lambda item: (priority[item.predicate], item.claim_id),
            )
        elif group == "diagnostic_evidence_roles":
            selected: list[ClaimRecord] = []
            requested_roles = roles or set(_EVIDENCE_ROLE_TO_FORMAL_ROLES)
            formal_roles = {
                formal_role
                for evidence_role in requested_roles
                for formal_role in _EVIDENCE_ROLE_TO_FORMAL_ROLES[evidence_role]
            }
            selected.extend(
                item for item in records
                if _record_roles_match(item, formal_roles)
            )
            if "pathogen_confirmation" in requested_roles:
                selected.extend(
                    item for item in records
                    if item.predicate == "diagnostic_stage_for"
                    and _record_has_type(item, "life_cycle_stage")
                )
            selected = sorted(
                {item.claim_id: item for item in selected}.values(),
                key=lambda item: item.claim_id,
            )
        elif group == "infective_pathogenic_stages":
            selected = sorted(
                (
                    item for item in records
                    if item.predicate in set(_GROUP_PREDICATES[group])
                    and item.subject
                    and index.entities[item.subject].get("entity_type")
                    == "life_cycle_stage"
                ),
                key=lambda item: item.claim_id,
            )
        elif group == "treatment_options":
            selected = sorted(
                (
                    item for item in records
                    if item.predicate == "treated_by"
                    and _record_object_has_type(item, "treatment", index)
                ),
                key=lambda item: item.claim_id,
            )
        elif group == "carcinogenic_classification":
            selected = sorted(
                (
                    item for item in records
                    if item.predicate == "classified_as"
                    and _record_object_has_type(
                        item, "hazard_classification", index
                    )
                ),
                key=lambda item: item.claim_id,
            )
        elif group == "control_measures":
            selected = sorted(
                (
                    item for item in records
                    if item.predicate in set(_GROUP_PREDICATES[group])
                    and _record_has_type(item, "intervention")
                ),
                key=lambda item: item.claim_id,
            )
        else:
            predicates = set(_GROUP_PREDICATES.get(group, ()))
            selected = sorted(
                (item for item in records if item.predicate in predicates),
                key=lambda item: item.claim_id,
            )
        result[group] = selected

    generic_entities = {"parasite.clonorchis_sinensis", "disease.clonorchiasis"}
    neighborhood_ids = set(plan.entity_ids) - generic_entities
    if neighborhood_ids:
        result["entity_neighborhood"] = sorted(
            (
                item for item in records
                if set(item.entity_ids) & neighborhood_ids
            ),
            key=lambda item: item.claim_id,
        )
    return result


def _rank(
    request: dict[str, Any], index: RetrievalIndex, top_k: int
) -> tuple[list[dict[str, Any]], int]:
    plan = analyze_query(request["query_text"], index)
    groups = _coverage_records(plan, index)
    coverage: list[tuple[ClaimRecord, str]] = []
    covered_ids: set[str] = set()
    for group in (*plan.coverage_groups, "entity_neighborhood"):
        for record in groups.get(group, []):
            if record.claim_id not in covered_ids:
                coverage.append((record, group))
                covered_ids.add(record.claim_id)

    scored: list[tuple[int, str, ClaimRecord, list[str]]] = []
    for record in index.records:
        score, features = _score_record(request["query_text"], record, plan)
        if score > 0:
            scored.append((score, record.claim_id, record, features))
    scored.sort(key=lambda item: (-item[0], item[1]))

    ordered: list[tuple[int, str, ClaimRecord, list[str]]] = []
    for order, (record, group) in enumerate(coverage):
        _, lexical_features = _score_record(request["query_text"], record, plan)
        ordered.append((
            20_000 - order,
            record.claim_id,
            record,
            sorted(set([*lexical_features, f"coverage:{group}"])),
        ))
    ordered.extend(item for item in scored if item[1] not in covered_ids)

    candidates: list[dict[str, Any]] = []
    for rank, (score, _, record, features) in enumerate(ordered[:top_k], 1):
        candidates.append({
            "rank": rank,
            "score": score,
            "score_features": features,
            **record.payload(),
        })
    eligible_ids = covered_ids | {item[1] for item in scored}
    return candidates, len(index.records) - len(eligible_ids)


def _result(
    request: dict[str, Any], index: RetrievalIndex, top_k: int
) -> dict[str, Any]:
    candidates, excluded = _rank(request, index, top_k)
    return {
        "schema_version": "1.1",
        "request_id": request["request_id"],
        "request_sha256": canonical_sha256(request),
        "knowledge_version": request["knowledge_version"],
        "normalized_query": normalize_query(request["query_text"]),
        "status": "RETRIEVED" if candidates else "NO_MATCH",
        "top_k": top_k,
        "candidate_count": len(candidates),
        "excluded_candidate_count": excluded,
        "runtime_bundle_sha256": index.bundle_sha256,
        "index_sha256": index.index_sha256,
        "candidates": candidates,
    }


def _validate_result_for_root(
    result: dict[str, Any], request: dict[str, Any], index: RetrievalIndex,
    root: Path,
) -> None:
    validate_schema_instance(result, _read_yaml(root / RESULT_SCHEMA_PATH))
    expected = _result(request, index, result["top_k"])
    if not _json_equal(result, expected):
        raise ValueError(
            "result semantic mismatch: request, ranking, source, entity, locator, "
            "direction, bundle, or index binding changed"
        )


def retrieve(
    request: dict[str, Any], *, root: Path = ROOT, top_k: int = 12
) -> dict[str, Any]:
    """Public retrieval API. No caller-provided index is accepted."""
    validate_request(request, root)
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 50:
        raise ValueError("top_k must be an integer from 1 through 50")
    index = build_index(root)
    result = _result(request, index, top_k)
    _validate_result_for_root(result, request, index, root)
    return result


def validate_result(
    result: dict[str, Any], request: dict[str, Any], *, root: Path = ROOT
) -> None:
    """Validate schema and semantics against a freshly verified index."""
    validate_request(request, root)
    index = build_index(root)
    _validate_result_for_root(result, request, index, root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    request = _read_yaml(args.request)
    result = retrieve(request, top_k=args.top_k)
    output = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        if args.check:
            if not args.output.exists() or args.output.read_text(encoding="utf-8") != output:
                raise SystemExit("retrieval output differs from frozen file")
        else:
            args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
