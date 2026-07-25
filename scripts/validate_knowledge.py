#!/usr/bin/env python3
"""Validate structured Markdown knowledge entities and their source references."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REQUIRED_FIELDS = {
    "schema_version",
    "id",
    "entity_type",
    "name_zh",
    "aliases",
    "one_health_domains",
    "summary",
    "review_status",
    "relations",
    "review",
}

REQUIRED_HEADINGS = {
    "## 核心知识",
    "## One Health联系",
    "## 学习提示",
    "## 证据边界",
}


@dataclass
class Finding:
    level: str
    path: Path
    message: str


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("YAML root must be a mapping")
    return data


def parse_markdown(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing opening YAML front matter delimiter")
    marker = "\n---\n"
    end = text.find(marker, 4)
    if end < 0:
        raise ValueError("missing closing YAML front matter delimiter")
    metadata = yaml.safe_load(text[4:end])
    if not isinstance(metadata, dict):
        raise ValueError("front matter must be a mapping")
    return metadata, text[end + len(marker) :]


def load_catalogs(root: Path) -> dict[str, Any]:
    entity_catalog = load_yaml(root / "schema" / "entity-types.yml")
    relation_catalog = load_yaml(root / "schema" / "relation-types.yml")
    source_catalog = load_yaml(root / "schema" / "source-types.yml")
    return {
        "entity": entity_catalog,
        "relation": relation_catalog,
        "source": source_catalog,
    }


def validate_source_registry(
    path: Path, catalogs: dict[str, Any]
) -> tuple[set[str], list[Finding]]:
    findings: list[Finding] = []
    try:
        registry = load_yaml(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return set(), [Finding("ERROR", path, f"cannot load source registry: {exc}")]

    sources = registry.get("sources")
    if not isinstance(sources, list):
        return set(), [Finding("ERROR", path, "sources must be a list")]

    allowed_types = set(catalogs["source"]["source_types"])
    allowed_roles = set(catalogs["source"]["source_roles"])
    allowed_access = set(catalogs["source"]["access_levels"])
    allowed_full_text = set(catalogs["source"]["full_text_statuses"])
    source_ids: set[str] = set()

    for index, source in enumerate(sources):
        where = f"sources[{index}]"
        if not isinstance(source, dict):
            findings.append(Finding("ERROR", path, f"{where} must be a mapping"))
            continue
        required = {
            "source_id",
            "source_type",
            "title",
            "roles",
            "access_level",
            "full_text_status",
        }
        missing = sorted(required - set(source))
        if missing:
            findings.append(
                Finding("ERROR", path, f"{where} missing fields: {', '.join(missing)}")
            )
            continue
        source_id = source["source_id"]
        if not isinstance(source_id, str) or not re.fullmatch(
            r"source\.[a-z0-9][a-z0-9_]*", source_id
        ):
            findings.append(Finding("ERROR", path, f"{where} has invalid source_id"))
        elif source_id in source_ids:
            findings.append(
                Finding("ERROR", path, f"duplicate source_id: {source_id}")
            )
        else:
            source_ids.add(source_id)
        if source["source_type"] not in allowed_types:
            findings.append(
                Finding("ERROR", path, f"{where} has unknown source_type")
            )
        roles = source["roles"]
        if not isinstance(roles, list) or any(role not in allowed_roles for role in roles):
            findings.append(Finding("ERROR", path, f"{where} has invalid roles"))
        if source["access_level"] not in allowed_access:
            findings.append(Finding("ERROR", path, f"{where} has invalid access_level"))
        if source["full_text_status"] not in allowed_full_text:
            findings.append(
                Finding("ERROR", path, f"{where} has invalid full_text_status")
            )

    return source_ids, findings


def validate_entity_metadata(
    path: Path,
    metadata: dict[str, Any],
    body: str,
    catalogs: dict[str, Any],
    source_ids: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    missing = sorted(REQUIRED_FIELDS - set(metadata))
    if missing:
        findings.append(
            Finding("ERROR", path, f"missing fields: {', '.join(missing)}")
        )
        return findings

    entity_types = catalogs["entity"]["entity_types"]
    entity_type = metadata["entity_type"]
    if entity_type not in entity_types:
        findings.append(Finding("ERROR", path, f"unknown entity_type: {entity_type}"))
        return findings

    entity_id = metadata["id"]
    id_pattern = catalogs["entity"]["id_pattern"]
    expected_prefix = entity_types[entity_type]["id_prefix"] + "."
    if not isinstance(entity_id, str) or not re.fullmatch(id_pattern, entity_id):
        findings.append(Finding("ERROR", path, f"invalid entity id: {entity_id!r}"))
    elif not entity_id.startswith(expected_prefix):
        findings.append(
            Finding(
                "ERROR",
                path,
                f"entity id must start with {expected_prefix!r} for {entity_type}",
            )
        )

    if not isinstance(metadata["name_zh"], str) or not metadata["name_zh"].strip():
        findings.append(Finding("ERROR", path, "name_zh must be a non-empty string"))
    if not isinstance(metadata["summary"], str) or not metadata["summary"].strip():
        findings.append(Finding("ERROR", path, "summary must be a non-empty string"))
    if not isinstance(metadata["aliases"], list):
        findings.append(Finding("ERROR", path, "aliases must be a list"))

    allowed_domains = set(catalogs["entity"]["one_health_domains"])
    domains = metadata["one_health_domains"]
    if not isinstance(domains, list) or any(
        domain not in allowed_domains for domain in domains
    ):
        findings.append(Finding("ERROR", path, "invalid one_health_domains"))

    allowed_review_statuses = set(catalogs["entity"]["review_statuses"])
    if metadata["review_status"] not in allowed_review_statuses:
        findings.append(Finding("ERROR", path, "invalid entity review_status"))

    for heading in sorted(REQUIRED_HEADINGS):
        if heading not in body:
            findings.append(Finding("ERROR", path, f"missing heading: {heading}"))

    relations = metadata["relations"]
    if not isinstance(relations, list):
        findings.append(Finding("ERROR", path, "relations must be a list"))
        return findings

    relation_types = catalogs["relation"]["relations"]
    relation_statuses = set(catalogs["relation"]["relation_statuses"])
    evidence_types = set(catalogs["source"]["evidence_types"])
    seen_relations: set[tuple[str, str]] = set()

    for index, relation in enumerate(relations):
        where = f"relations[{index}]"
        if not isinstance(relation, dict):
            findings.append(Finding("ERROR", path, f"{where} must be a mapping"))
            continue
        required = {
            "predicate",
            "object",
            "statement_zh",
            "relation_status",
            "evidence",
            "qualifiers",
        }
        missing_relation = sorted(required - set(relation))
        if missing_relation:
            findings.append(
                Finding(
                    "ERROR",
                    path,
                    f"{where} missing fields: {', '.join(missing_relation)}",
                )
            )
            continue

        predicate = relation["predicate"]
        object_id = relation["object"]
        if predicate not in relation_types:
            findings.append(
                Finding("ERROR", path, f"{where} unknown predicate: {predicate}")
            )
            continue
        if entity_type not in relation_types[predicate]["subject_types"]:
            findings.append(
                Finding(
                    "ERROR",
                    path,
                    f"{where} predicate {predicate} does not allow subject type {entity_type}",
                )
            )
        if not isinstance(object_id, str) or not re.fullmatch(id_pattern, object_id):
            findings.append(Finding("ERROR", path, f"{where} invalid object id"))
        relation_key = (str(predicate), str(object_id))
        if relation_key in seen_relations:
            findings.append(
                Finding("ERROR", path, f"{where} duplicates {predicate} -> {object_id}")
            )
        seen_relations.add(relation_key)

        if (
            not isinstance(relation["statement_zh"], str)
            or not relation["statement_zh"].strip()
        ):
            findings.append(
                Finding("ERROR", path, f"{where} statement_zh must be non-empty")
            )
        if relation["relation_status"] not in relation_statuses:
            findings.append(
                Finding("ERROR", path, f"{where} invalid relation_status")
            )
        if not isinstance(relation["qualifiers"], dict):
            findings.append(Finding("ERROR", path, f"{where} qualifiers must be a mapping"))

        evidence = relation["evidence"]
        if not isinstance(evidence, list) or not evidence:
            findings.append(
                Finding("ERROR", path, f"{where} must contain at least one evidence item")
            )
            continue
        for evidence_index, item in enumerate(evidence):
            evidence_where = f"{where}.evidence[{evidence_index}]"
            if not isinstance(item, dict):
                findings.append(
                    Finding("ERROR", path, f"{evidence_where} must be a mapping")
                )
                continue
            if not {"source_id", "locator", "evidence_type"} <= set(item):
                findings.append(
                    Finding("ERROR", path, f"{evidence_where} missing required fields")
                )
                continue
            if item["source_id"] not in source_ids:
                findings.append(
                    Finding(
                        "ERROR",
                        path,
                        f"{evidence_where} references unknown source_id: {item['source_id']}",
                    )
                )
            if not isinstance(item["locator"], str) or not item["locator"].strip():
                findings.append(
                    Finding("ERROR", path, f"{evidence_where} locator must be non-empty")
                )
            if item["evidence_type"] not in evidence_types:
                findings.append(
                    Finding("ERROR", path, f"{evidence_where} invalid evidence_type")
                )

    return findings


def validate_repository(
    root: Path, knowledge_dir: Path, source_registry: Path
) -> list[Finding]:
    findings: list[Finding] = []
    catalogs = load_catalogs(root)
    source_ids, source_findings = validate_source_registry(source_registry, catalogs)
    findings.extend(source_findings)

    documents: dict[str, tuple[Path, dict[str, Any]]] = {}
    parsed: list[tuple[Path, dict[str, Any], str]] = []
    for path in sorted(knowledge_dir.rglob("*.md")):
        if path.name == "README.md":
            continue
        try:
            metadata, body = parse_markdown(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            findings.append(Finding("ERROR", path, f"cannot parse document: {exc}"))
            continue
        entity_id = metadata.get("id")
        if isinstance(entity_id, str):
            if entity_id in documents:
                findings.append(
                    Finding("ERROR", path, f"duplicate entity id: {entity_id}")
                )
            else:
                documents[entity_id] = (path, metadata)
        parsed.append((path, metadata, body))

    for path, metadata, body in parsed:
        findings.extend(
            validate_entity_metadata(
                path, metadata, body, catalogs, source_ids
            )
        )

    relation_types = catalogs["relation"]["relations"]
    for path, metadata, _body in parsed:
        for relation in metadata.get("relations", []):
            if not isinstance(relation, dict):
                continue
            object_id = relation.get("object")
            predicate = relation.get("predicate")
            if not isinstance(object_id, str) or object_id not in documents:
                findings.append(
                    Finding(
                        "ERROR",
                        path,
                        f"relation target does not exist: {predicate} -> {object_id}",
                    )
                )
                continue
            if predicate not in relation_types:
                continue
            object_type = documents[object_id][1].get("entity_type")
            if object_type not in relation_types[predicate]["object_types"]:
                findings.append(
                    Finding(
                        "ERROR",
                        path,
                        f"predicate {predicate} does not allow object type {object_type}",
                    )
                )

    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root containing the schema directory.",
    )
    parser.add_argument(
        "--knowledge-dir",
        type=Path,
        default=None,
        help="Knowledge directory; defaults to <root>/knowledge.",
    )
    parser.add_argument(
        "--source-registry",
        type=Path,
        default=None,
        help="Source registry; defaults to <root>/sources/registry.yml.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    knowledge_dir = (args.knowledge_dir or root / "knowledge").resolve()
    source_registry = (
        args.source_registry or root / "sources" / "registry.yml"
    ).resolve()

    try:
        findings = validate_repository(root, knowledge_dir, source_registry)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: schema loading failed: {exc}")
        return 2

    errors = [finding for finding in findings if finding.level == "ERROR"]
    for finding in findings:
        try:
            shown_path = finding.path.relative_to(root)
        except ValueError:
            shown_path = finding.path
        print(f"{finding.level}: {shown_path}: {finding.message}")

    entity_count = len(
        [
            path
            for path in knowledge_dir.rglob("*.md")
            if path.name != "README.md"
        ]
    )
    if errors:
        print(f"VALIDATION=FAIL entities={entity_count} errors={len(errors)}")
        return 1
    print(f"VALIDATION=PASS entities={entity_count} errors=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
