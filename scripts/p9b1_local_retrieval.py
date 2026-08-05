#!/usr/bin/env python3
"""Deterministic, allowlist-only evidence retrieval for Clonorchis PCMS v1.

P9-B1 deliberately does not call a model, the network, or student data.  Every
public retrieval and every public result validation rebuilds a verified index
from the four P9-A allowlisted files.  Callers cannot inject an index.
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
FROZEN_RUNTIME_CONTRACT_SHA256 = "f4b2712a1b7cd4a1bce0093a8a4c3a717fecee04ab540434fb3c3ce0539d4a5f"
FROZEN_REQUEST_SCHEMA_SHA256 = "da98c6e6427a52cb17501177da6aa97c73c7417edbec39b019d1b46b4fcdbd56"
FROZEN_RESULT_SCHEMA_SHA256 = "3a44d7d457af16f4850ab812b009e59b10fdd5255ca920bb913670d1bb7ae4d6"
FROZEN_RETRIEVAL_CONTRACT_SHA256 = "3d5ce4bd018fd3714f349daa48739a51e7ed0ca741d9916e343cf1bdb601e7d4"

ALLOWED_RUNTIME_INPUTS = (
    "derived/clonorchis-sinensis/pcms-v1/nodes.jsonl",
    "derived/clonorchis-sinensis/pcms-v1/edges.jsonl",
    "phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml",
    "sources/registry.yml",
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


def build_index(root: Path = ROOT) -> RetrievalIndex:
    """Build and seal an index after all P9-A/P9-B1 authority checks pass."""
    manifest = verify_runtime_bundle(root)
    control = _verify_control_files(root)
    nodes = _load_jsonl(root / ALLOWED_RUNTIME_INPUTS[0])
    edges = _load_jsonl(root / ALLOWED_RUNTIME_INPUTS[1])
    review = _read_yaml(root / ALLOWED_RUNTIME_INPUTS[2])
    registry = _read_yaml(root / ALLOWED_RUNTIME_INPUTS[3])
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
            entity_ids=(subject, object_id), statement_zh=edge["statement_zh"],
            qualifiers=qualifiers, citations=citations, search_text=search,
        ))
        for supporting_id in source_qualifiers.get("supporting_narrative_atom_ids", []):
            records.append(ClaimRecord(
                claim_id=supporting_id, claim_kind="supporting_narrative",
                subject=subject, predicate=edge.get("predicate"), object=object_id,
                entity_ids=(subject, object_id), statement_zh=edge["statement_zh"],
                qualifiers={**qualifiers, "supporting_for": claim_id},
                citations=citations, search_text=search,
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


CONCEPT_RULES: dict[str, dict[str, Any]] = {
    "morphology": {
        "terms": ("形态", "识别", "外形", "大小", "尺寸", "卵盖", "肩峰", "小疣", "成虫和虫卵"),
        "claim_kind": ("narrative",),
    },
    "life_cycle_order": {
        "terms": ("生活史", "发育", "顺序", "阶段", "衔接", "过程"),
        "predicates": ("develops_into",),
    },
    "host_roles": {
        "terms": ("宿主", "中间宿主", "终宿主", "保虫宿主", "宿主分别", "宿主角色", "淡水鱼和淡水虾", "鱼虾"),
        "predicates": ("has_first_intermediate_host", "has_second_intermediate_host", "has_definitive_host", "has_reservoir_host"),
    },
    "one_health_chain": {
        "terms": ("传播链", "传播网络", "连接", "粪便", "螺", "水体", "动物", "环境", "onehealth"),
        "min_terms": 3,
        "predicates": ("has_first_intermediate_host", "has_second_intermediate_host", "has_reservoir_host", "sheds_stage", "present_in_environment", "transmitted_via", "targets"),
    },
    "diagnosis": {
        "terms": ("诊断", "确诊", "确证", "检卵", "影像", "生食鱼史"),
        "predicates": ("diagnosed_by", "has_diagnostic_clue", "diagnostic_stage_for"),
    },
    "treatment": {
        "terms": ("治疗", "药物", "吡喹酮", "阿苯达唑", "三苯双脒"),
        "predicates": ("treated_by",),
    },
    "carcinogenic": {
        "terms": ("致癌", "癌症", "胆管癌", "iarc", "group1", "危害分类"),
        "predicates": ("classified_as",),
    },
    "source_traceability": {
        "terms": ("来源", "权威", "资料", "依据", "溯源"),
        "source_bonus": True,
    },
    "infection_pathogenic_stage": {
        "terms": ("感染阶段", "致病阶段", "进入人体", "造成感染", "导致病变"),
        "predicates": ("infective_stage_for", "pathogenic_stage_for"),
    },
    "control": {
        "terms": ("防控", "预防", "卫生", "兽医", "消除"),
        "predicates": ("controlled_by", "targets"),
    },
}


def _contains_term(normalized: str, term: str) -> bool:
    return normalize_query(term) in normalized


def _ngrams(text: str, size: int) -> set[str]:
    if len(text) < size:
        return {text} if text else set()
    return {text[index:index + size] for index in range(len(text) - size + 1)}


def _score_record(query: str, record: ClaimRecord) -> tuple[int, list[str]]:
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

    active: set[str] = set()
    for concept, rule in CONCEPT_RULES.items():
        matched_terms = sum(
            _contains_term(normalized, term) for term in rule["terms"]
        )
        if matched_terms >= rule.get("min_terms", 1):
            active.add(concept)
            if record.predicate in rule.get("predicates", ()):
                score += 120
                features.append(f"concept:{concept}")
            if record.claim_kind in rule.get("claim_kind", ()):
                score += 120
                features.append(f"concept:{concept}")

    # Source questions need one representative from each requested semantic area,
    # but no claim ID is encoded here: the boost is predicate based.
    if "source_traceability" in active:
        if record.predicate in {"develops_into", "treated_by", "classified_as"}:
            score += 80
            features.append("source_traceability")

    if "life_cycle_order" in active and record.predicate == "has_life_cycle_stage":
        score += 25
        features.append("life_cycle_context")
    if "one_health_chain" in active and record.predicate == "controlled_by":
        score += 15
        features.append("one_health_context")

    return score, sorted(set(features))


def _rank(
    request: dict[str, Any], index: RetrievalIndex, top_k: int
) -> tuple[list[dict[str, Any]], int]:
    scored: list[tuple[int, str, ClaimRecord, list[str]]] = []
    for record in index.records:
        score, features = _score_record(request["query_text"], record)
        if score > 0:
            scored.append((score, record.claim_id, record, features))
    scored.sort(key=lambda item: (-item[0], item[1]))
    candidates: list[dict[str, Any]] = []
    for rank, (score, _, record, features) in enumerate(scored[:top_k], 1):
        candidates.append({
            "rank": rank,
            "score": score,
            "score_features": features,
            **record.payload(),
        })
    return candidates, len(index.records) - len(scored)


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
