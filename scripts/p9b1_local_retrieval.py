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
FROZEN_RETRIEVAL_CONTRACT_SHA256 = "df4d068000f9b12fe0ffbf061ab16a6208fa5ddfc227df955737b595040ccda0"

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
        "evidence_roles", "negated_evidence_roles",
        "required_evidence_roles", "evidence_observations",
        "control_semantic_roles", "topic_scopes", "coverage_groups",
        "relation_activations",
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
    revision_5 = control.get("revision_5_acceptance", {})
    public_regression = revision_5.get(
        "revision_4_blind_disclosed_public_regression"
    )
    if public_regression != {
        "path": (
            "phase9/clonorchis-sinensis/acceptance-cases/"
            "p9b1-revision4-blind-disclosed-regression.yml"
        ),
        "sha256": (
            "b88918ae75fb26a61f43dcf83636a8a9"
            "444c460060edd3f88b93d00232ffd1cd"
        ),
        "cases": 15,
        "prior_blind_result_on_b71d08c": "12/15 PASS_CHANGES_REQUIRED",
        "role_from_revision_5": "PUBLIC_REGRESSION_NOT_HELD_OUT",
        "required_claim_recall_top12": "ALL_REQUIRED_IDS_PRESENT",
    }:
        raise ValueError("P9-B1 revision-4 public regression control changed")
    revision_5_blind = revision_5.get("blind_independent_suite_commitment")
    if revision_5_blind != {
        "suite_id": "clonorchis_p9b1_revision5_blind_heldout_v1",
        "cases": 16,
        "canonical_content_sha256": (
            "924205fe1b4df71639e475274697a8b4b"
            "f4c72e77a4fe346ccf4a5182919dfd6"
        ),
        "frozen_at": "2026-08-05T10:01:00Z",
        "contents_available_to_implementation": False,
        "reveal_timing": "AFTER_REVISION_5_LOCAL_COMMIT",
    }:
        raise ValueError("P9-B1 revision-5 blind commitment changed")
    revision_6 = control.get("revision_6_acceptance", {})
    public_regression = revision_6.get(
        "revision_5_blind_disclosed_public_regression"
    )
    if public_regression != {
        "path": (
            "phase9/clonorchis-sinensis/acceptance-cases/"
            "p9b1-revision5-blind-disclosed-regression.yml"
        ),
        "sha256": (
            "1d8b08110ded74b0c392876d4e0593eb"
            "21f7a37c683803394d7600c6c9f0644b"
        ),
        "cases": 16,
        "prior_recall_on_12554f2": "11/16 PASS_CHANGES_REQUIRED",
        "prior_complete_plan_assertions_on_12554f2": (
            "5/16 PASS_CHANGES_REQUIRED"
        ),
        "role_from_revision_6": "PUBLIC_REGRESSION_NOT_HELD_OUT",
        "required_claim_recall_top12": "ALL_REQUIRED_IDS_PRESENT",
    }:
        raise ValueError("P9-B1 revision-5 public regression control changed")
    revision_6_blind = revision_6.get("blind_independent_suite_commitment")
    if revision_6_blind != {
        "suite_id": "clonorchis_p9b1_revision6_blind_heldout_v1",
        "cases": 18,
        "canonical_content_sha256": (
            "074636eaaf4b7d301c6f55645d33fe85"
            "8f58eba3abb4c0caaf9b741b72b0a698"
        ),
        "frozen_at": "2026-08-05T11:33:18Z",
        "contents_available_to_implementation": False,
        "reveal_timing": "AFTER_REVISION_6_LOCAL_COMMIT",
    }:
        raise ValueError("P9-B1 revision-6 blind commitment changed")
    revision_7 = control.get("revision_7_acceptance", {})
    public_regression = revision_7.get(
        "revision_6_blind_disclosed_public_regression"
    )
    if public_regression != {
        "path": (
            "phase9/clonorchis-sinensis/acceptance-cases/"
            "p9b1-revision6-blind-disclosed-regression.yml"
        ),
        "sha256": (
            "8c770d29acfab35f5424be7e64375361"
            "adc5519cc045bd74bf7b559ddf15abac"
        ),
        "cases": 18,
        "prior_recall_on_bbdc3bb": "13/18 PASS_CHANGES_REQUIRED",
        "prior_complete_plan_assertions_on_bbdc3bb": (
            "11/18 PASS_CHANGES_REQUIRED"
        ),
        "role_from_revision_7": "PUBLIC_REGRESSION_NOT_HELD_OUT",
        "required_claim_recall_top12": "ALL_REQUIRED_IDS_PRESENT",
        "required_plan_assertions": (
            "ALL_REQUIRED_RELATIONS_ROLES_EVENTS_AND_SCOPES_PRESENT"
        ),
    }:
        raise ValueError("P9-B1 revision-6 public regression control changed")
    revision_7_blind = revision_7.get("blind_independent_suite_commitment")
    if revision_7_blind != {
        "suite_id": "clonorchis_p9b1_revision7_blind_heldout_v1",
        "cases": 22,
        "canonical_content_sha256": (
            "5bc7692fe7fb0450c80d1227bfada034"
            "52d3ac8305d9bce74e22e64b513e89a5"
        ),
        "frozen_at": "2026-08-05T12:20:45Z",
        "contents_available_to_implementation": False,
        "reveal_timing": "AFTER_REVISION_7_LOCAL_COMMIT",
    }:
        raise ValueError("P9-B1 revision-7 blind commitment changed")
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
class EvidenceObservation:
    """A query-side evidence event bound to its method and polarity."""

    observation_id: str
    evidence_entity_id: str | None
    evidence_role: str
    polarity: str
    event_type: str
    semantic_roles: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "evidence_entity_id": self.evidence_entity_id,
            "evidence_role": self.evidence_role,
            "polarity": self.polarity,
            "event_type": self.event_type,
            "semantic_roles": list(self.semantic_roles),
        }


@dataclass(frozen=True)
class RelationActivation:
    """A reviewed graph relation activated by the query event plan."""

    claim_id: str
    predicate: str
    semantic_roles: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "predicate": self.predicate,
            "semantic_roles": list(self.semantic_roles),
        }


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
    required_evidence_roles: tuple[str, ...]
    evidence_observations: tuple[EvidenceObservation, ...]
    relation_activations: tuple[RelationActivation, ...]
    control_semantic_roles: tuple[str, ...]
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
            "required_evidence_roles": list(self.required_evidence_roles),
            "evidence_observations": [
                observation.public() for observation in self.evidence_observations
            ],
            "relation_activations": [
                activation.public() for activation in self.relation_activations
            ],
            "control_semantic_roles": list(self.control_semantic_roles),
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
    "mechanism",
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
    if qualifiers.get("universal_elimination_claim") is False:
        roles.add("universal_elimination_claim_false")
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
    "变化链", "发生次序", "逐级", "阶段变化", "发育链", "演化链",
    "发育全程", "中间阶段", "完整过程", "逐步", "一步步", "哪些阶段",
)
_MORPHOLOGY_MARKERS = (
    "识别", "辨认", "外形", "结构", "大小", "尺寸", "特征",
    "卵盖", "肩峰", "小疣",
)
_CLINICAL_DIFFERENTIAL_MARKERS = (
    "鉴别诊断", "患者诊断", "证据区分", "从鉴别中", "感染鉴别",
    "排除感染", "拿掉", "其他胆道疾病", "临床上",
)
_MORPHOLOGY_ANCHORS = (
    "形态", "外观", "外形", "结构", "尺寸", "卵盖", "肩峰", "小疣",
    "显微特征", "肉眼",
)
_CONNECTION_MARKERS = (
    "传播", "连接", "循环", "周而复始", "往复", "维持", "链条", "网络",
    "延续", "回到", "闭环",
)
_DIAGNOSIS_MARKERS = (
    "诊断", "确诊", "确证", "判读", "证据", "依据", "意义", "说明什么",
    "最终判断", "辅助信息", "合并哪些", "综合判断",
)
_NONCONFIRMATORY_QUERY_MARKERS = (
    "线索", "辅助信息", "非确证",
    "不能单独确诊", "不能单独确认", "不可单独确诊", "不可单独确认",
    "只是线索", "不属于确证",
)
_EPIDEMIOLOGIC_EXPOSURE_MARKERS = (
    "流行区", "流行地区", "流行地", "居住史", "旅居史", "暴露史",
)
_SOURCE_MARKERS = (
    "来源", "出自", "文献", "机构", "指南", "资料", "权威", "回查", "溯源",
    "查证", "翻阅", "出处", "登记材料", "核对材料",
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
_CONTROL_MARKERS = (
    "防控", "防治", "预防", "兽医", "消除", "干预", "管控",
    "治理", "切断", "阻断", "厕所", "改厕", "粪污", "粪便污染",
    "根除", "清除", "消灭", "排泄物污染", "粪水", "便溺入水",
    "整治", "粪源", "无害化", "排泄物入水", "排污", "避免生食",
    "避免食用", "减少人粪", "减少动物排泄物", "减少家养动物排泄物",
)
_DETECTION_ACTION_MARKERS = (
    "检出", "镜检", "显微镜", "检卵", "查见", "查到", "检验", "检测",
    "找到", "观察到", "检获", "见虫卵", "查虫卵", "便检", "粪检",
    "寄生虫学检查", "病原学检查", "阳性发现", "阳性结果", "看见",
    "查出", "检到", "检得", "寻获", "观察见", "送检", "查卵",
)
_NEGATED_DETECTION_PATTERNS = (
    re.compile(
        r"(?:没|未|无|没有|并无|未能).{0,10}"
        r"(?:检出|查到|查出|找到|找出|发现|阳性|检获|查见|观察到|观察见|看见|检到|检得|寻获)"
    ),
    re.compile(
        r"(?:检查|检测|检卵|镜检|便检|粪检|送检|寄生虫学|病原学).{0,10}"
        r"(?:阴性|未检出|未见|没找到|没有阳性|无阳性|查无|未获阳性)"
    ),
    re.compile(r"(?:结果|报告).{0,4}(?:为)?阴性"),
    re.compile(
        r"(?:查不出|查不到|检不出|检不到|找不着|没查着|查无).{0,6}"
        r"(?:虫卵|病原|阳性)"
    ),
    re.compile(
        r"(?:仍|始终|依然)?(?:无|没有).{0,6}(?:虫卵|目标虫卵)"
        r".{0,4}(?:可见|可检出|被发现|阳性所见)"
    ),
)

_NEGATED_IMAGING_PATTERNS = (
    re.compile(
        r"(?:影像|超声|ct|mri|胆道).{0,10}"
        r"(?:未显示|未见|没有显示|无).{0,8}(?:异常|改变|扩张|特异)"
    ),
)

_POSITIVE_DETECTION_MARKERS = (
    "检出", "查到", "查出", "找到", "发现", "检获", "查见", "观察到",
    "观察见", "看见", "检到", "检得", "寻获", "阳性", "见卵",
)

_LIFE_CYCLE_EVENT_MARKERS = (
    "幼体", "幼虫", "虫态", "包囊", "成熟", "转换", "形成", "前序", "后续",
    "变成", "转化", "蜕变", "入鱼", "螺内", "鱼内", "宿主体内",
    "演替",
)

_MORPHOLOGY_NEGATION_PATTERNS = (
    re.compile(r"(?:不|不是|并非).{0,8}(?:辨认|识别|观察).{0,8}(?:外形|形态|结构)"),
    re.compile(r"(?:不|不是|并非).{0,8}(?:虫体|虫卵).{0,6}(?:外形|形态)"),
)

_SHEDDING_EVENT_MARKERS = (
    "排出", "排卵", "随粪", "排泄物进入", "排泄物排入", "排入淡水",
    "污染水体", "污染淡水", "进入水域", "进入淡水",
)
_ENVIRONMENT_EVENT_MARKERS = (
    "进入水域", "进入淡水", "排入淡水", "污染水体", "污染淡水",
    "淡水中", "水体中", "水域中",
)
_HOST_INGESTION_MARKERS = (
    "摄取", "摄入", "食入", "吞入", "吃进", "被人摄入", "食鱼行为",
)
_PARASITISM_EVENT_MARKERS = (
    "寄生部位", "寄生于", "在胆管成熟", "进入胆管", "进入胆道",
    "胆管内成熟", "胆道内成熟", "在胆道成熟", "胆道成熟",
)
_BOUNDARY_MARKERS = (
    "边界", "量化效果", "定量", "任何地区", "所有地区", "普遍", "保证",
    "根除", "清除", "已证实有效", "外推",
)

_DIAGNOSTIC_INTEGRATION_ROLES = {
    "diagnostic_evidence_integration",
    "diagnostic_confirmation_limit",
    "evidence_integration_required",
    "pathogen_evidence_required_for_confirmation",
}

_DIAGNOSTIC_CONTRAST_ROLES = _DIAGNOSTIC_INTEGRATION_ROLES | {
    "epidemiological_clue",
    "auxiliary",
    "not_confirmatory",
    "cannot_confirm_alone",
}

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
    "event_transmission": (
        "has_first_intermediate_host", "has_second_intermediate_host",
        "has_definitive_host", "has_reservoir_host", "sheds_stage",
        "present_in_environment", "transmitted_via", "infective_stage_for",
        "parasitizes_site",
    ),
    "exposure_evidence": ("has_diagnostic_clue", "transmitted_via"),
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
    "transmission": "event_transmission",
    "exposure": "exposure_evidence",
    "diagnosis": "diagnostic_evidence_roles",
    "stage_roles": "infective_pathogenic_stages",
    "treatment": "treatment_options",
    "carcinogenicity": "carcinogenic_classification",
    "control": "control_measures",
}

_TOPIC_ORDER = (
    "morphology", "life_cycle", "transmission", "exposure", "host_roles",
    "one_health", "diagnosis", "stage_roles", "treatment",
    "carcinogenicity", "control", "boundary", "source_traceability",
)


def _surface_query(query: str) -> str:
    value = query.lower()
    for source, replacement in _SURFACE_NORMALIZATION:
        value = value.replace(source, replacement)
    return normalize_query(value)


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(normalize_query(term) in text for term in terms)


def _has_negated_detection(text: str) -> bool:
    """Recognize compositional negative test reports, not negative conclusions."""
    return any(pattern.search(text) for pattern in _NEGATED_DETECTION_PATTERNS)


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
        if "虫卵" in joined:
            # Keep the reviewed full stage name; a one-character alias would
            # falsely match the unrelated action word “排卵”.
            aliases.add("虫卵")
        if "囊蚴" in joined:
            aliases.update({"包囊幼体", "包囊期", "包囊", "感染性包囊"})
        if "成虫" in joined:
            aliases.update({"成熟虫体", "成熟阶段", "成体", "成熟形态"})
    if entity_type == "host":
        if "淡水螺" in joined:
            aliases.update({"淡水螺", "螺", "软体动物", "螺类"})
        if "淡水鱼" in joined:
            aliases.update({"淡水鱼", "河鱼", "鱼"})
        for host_name in ("犬", "猫", "猪", "人类"):
            if host_name in joined:
                aliases.add(normalize_query(host_name))
        if "人" in joined:
            aliases.update({"感染者", "患者", "终宿主"})
    if entity_type == "environment" and "水" in joined:
        aliases.update({"淡水环境", "水体", "河塘", "水域"})
    if entity_type == "diagnostic_method":
        if "影像" in joined:
            aliases.update({"影像", "影像学", "胆道影像", "彩超"})
        if "粪便" in joined and "卵" in joined:
            aliases.update({"粪便检卵", "粪检", "便检"})
        if "十二指肠" in joined and "卵" in joined:
            aliases.update({
                "十二指肠液检卵", "十二指肠引流液检卵",
                "十二指肠引流标本", "十二指肠液标本", "十二指肠标本",
            })
    if entity_type == "intervention":
        compact = normalize_query(joined)
        if "改善卫生设施" in compact:
            aliases.update({
                "卫生设施", "厕所设施", "厕所", "改厕", "改良厕所",
                "厕所改造", "环境卫生", "卫生治理",
            })
        if "减少动物粪便污染" in compact:
            aliases.update({
                "动物粪污", "家畜粪污", "畜禽粪污", "牲畜粪便",
                "动物排泄物污染", "家畜排泄物", "畜禽排泄物",
                "动物排泄物", "家养动物排泄物", "动物粪便",
            })
        if "减少人粪便污染" in compact:
            aliases.update({
                "人粪污", "人粪便污染", "人的排泄物污染", "人类排泄物",
                "人粪", "人的排泄物", "人排泄物",
            })
        if "综合防控" in compact:
            aliases.update({
                "综合防控", "综合治理", "协同防控", "人畜环境协同",
                "全健康",
            })
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


def _diagnostic_method_cues(
    entity_id: str, index: RetrievalIndex
) -> set[str]:
    """Derive query cues from the reviewed diagnostic method identity."""
    entity = index.entities[entity_id]
    joined = normalize_query(_entity_search_text(entity))
    cues = set(_formal_entity_aliases(entity))
    if "十二指肠" in joined:
        cues.update({
            "十二指肠液", "十二指肠引流液", "十二指肠查卵",
            "十二指肠引流液查卵", "十二指肠引流标本",
            "十二指肠液标本", "十二指肠标本",
        })
    if "粪便" in joined and "卵" in joined:
        cues.update({
            "粪便", "粪样", "粪标本", "便涂片", "粪涂片", "粪检",
            "便检", "排泄物", "大便",
        })
    if "影像" in joined:
        cues.update({"影像", "超声", "彩超", "ct", "mri", "胆道影像"})
    return {normalize_query(cue) for cue in cues if cue}


def _diagnostic_method_occurrences(
    surface: str, index: RetrievalIndex
) -> list[tuple[int, str]]:
    occurrences: list[tuple[int, str]] = []
    for entity_id in sorted(_entities_with_type(index, "diagnostic_method")):
        formal = normalize_query(_entity_search_text(index.entities[entity_id]))
        if "粪便" in formal and "卵" in formal and not (
            "卵" in surface or _has_any(surface, _DETECTION_ACTION_MARKERS)
        ):
            continue
        positions = [
            surface.find(cue)
            for cue in _diagnostic_method_cues(entity_id, index)
            if cue and cue in surface
        ]
        if positions:
            occurrences.append((min(positions), entity_id))
    return sorted(occurrences)


def _detect_diagnostic_methods(
    surface: str, index: RetrievalIndex
) -> set[str]:
    detected = {
        entity_id
        for _, entity_id in _diagnostic_method_occurrences(surface, index)
    }
    detection = _has_any(surface, _DETECTION_ACTION_MARKERS)
    if "卵" in surface and detection and not detected:
        detected.update(
            record.object
            for record in index.records
            if record.predicate == "diagnosed_by"
            and record.object in _entities_with_type(index, "diagnostic_method")
            and "卵" in normalize_query(record.search_text)
        )
    return {item for item in detected if item}


def _is_negative_observation(text: str) -> bool:
    return "阴性" in text or _has_negated_detection(text) or any(
        pattern.search(text) for pattern in _NEGATED_IMAGING_PATTERNS
    )


def _is_positive_observation(text: str) -> bool:
    if _is_negative_observation(text):
        return False
    if _has_any(text, _POSITIVE_DETECTION_MARKERS):
        return True
    return (
        _has_any(text, ("提示", "显示", "呈现"))
        and _has_any(text, ("异常", "改变", "扩张", "阳性"))
    )


def _method_windows(
    surface: str, occurrences: list[tuple[int, str]]
) -> list[tuple[str, str]]:
    """Bind nearby polarity wording to each mentioned diagnostic method."""
    if not occurrences:
        return []
    boundaries = [0, *(position for position, _ in occurrences[1:]), len(surface)]
    return [
        (entity_id, surface[boundaries[index]:boundaries[index + 1]])
        for index, (_, entity_id) in enumerate(occurrences)
    ]


def _coordinated_polarities(text: str, count: int) -> list[str] | None:
    """Resolve explicit ordered constructions such as '分别阴性和阳性'."""
    if count < 2:
        return None
    if "前者" in text and "后者" in text:
        former = text.split("前者", 1)[1].split("后者", 1)[0]
        latter = text.split("后者", 1)[1]
        return [
            "negative" if _is_negative_observation(former) else "positive"
            if _is_positive_observation(former) else "unspecified",
            "negative" if _is_negative_observation(latter) else "positive"
            if _is_positive_observation(latter) else "unspecified",
        ]
    if "分别" not in text:
        return None
    tail = text.split("分别", 1)[1]
    tokens = [match.group(0) for match in re.finditer(r"阴性|阳性", tail)]
    if len(tokens) < count:
        return None
    return ["negative" if token == "阴性" else "positive" for token in tokens[:count]]


def _has_generic_parasitological_event(surface: str) -> bool:
    return _has_any(
        surface,
        ("寄生虫学", "病原学", "病原检查", "送检", "查卵", "虫卵"),
    ) and (
        _has_any(surface, _DETECTION_ACTION_MARKERS)
        or _is_negative_observation(surface)
    )


def _evidence_clauses(query: str, index: RetrievalIndex) -> list[str]:
    """Preserve event boundaries before punctuation is removed."""
    raw_parts = re.split(r"[，,；;。！？!?]", query.lower())
    clauses: list[str] = []
    for raw in raw_parts:
        pending = [raw]
        for marker in ("然而", "随后", "后来", "同时", "但是", "但", "而"):
            next_pending: list[str] = []
            for item in pending:
                position = item.find(marker)
                if position < 0:
                    next_pending.append(item)
                    continue
                left = _surface_query(item[:position])
                right = _surface_query(item[position + len(marker):])
                if (
                    (
                        _diagnostic_method_occurrences(left, index)
                        or _has_generic_parasitological_event(left)
                    )
                    and (
                        _diagnostic_method_occurrences(right, index)
                        or _has_generic_parasitological_event(right)
                    )
                ):
                    next_pending.extend([item[:position], item[position + len(marker):]])
                else:
                    next_pending.append(item)
            pending = next_pending
        clauses.extend(
            normalized for item in pending
            if (normalized := _surface_query(item))
        )
    return clauses


def _query_evidence_observations(
    query: str, surface: str, entities: set[str], index: RetrievalIndex
) -> tuple[EvidenceObservation, ...]:
    observations: list[EvidenceObservation] = []
    last_pathogen_method: str | None = None
    for clause in _evidence_clauses(query, index):
        occurrences = _diagnostic_method_occurrences(clause, index)
        coordinated = _coordinated_polarities(clause, len(occurrences))
        clause_has_pathogen_method = False
        for method_index, (entity_id, window) in enumerate(
            _method_windows(clause, occurrences)
        ):
            roles = _roles_for_entities({entity_id}, index)
            evidence_role = next(
                (
                    mapped
                    for formal, mapped in _FORMAL_ROLE_TO_EVIDENCE_ROLE.items()
                    if formal in roles
                ),
                "pathogen_confirmation",
            )
            polarity = coordinated[method_index] if coordinated else (
                "negative" if _is_negative_observation(window)
                else "positive" if _is_positive_observation(window)
                else "unspecified"
            )
            event_type = (
                "imaging_observation"
                if evidence_role == "imaging_auxiliary_clue"
                else "parasitological_test"
            )
            if evidence_role == "pathogen_confirmation":
                clause_has_pathogen_method = True
                last_pathogen_method = entity_id
            observations.append(EvidenceObservation(
                observation_id=f"OBS-{len(observations) + 1:02d}",
                evidence_entity_id=entity_id,
                evidence_role=evidence_role,
                polarity=polarity,
                event_type=event_type,
                semantic_roles=tuple(sorted(roles)),
            ))
        if not clause_has_pathogen_method and _has_generic_parasitological_event(clause):
            polarity = (
                "negative" if _is_negative_observation(clause)
                else "positive" if _is_positive_observation(clause)
                else "unspecified"
            )
            bound_entity = last_pathogen_method
            bound_roles = (
                tuple(sorted(_roles_for_entities({bound_entity}, index)))
                if bound_entity else ("parasitological_confirmation",)
            )
            replacement_index = next(
                (
                    index_number
                    for index_number in range(len(observations) - 1, -1, -1)
                    if observations[index_number].evidence_entity_id == bound_entity
                    and observations[index_number].polarity == "unspecified"
                    and bound_entity is not None
                ),
                None,
            )
            observation = EvidenceObservation(
                observation_id=(
                    observations[replacement_index].observation_id
                    if replacement_index is not None
                    else f"OBS-{len(observations) + 1:02d}"
                ),
                evidence_entity_id=bound_entity,
                evidence_role="pathogen_confirmation",
                polarity=polarity,
                event_type="parasitological_test",
                semantic_roles=bound_roles,
            )
            if replacement_index is None:
                observations.append(observation)
            else:
                observations[replacement_index] = observation

    has_exposure_observation = False
    for entity_id in sorted(entities):
        if index.entities[entity_id].get("entity_type") != "behavior":
            continue
        roles = _roles_for_entities({entity_id}, index)
        if "epidemiological_clue" not in roles:
            continue
        if _has_any(surface, _CONTROL_MARKERS) and not _has_any(
            surface,
            ("诊断", "确诊", "确证", "病原学", "寄生虫学", "线索",
             "流行区", "流行地区", "暴露史"),
        ):
            continue
        observations.append(EvidenceObservation(
            observation_id=f"OBS-{len(observations) + 1:02d}",
            evidence_entity_id=entity_id,
            evidence_role="epidemiologic_exposure_clue",
            polarity="positive",
            event_type="exposure_history",
            semantic_roles=tuple(sorted(roles)),
        ))
        has_exposure_observation = True
    if (
        not has_exposure_observation
        and _has_any(surface, _EPIDEMIOLOGIC_EXPOSURE_MARKERS)
        and _has_any(surface, _NONCONFIRMATORY_QUERY_MARKERS)
    ):
        observations.append(EvidenceObservation(
            observation_id=f"OBS-{len(observations) + 1:02d}",
            evidence_entity_id=None,
            evidence_role="epidemiologic_exposure_clue",
            polarity="positive",
            event_type="exposure_history",
            semantic_roles=("epidemiological_clue", "not_confirmatory"),
        ))
    return tuple(observations)


def _detect_entities(surface: str, index: RetrievalIndex) -> set[str]:
    detected: set[str] = set()
    for entity_id, entity in index.entities.items():
        if any(alias and alias in surface for alias in _formal_entity_aliases(entity)):
            detected.add(entity_id)

    # Query-language composition chooses among formally typed reviewed entities.
    # It never creates a runtime fact or a synthetic entity.
    if _has_any(surface, ("犬", "猫", "猪", "家畜", "家养动物", "动物宿主", "人畜")):
        for entity_id in _entities_with_type(index, "host"):
            formal = " ".join(_formal_entity_aliases(index.entities[entity_id]))
            if any(term in formal for term in ("犬", "猫", "猪", "食鱼哺乳动物")):
                detected.add(entity_id)

    raw_food = _has_any(
        surface,
        ("生食", "未充分加热", "生鱼", "鱼生", "没煮熟", "吃生", "生河鱼"),
    )
    if raw_food:
        for entity_id in _entities_with_type(index, "behavior"):
            formal = normalize_query(_entity_search_text(index.entities[entity_id]))
            if _has_any(formal, ("生食", "未充分加热")):
                detected.add(entity_id)
        if _has_any(surface, ("避免", "不吃", "拒绝", "预防", "防控")):
            for entity_id in _entities_with_type(index, "intervention"):
                formal = normalize_query(_entity_search_text(index.entities[entity_id]))
                if "避免食用生或未充分加热淡水鱼" in formal:
                    detected.add(entity_id)

    if _has_any(surface, _CONTROL_MARKERS):
        for entity_id in _entities_with_type(index, "intervention"):
            formal = normalize_query(_entity_search_text(index.entities[entity_id]))
            if "改善卫生设施" in formal and _has_any(
                surface, ("卫生", "改厕", "厕所", "社区排污")
            ):
                detected.add(entity_id)
            if "减少人粪便污染" in formal and _has_any(
                surface, ("人粪", "社区排污", "人畜粪污", "人畜排卵")
            ):
                detected.add(entity_id)
            if "减少动物粪便污染" in formal and _has_any(
                surface, ("动物", "家畜", "犬猫猪", "人畜粪污", "人畜排卵")
            ):
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

    detected.update(_detect_diagnostic_methods(surface, index))
    return {entity_id for entity_id in detected if entity_id in index.entities}


def _has_negated_morphology_intent(surface: str) -> bool:
    return any(pattern.search(surface) for pattern in _MORPHOLOGY_NEGATION_PATTERNS)


def _event_relation_intents(
    surface: str,
    entities: set[str],
    evidence_observations: tuple[EvidenceObservation, ...],
    index: RetrievalIndex,
) -> set[str]:
    """Map query events onto predicates that exist in the reviewed graph."""
    intents: set[str] = set()
    entity_types = {
        index.entities[entity_id].get("entity_type") for entity_id in entities
    }
    stage_entities = {
        entity_id for entity_id in entities
        if index.entities[entity_id].get("entity_type") == "life_cycle_stage"
    }
    host_entities = {
        entity_id for entity_id in entities
        if index.entities[entity_id].get("entity_type") == "host"
    }

    if evidence_observations:
        if any(
            item.event_type in {"parasitological_test", "imaging_observation"}
            for item in evidence_observations
        ):
            intents.update({"diagnosed_by", "diagnostic_stage_for"})
        if any(item.event_type == "exposure_history" for item in evidence_observations):
            intents.add("has_diagnostic_clue")

    stage_event_language = (
        bool(stage_entities)
        or _has_any(
            surface,
            ("幼体", "成体", "后代", "虫态", "虫期", "虫体", "发育", "变化",
             "转换", "形成", "成熟", "演替"),
        )
    )
    life_event = "生活史" in surface or (
        (
            _has_any(surface, _SEQUENCE_MARKERS)
            or _has_any(surface, _LIFE_CYCLE_EVENT_MARKERS)
            or _has_any(surface, ("连续变化", "完整发育", "虫期变化", "虫态转换"))
        )
        and stage_event_language
    )
    if life_event:
        intents.add("develops_into")

    host_relation_context = life_event or _has_any(
        surface, (*_CONNECTION_MARKERS, "宿主", "承载", "水生动物")
    )
    if host_relation_context and _has_any(
        surface, ("螺", "软体动物", "第一中间宿主")
    ):
        intents.add("has_first_intermediate_host")
    if host_relation_context and _has_any(
        surface,
        ("淡水鱼", "鱼体", "入鱼", "第二中间宿主", "螺和鱼", "螺鱼"),
    ):
        intents.add("has_second_intermediate_host")
    if _has_any(surface, ("终宿主", "食鱼哺乳动物")):
        intents.add("has_definitive_host")
    if _has_any(surface, ("保虫宿主", "储存宿主")):
        intents.add("has_reservoir_host")

    network_intent = _has_any(surface, _CONNECTION_MARKERS)
    has_snail = _has_any(surface, ("螺", "软体动物"))
    has_fish = _has_any(surface, ("鱼", "水生动物"))
    has_human_or_animal = _has_any(
        surface, ("人", "感染者", "食鱼者", "犬", "猫", "猪", "家畜", "人畜")
    )
    if network_intent and has_snail and has_fish and has_human_or_animal:
        intents.update({
            "has_first_intermediate_host", "has_second_intermediate_host",
            "sheds_stage", "present_in_environment", "transmitted_via",
        })
        if _has_any(
            surface, ("犬", "猫", "猪", "家畜", "家养动物", "动物", "人畜")
        ):
            intents.add("has_reservoir_host")
    if network_intent and _has_any(surface, ("水生生态系统", "水生系统")) and _has_any(
        surface, ("人", "家畜", "动物", "人畜")
    ):
        intents.update({
            "has_first_intermediate_host", "has_second_intermediate_host",
            "has_reservoir_host", "sheds_stage", "present_in_environment",
            "transmitted_via",
        })
    if network_intent and _has_any(surface, ("人", "人类")) and _has_any(
        surface, ("动物", "家畜", "人畜")
    ) and _has_any(surface, ("淡水环境", "水环境", "水体", "水域")):
        intents.update({
            "has_first_intermediate_host", "has_second_intermediate_host",
            "has_reservoir_host", "sheds_stage", "present_in_environment",
            "transmitted_via",
        })
    if _has_any(surface, ("水生动物", "水生宿主")) and _has_any(
        surface, ("承载", "幼虫", "先后", "宿主")
    ):
        intents.update({"has_first_intermediate_host", "has_second_intermediate_host"})
    if _has_any(surface, ("人", "犬", "猫", "食鱼动物")) and _has_any(
        surface, ("终宿主", "繁殖", "成体", "处于什么位置")
    ):
        intents.add("has_definitive_host")

    if _has_any(surface, _SHEDDING_EVENT_MARKERS):
        intents.add("sheds_stage")
    if _has_any(surface, _ENVIRONMENT_EVENT_MARKERS) and (
        "sheds_stage" in intents
        or _has_any(surface, ("虫卵", "后代", "排泄物", "粪", "污染"))
    ):
        intents.add("present_in_environment")
    if _has_any(surface, ("食鱼行为", "生食", "未充分加热")) and _has_any(
        surface, ("传播", "感染", "回到人", "摄入", "食入")
    ):
        intents.add("transmitted_via")
    if _has_any(surface, _HOST_INGESTION_MARKERS) and _has_any(
        surface, ("感染人", "可感染人", "被人", "建立感染", "感染阶段", "包囊")
    ):
        intents.add("infective_stage_for")
    if _has_any(surface, _PARASITISM_EVENT_MARKERS):
        intents.add("parasitizes_site")

    infection_intent = _has_any(surface, _INFECTION_MARKERS)
    pathogenic_intent = _has_any(surface, _PATHOGENIC_MARKERS)
    if infection_intent and _has_any(surface, ("阶段", "虫期", "虫态", "包囊")):
        intents.add("infective_stage_for")
    if pathogenic_intent and _has_any(
        surface, ("阶段", "虫期", "虫态", "成虫", "形态")
    ):
        intents.add("pathogenic_stage_for")

    control_intent = "intervention" in entity_types or _has_any(
        surface, _CONTROL_MARKERS
    )
    if control_intent:
        intents.add("controlled_by")
    target_mechanism = _has_any(surface, _ENVIRONMENT_EVENT_MARKERS) or _has_any(
        surface, ("靶点", "传播环节", "机制", "粪污", "排污")
    )
    target_actor = _has_any(
        surface,
        ("人粪", "动物", "家畜", "犬", "猫", "猪", "排泄物", "粪污",
         "人畜排卵", "排卵污染", "社区排污"),
    )
    sanitation_boundary = (
        "intervention.improved_sanitation" in entities
        and _has_any(surface, _BOUNDARY_MARKERS)
    )
    if control_intent and ((target_mechanism and target_actor) or sanitation_boundary):
        intents.add("targets")

    if _has_any(surface, _TREATMENT_MARKERS) or "treatment" in entity_types:
        intents.add("treated_by")
    if _has_any(surface, _CARCINOGENIC_MARKERS) or "hazard_classification" in entity_types:
        intents.add("classified_as")
    return intents


def _relation_record_relevant(
    record: ClaimRecord,
    surface: str,
    entities: set[str],
    index: RetrievalIndex,
) -> bool:
    """Bind an activated predicate to the entities/events present in this query."""
    predicate = record.predicate
    if predicate == "develops_into":
        return True
    if predicate in {
        "has_first_intermediate_host", "has_second_intermediate_host",
        "has_definitive_host", "has_reservoir_host", "present_in_environment",
        "infective_stage_for", "pathogenic_stage_for", "parasitizes_site",
        "diagnostic_stage_for",
    }:
        return True
    if predicate == "diagnosed_by":
        return bool(set(record.entity_ids) & entities) or _has_any(
            surface, ("病原学", "寄生虫学", "确证", "直接病原体", "虫卵")
        )
    if predicate == "has_diagnostic_clue":
        return bool(set(record.entity_ids) & entities) or _has_any(
            surface, ("流行区", "暴露史", "流行病学", "辅助线索")
        )
    if predicate == "sheds_stage":
        actor_entities = {
            entity_id for entity_id in entities
            if index.entities[entity_id].get("entity_type") == "host"
        }
        if record.subject in actor_entities:
            return True
        subject_text = normalize_query(_entity_search_text(index.entities[record.subject]))
        if "人" in subject_text and "人" in surface:
            return True
        if _has_any(subject_text, ("犬", "猫", "猪")) and _has_any(
            surface, ("动物", "家畜", "家养动物", "犬", "猫", "猪", "人畜")
        ):
            return True
        return not actor_entities
    if predicate == "transmitted_via":
        return bool(set(record.entity_ids) & entities) or _has_any(
            surface, ("食鱼行为", "食鱼者", "生食", "未充分加热", "饮食回到")
        ) or (
            _has_any(surface, _CONNECTION_MARKERS)
            and _has_any(surface, ("鱼", "水生生态系统"))
            and _has_any(surface, ("人", "动物", "家畜", "食鱼者", "人畜"))
        ) or (
            _has_any(surface, _CONNECTION_MARKERS)
            and _has_any(surface, ("人", "人类"))
            and _has_any(surface, ("动物", "家畜", "人畜"))
            and _has_any(surface, ("淡水环境", "水环境", "水体", "水域"))
        )
    if predicate in {"treated_by", "classified_as"}:
        return not entities or bool(set(record.entity_ids) & entities)
    if predicate == "controlled_by":
        if record.object in entities:
            return True
        object_text = normalize_query(_entity_search_text(index.entities[record.object]))
        if "onehealth综合防控" in object_text:
            return _has_any(
                surface,
                ("综合治理", "综合防控", "协同治理", "人动物和环境", "人畜环境"),
            ) or (
                _has_any(surface, _BOUNDARY_MARKERS)
                and _has_any(surface, ("人粪", "社区排污", "人畜"))
                and _has_any(surface, ("动物", "家畜", "犬", "猫", "猪"))
            )
        if "改善卫生设施" in object_text:
            return _has_any(surface, ("卫生设施", "改厕", "厕所", "改进卫生"))
        if "避免食用生或未充分加热淡水鱼" in object_text:
            return _has_any(surface, ("避免生食", "避免食用", "不吃生鱼"))
        return False
    if predicate == "targets":
        if record.subject in entities:
            return True
        subject_text = normalize_query(_entity_search_text(index.entities[record.subject]))
        if "减少人粪便污染" in subject_text:
            return _has_any(
                surface,
                ("人粪", "人的排泄物", "人类排泄物", "人畜排卵",
                 "排卵污染", "社区排污", "人畜粪污"),
            ) or (
                "intervention.improved_sanitation" in entities
                and _has_any(surface, _BOUNDARY_MARKERS)
            )
        if "减少动物粪便污染" in subject_text:
            return _has_any(
                surface,
                ("动物排泄物", "家养动物排泄物", "动物粪便", "粪污",
                 "犬猫猪", "人畜排卵", "排卵污染", "人畜粪污"),
            )
        return False
    return bool(set(record.entity_ids) & entities)


def _relation_activations(
    surface: str,
    entities: set[str],
    relation_intents: set[str],
    index: RetrievalIndex,
) -> tuple[RelationActivation, ...]:
    activations = [
        RelationActivation(
            claim_id=record.claim_id,
            predicate=record.predicate,
            semantic_roles=record.semantic_roles,
        )
        for record in index.records
        if record.predicate in relation_intents
        and _relation_record_relevant(record, surface, entities, index)
    ]
    return tuple(sorted(activations, key=lambda item: item.claim_id))


def analyze_query(query: str, index: RetrievalIndex) -> QueryPlan:
    """Build a deterministic, relation-bound plan over the reviewed graph."""
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
    evidence_observations = _query_evidence_observations(
        query, surface, entities, index
    )
    semantic_roles = {
        role
        for observation in evidence_observations
        for role in observation.semantic_roles
    }
    evidence_roles = {
        observation.evidence_role for observation in evidence_observations
    }
    evidence_roles.update(
        evidence_role
        for formal_role, evidence_role in _FORMAL_ROLE_TO_EVIDENCE_ROLE.items()
        if formal_role in semantic_roles
    )
    negated_evidence_roles = {
        observation.evidence_role
        for observation in evidence_observations
        if observation.polarity == "negative"
    }

    topics: set[str] = set()
    clinical_differential = _has_any(surface, _CLINICAL_DIFFERENTIAL_MARKERS)
    morphology_intent = (
        _has_any(surface, _MORPHOLOGY_MARKERS)
        or ("鉴别" in surface and _has_any(surface, _MORPHOLOGY_ANCHORS))
    ) and not clinical_differential and not _has_negated_morphology_intent(surface)
    if morphology_intent and (
        stages or _has_any(surface, ("成虫", "虫卵", "虫体", "卵壳"))
    ):
        topics.add("morphology")

    relation_intents = _event_relation_intents(
        surface, entities, evidence_observations, index
    )
    if "develops_into" in relation_intents or "生活史" in surface:
        topics.add("life_cycle")
    transmission_predicates = {
        "has_first_intermediate_host", "has_second_intermediate_host",
        "has_definitive_host", "has_reservoir_host", "sheds_stage",
        "present_in_environment", "transmitted_via", "infective_stage_for",
        "parasitizes_site",
    }
    if relation_intents & transmission_predicates and _has_any(
        surface,
        ("传播", "链", "水域", "淡水", "排出", "排卵", "摄取", "摄入",
         "感染人", "回到人", "宿主环节", "进入鱼", "进入水"),
    ):
        topics.add("transmission")
    if {
        "has_first_intermediate_host", "has_second_intermediate_host"
    } <= relation_intents and (
        "sheds_stage" in relation_intents or "present_in_environment" in relation_intents
    ):
        topics.add("life_cycle")
        topics.add("transmission")
    if _has_any(surface, ("宿主", "第一中间", "第二中间", "终宿主", "保虫")) or (
        relation_intents
        & {
            "has_first_intermediate_host", "has_second_intermediate_host",
            "has_definitive_host", "has_reservoir_host",
        }
        and _has_any(surface, ("承载", "处于什么位置", "分别是什么", "分工"))
    ):
        topics.add("host_roles")

    actor_groups: set[str] = set()
    if "host.human" in entities or "人" in surface:
        actor_groups.add("human")
    if any(
        _has_any(
            normalize_query(_entity_search_text(index.entities[item])),
            ("犬", "猫", "猪", "食鱼哺乳动物"),
        )
        for item in hosts
    ) or _has_any(surface, ("动物", "人畜")):
        actor_groups.add("animal")
    if any("螺" in index.entities[item].get("name_zh", "") for item in hosts):
        actor_groups.add("snail")
    if any("鱼" in index.entities[item].get("name_zh", "") for item in hosts):
        actor_groups.add("fish")
    if "environment" in entity_types or _has_any(
        surface, ("环境", "水体", "河塘", "水域", "淡水")
    ):
        actor_groups.add("environment")
    if (
        len(actor_groups) >= 4
        or _has_any(surface, ("onehealth", "全健康", "人动物和环境", "人畜环境"))
    ):
        topics.add("one_health")

    if any(
        observation.evidence_role == "epidemiologic_exposure_clue"
        for observation in evidence_observations
    ):
        topics.add("exposure")
    if "intervention" in entity_types or _has_any(surface, _CONTROL_MARKERS):
        topics.add("control")
    if "control" in topics and _has_any(surface, _BOUNDARY_MARKERS):
        topics.add("boundary")
    if _has_any(surface, _TREATMENT_MARKERS) or "treatment" in entity_types:
        topics.add("treatment")
    if _has_any(surface, _CARCINOGENIC_MARKERS) or "hazard_classification" in entity_types:
        topics.add("carcinogenicity")
    if (
        "infective_stage_for" in relation_intents
        and "pathogenic_stage_for" in relation_intents
    ):
        topics.add("stage_roles")
    if _has_any(surface, _SOURCE_MARKERS):
        topics.add("source_traceability")

    diagnostic_role = bool(
        semantic_roles
        & (set(_FORMAL_ROLE_TO_EVIDENCE_ROLE) | _DIAGNOSTIC_CONTRAST_ROLES)
    )
    if evidence_observations and any(
        item.event_type != "exposure_history" for item in evidence_observations
    ):
        topics.add("diagnosis")
    if diagnostic_role or _has_any(surface, _DIAGNOSIS_MARKERS):
        if evidence_roles or clinical_differential or "diagnosed_by" in relation_intents:
            topics.add("diagnosis")

    required_evidence_roles: set[str] = set()
    if semantic_roles & _DIAGNOSTIC_CONTRAST_ROLES:
        required_evidence_roles.add("pathogen_confirmation")
    if _has_any(surface, _NONCONFIRMATORY_QUERY_MARKERS):
        required_evidence_roles.add("pathogen_confirmation")
    if required_evidence_roles:
        evidence_roles.update(required_evidence_roles)
        topics.add("diagnosis")
        relation_intents.update({"diagnosed_by", "diagnostic_stage_for"})

    # Preserve established complete groups where their topic is actually active;
    # transmission, exposure and control remain event-selective.
    broad_group_topics = {
        "morphology", "diagnosis", "stage_roles", "treatment",
        "carcinogenicity",
    }
    for topic in topics & broad_group_topics:
        group = _TOPIC_TO_GROUP[topic]
        relation_intents.update(_GROUP_PREDICATES.get(group, ()))

    activations = _relation_activations(
        surface, entities, relation_intents, index
    )
    semantic_roles.update(
        role for activation in activations for role in activation.semantic_roles
    )
    control_semantic_roles = {
        role
        for activation in activations
        if activation.predicate in {"controlled_by", "targets"}
        for role in activation.semantic_roles
    }
    if control_semantic_roles:
        semantic_roles.update(control_semantic_roles)
        topics.add("control")
        if control_semantic_roles & {
            "recommendation_not_local_effect", "recommendation_not_quantified_effect",
            "universal_elimination_claim_false",
        } or _has_any(surface, _BOUNDARY_MARKERS):
            topics.add("boundary")

    if semantic_roles & _DIAGNOSTIC_CONTRAST_ROLES:
        required_evidence_roles.add("pathogen_confirmation")
        evidence_roles.add("pathogen_confirmation")
        topics.add("diagnosis")
        relation_intents.update({"diagnosed_by", "diagnostic_stage_for"})
        activations = _relation_activations(
            surface, entities, relation_intents, index
        )

    ordered_topics = tuple(item for item in _TOPIC_ORDER if item in topics)
    coverage_groups = tuple(dict.fromkeys(
        _TOPIC_TO_GROUP[item]
        for item in ordered_topics
        if item in _TOPIC_TO_GROUP
        and not (
            item == "life_cycle" and "develops_into" not in relation_intents
        )
    ))
    return QueryPlan(
        normalized_surface=surface,
        entity_ids=tuple(sorted(entities)),
        entity_types=tuple(sorted(entity_types)),
        relation_intents=tuple(sorted(relation_intents)),
        semantic_roles=tuple(sorted(semantic_roles)),
        evidence_roles=tuple(sorted(evidence_roles)),
        negated_evidence_roles=tuple(sorted(negated_evidence_roles)),
        required_evidence_roles=tuple(sorted(required_evidence_roles)),
        evidence_observations=evidence_observations,
        relation_activations=activations,
        control_semantic_roles=tuple(sorted(control_semantic_roles)),
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
    activated_ids = {
        activation.claim_id for activation in plan.relation_activations
    }
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
        elif group in {
            "one_health_transmission", "event_transmission",
            "exposure_evidence", "control_measures",
        }:
            predicates = set(_GROUP_PREDICATES[group])
            selected = sorted(
                (
                    item for item in records
                    if item.claim_id in activated_ids
                    and item.predicate in predicates
                ),
                key=lambda item: item.claim_id,
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
            observed_entities = {
                observation.evidence_entity_id
                for observation in plan.evidence_observations
                if observation.evidence_entity_id
            }
            selected = sorted(
                {item.claim_id: item for item in selected}.values(),
                key=lambda item: (
                    0 if set(item.entity_ids) & observed_entities else 1,
                    item.claim_id,
                ),
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
    records_by_id = {record.claim_id: record for record in index.records}

    # First reserve capacity across each actually activated graph predicate.
    # Round-robin prevents the first broad topic from consuming all Top12 slots.
    predicate_buckets: dict[str, list[ClaimRecord]] = {}
    for activation in plan.relation_activations:
        predicate_buckets.setdefault(activation.predicate, []).append(
            records_by_id[activation.claim_id]
        )
    for predicate, bucket in predicate_buckets.items():
        if predicate == "develops_into":
            predicate_buckets[predicate] = _ordered_life_cycle(bucket)
        else:
            predicate_buckets[predicate] = sorted(
                bucket,
                key=lambda record: (
                    -_score_record(request["query_text"], record, plan)[0],
                    record.claim_id,
                ),
            )
    relation_priority = {
        "has_first_intermediate_host": 10,
        "has_second_intermediate_host": 20,
        "sheds_stage": 30,
        "present_in_environment": 40,
        "transmitted_via": 50,
        "infective_stage_for": 60,
        "parasitizes_site": 70,
        "targets": 80,
        "controlled_by": 90,
        "diagnosed_by": 100,
        "has_diagnostic_clue": 110,
        "diagnostic_stage_for": 120,
        "pathogenic_stage_for": 130,
        "has_definitive_host": 140,
        "has_reservoir_host": 150,
        "treated_by": 160,
        "classified_as": 170,
        "develops_into": 0,
    }
    predicate_order = sorted(
        predicate_buckets,
        key=lambda predicate: (relation_priority.get(predicate, 999), predicate),
    )
    # A reviewed development path is an indivisible coverage constraint.
    # Reserve the complete ordered path before distributing the remaining slots.
    for record in predicate_buckets.get("develops_into", []):
        if len(coverage) >= top_k:
            break
        coverage.append((record, "relation:develops_into"))
        covered_ids.add(record.claim_id)
    predicate_order = [
        predicate for predicate in predicate_order if predicate != "develops_into"
    ]
    offset = 0
    while len(coverage) < top_k and any(
        offset < len(predicate_buckets[predicate])
        for predicate in predicate_order
    ):
        for predicate in predicate_order:
            bucket = predicate_buckets[predicate]
            if offset >= len(bucket):
                continue
            record = bucket[offset]
            if record.claim_id not in covered_ids:
                coverage.append((record, f"relation:{predicate}"))
                covered_ids.add(record.claim_id)
                if len(coverage) >= top_k:
                    break
        offset += 1

    # Then share remaining capacity across semantic coverage groups.
    group_order = list(plan.coverage_groups)
    offset = 0
    while len(coverage) < top_k and any(
        offset < len(groups.get(group, [])) for group in group_order
    ):
        for group in group_order:
            bucket = groups.get(group, [])
            if offset >= len(bucket):
                continue
            record = bucket[offset]
            if record.claim_id not in covered_ids:
                coverage.append((record, group))
                covered_ids.add(record.claim_id)
                if len(coverage) >= top_k:
                    break
        offset += 1

    for record in groups.get("entity_neighborhood", []):
        if len(coverage) >= top_k:
            break
        if record.claim_id not in covered_ids:
            coverage.append((record, "entity_neighborhood"))
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
