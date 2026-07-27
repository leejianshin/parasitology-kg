#!/usr/bin/env python3
"""Build the deterministic Clonorchis PCMS aggregate graph.

The aggregate combines the frozen P5-B1 graph, new P7-PCMS entity documents,
and reviewed batch-scoped extension documents. Frozen Phase 5 entity files and
the Phase 6 evaluation corpus are not rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    from .build_derived_graph import (
        ROOT,
        build_graph,
        jsonl_bytes,
        parse_front_matter,
        sha256_bytes,
        triples_csv_bytes,
        write_artifacts,
    )
except ImportError:
    from build_derived_graph import (
        ROOT,
        build_graph,
        jsonl_bytes,
        parse_front_matter,
        sha256_bytes,
        triples_csv_bytes,
        write_artifacts,
    )


BASE_BATCH_ID = "P5-B1"
PCMS_BATCH_ID = "P7-PCMS"
DEFAULT_OUTPUT_DIR = ROOT / "derived" / "clonorchis-sinensis" / "pcms-v1"
EXTENSION_DIR = ROOT / "knowledge-extensions" / "clonorchis-sinensis"
NARRATIVE_CLAIMS = {
    "PCMS-001": "stage.clonorchis_adult",
    "PCMS-002": "stage.clonorchis_adult",
    "PCMS-003": "stage.clonorchis_egg",
    "PCMS-004": "stage.clonorchis_egg",
    "PCMS-005": "stage.clonorchis_egg",
    "PCMS-006": "stage.clonorchis_egg",
}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def selected_pcms_documents(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    documents: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((root / "knowledge").rglob("*.md")):
        if path.name == "README.md":
            continue
        metadata = parse_front_matter(path)
        admission = metadata.get("admission")
        if (
            metadata.get("review_status") == "reviewed"
            and isinstance(admission, dict)
            and admission.get("batch_id") == PCMS_BATCH_ID
        ):
            documents.append((path, metadata))
    return documents


def selected_extensions(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    extension_root = root / "knowledge-extensions" / "clonorchis-sinensis"
    documents: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(extension_root.glob("*.md")):
        metadata = parse_front_matter(path)
        admission = metadata.get("admission")
        if (
            metadata.get("review_status") == "reviewed"
            and isinstance(admission, dict)
            and admission.get("batch_id") == PCMS_BATCH_ID
        ):
            documents.append((path, metadata))
    return documents


def node_from_document(
    root: Path, path: Path, metadata: dict[str, Any]
) -> dict[str, Any]:
    admission = metadata["admission"]
    return {
        "id": metadata["id"],
        "entity_type": metadata["entity_type"],
        "name_zh": metadata["name_zh"],
        "name_en": metadata.get("name_en"),
        "scientific_name": metadata.get("scientific_name"),
        "aliases": metadata["aliases"],
        "one_health_domains": metadata["one_health_domains"],
        "summary": metadata["summary"],
        "review_status": metadata["review_status"],
        "admission_batch_id": admission["batch_id"],
        "source_atom_ids": admission.get("atom_ids", []),
        "source_file": path.relative_to(root).as_posix(),
    }


def edge_from_relation(
    root: Path,
    source_file: Path,
    subject: str,
    relation: dict[str, Any],
) -> dict[str, Any]:
    if relation.get("relation_status") != "reviewed":
        raise ValueError(f"{source_file} contains a non-reviewed relation")
    return {
        "subject": subject,
        "predicate": relation["predicate"],
        "object": relation["object"],
        "statement_zh": relation["statement_zh"],
        "relation_status": relation["relation_status"],
        "evidence": relation["evidence"],
        "qualifiers": relation["qualifiers"],
        "source_file": source_file.relative_to(root).as_posix(),
    }


def validate_extensions(
    root: Path,
    extensions: list[tuple[Path, dict[str, Any]]],
    nodes: list[dict[str, Any]],
) -> None:
    entity_catalog = load_yaml(root / "schema" / "entity-types.yml")
    relation_catalog = load_yaml(root / "schema" / "relation-types.yml")
    source_catalog = load_yaml(root / "schema" / "source-types.yml")
    registry = load_yaml(root / "sources" / "registry.yml")
    entity_types = entity_catalog["entity_types"]
    relations = relation_catalog["relations"]
    node_types = {node["id"]: node["entity_type"] for node in nodes}
    source_ids = {item["source_id"] for item in registry["sources"]}
    evidence_types = set(source_catalog["evidence_types"])
    extension_ids: set[str] = set()

    for path, metadata in extensions:
        required = {
            "schema_version",
            "extension_id",
            "extends_entity",
            "review_status",
            "admission",
            "relations",
            "review",
        }
        missing = required - set(metadata)
        if missing:
            raise ValueError(f"{path} missing extension fields: {sorted(missing)}")
        extension_id = metadata["extension_id"]
        if not (
            isinstance(extension_id, str)
            and extension_id.startswith("extension.")
        ):
            raise ValueError(f"{path} has invalid extension_id")
        if extension_id in extension_ids:
            raise ValueError(f"duplicate extension_id: {extension_id}")
        extension_ids.add(extension_id)
        subject = metadata["extends_entity"]
        if subject not in node_types:
            raise ValueError(f"{path} extends unknown entity: {subject}")
        subject_type = node_types[subject]
        admission = metadata["admission"]
        if admission.get("batch_id") != PCMS_BATCH_ID:
            raise ValueError(f"{path} has incorrect admission batch")
        review = metadata["review"]
        if (
            review.get("reviewed_by") != "course_lead"
            or not review.get("last_reviewed")
        ):
            raise ValueError(f"{path} lacks course-lead review metadata")
        atom_ids = set(admission.get("atom_ids", []))
        relation_atom_ids: set[str] = set()
        relation_keys: set[tuple[str, str]] = set()
        for relation in metadata["relations"]:
            required_relation_fields = {
                "predicate",
                "object",
                "statement_zh",
                "relation_status",
                "evidence",
                "qualifiers",
            }
            missing_relation_fields = required_relation_fields - set(relation)
            if missing_relation_fields:
                raise ValueError(
                    f"{path} relation missing fields: "
                    f"{sorted(missing_relation_fields)}"
                )
            if relation["relation_status"] != "reviewed":
                raise ValueError(f"{path} contains non-reviewed relation")
            if not (
                isinstance(relation["statement_zh"], str)
                and relation["statement_zh"].strip()
            ):
                raise ValueError(f"{path} relation statement is empty")
            predicate = relation["predicate"]
            object_id = relation["object"]
            relation_key = (predicate, object_id)
            if relation_key in relation_keys:
                raise ValueError(f"{path} duplicates relation {relation_key}")
            relation_keys.add(relation_key)
            if predicate not in relations:
                raise ValueError(f"{path} unknown predicate: {predicate}")
            if subject_type not in relations[predicate]["subject_types"]:
                raise ValueError(
                    f"{path} {predicate} disallows subject type {subject_type}"
                )
            if object_id not in node_types:
                raise ValueError(f"{path} targets unknown entity: {object_id}")
            if node_types[object_id] not in relations[predicate]["object_types"]:
                raise ValueError(
                    f"{path} {predicate} disallows object type {node_types[object_id]}"
                )
            atom_id = relation["qualifiers"].get("source_atom_id")
            if not isinstance(atom_id, str):
                raise ValueError(f"{path} relation lacks source_atom_id")
            relation_atom_ids.add(atom_id)
            evidence_items = relation["evidence"]
            if not isinstance(evidence_items, list) or not evidence_items:
                raise ValueError(f"{path} relation lacks evidence")
            for evidence in evidence_items:
                if evidence["source_id"] not in source_ids:
                    raise ValueError(
                        f"{path} references unknown source: {evidence['source_id']}"
                    )
                if not (
                    isinstance(evidence.get("locator"), str)
                    and evidence["locator"].strip()
                ):
                    raise ValueError(f"{path} evidence locator is empty")
                if evidence.get("evidence_type") not in evidence_types:
                    raise ValueError(f"{path} evidence type is invalid")
        if not relation_atom_ids <= atom_ids:
            raise ValueError(
                f"{path} relation atoms absent from admission: "
                f"{sorted(relation_atom_ids - atom_ids)}"
            )

    if "hazard_classification" not in entity_types:
        raise ValueError("PCMS hazard_classification schema extension is missing")


def build_pcms_graph(
    root: Path = ROOT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, dict[str, Any]]:
    base_nodes, base_edges, base_hash = build_graph(root, BASE_BATCH_ID)
    pcms_documents = selected_pcms_documents(root)
    extensions = selected_extensions(root)
    pcms_nodes = [
        node_from_document(root, path, metadata)
        for path, metadata in pcms_documents
    ]
    nodes = base_nodes + pcms_nodes
    node_ids = [node["id"] for node in nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("PCMS aggregate contains duplicate entity IDs")

    pcms_edges: list[dict[str, Any]] = []
    for path, metadata in pcms_documents:
        for relation in metadata["relations"]:
            pcms_edges.append(
                edge_from_relation(root, path, metadata["id"], relation)
            )
    validate_extensions(root, extensions, nodes)
    for path, metadata in extensions:
        for relation in metadata["relations"]:
            pcms_edges.append(
                edge_from_relation(
                    root, path, metadata["extends_entity"], relation
                )
            )

    relation_atom_ids = [
        edge["qualifiers"].get("source_atom_id") for edge in pcms_edges
    ]
    if len(relation_atom_ids) != len(set(relation_atom_ids)):
        raise ValueError("PCMS relation claim IDs must be unique")
    expected_relation_ids = {
        f"PCMS-{index:03d}" for index in range(7, 37)
    }
    if set(relation_atom_ids) != expected_relation_ids:
        raise ValueError(
            "PCMS relation claim coverage mismatch "
            f"missing={sorted(expected_relation_ids - set(relation_atom_ids))} "
            f"extra={sorted(set(relation_atom_ids) - expected_relation_ids)}"
        )

    edges = base_edges + pcms_edges
    nodes.sort(key=lambda item: item["id"])
    edges.sort(
        key=lambda item: (
            item["subject"],
            item["predicate"],
            item["object"],
            item["qualifiers"]["source_atom_id"],
        )
    )

    hasher = hashlib.sha256()
    hasher.update(f"base:{base_hash}\0".encode())
    for path, _metadata in pcms_documents + extensions:
        hasher.update(path.relative_to(root).as_posix().encode())
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    for path in (
        root / "schema" / "entity-types.yml",
        root / "schema" / "relation-types.yml",
    ):
        hasher.update(path.read_bytes())
        hasher.update(b"\0")

    details = {
        "base_nodes": len(base_nodes),
        "base_edges": len(base_edges),
        "pcms_nodes": len(pcms_nodes),
        "pcms_edges": len(pcms_edges),
        "extension_documents": len(extensions),
        "narrative_claims": len(NARRATIVE_CLAIMS),
    }
    return nodes, edges, hasher.hexdigest(), details


def render_artifacts(root: Path = ROOT) -> dict[str, bytes]:
    nodes, edges, canonical_hash, details = build_pcms_graph(root)
    artifacts = {
        "nodes.jsonl": jsonl_bytes(nodes),
        "edges.jsonl": jsonl_bytes(edges),
        "triples.csv": triples_csv_bytes(edges),
    }
    manifest = {
        "manifest_version": "1.0",
        "aggregate_id": "clonorchis_pcms_v1",
        "base_batch_id": BASE_BATCH_ID,
        "admission_batch_id": PCMS_BATCH_ID,
        "authority": "reviewed_markdown_plus_reviewed_batch_extensions",
        "generator": "scripts/build_pcms_graph.py",
        "canonical_input_sha256": canonical_hash,
        "counts": {
            **details,
            "nodes": len(nodes),
            "edges": len(edges),
            "triples": len(edges),
        },
        "narrative_claims": [
            {"claim_id": claim_id, "entity_id": entity_id}
            for claim_id, entity_id in sorted(NARRATIVE_CLAIMS.items())
        ],
        "artifacts": [
            {
                "path": name,
                "sha256": sha256_bytes(content),
                "size_bytes": len(content),
            }
            for name, content in artifacts.items()
        ],
        "release_boundary": {
            "student_release_authorized": False,
            "student_roster_included": False,
            "raw_score_data_included": False,
            "collaborative_review": "CHEN_HAIYING_PENDING",
        },
    }
    artifacts["manifest.yml"] = yaml.safe_dump(
        manifest, allow_unicode=True, sort_keys=False
    ).encode("utf-8")
    return artifacts


def check_artifacts(output_dir: Path, artifacts: dict[str, bytes]) -> None:
    actual = (
        {path.name for path in output_dir.iterdir() if path.is_file()}
        if output_dir.exists()
        else set()
    )
    if actual != set(artifacts):
        raise ValueError(
            f"PCMS artifact set mismatch expected={sorted(artifacts)} "
            f"actual={sorted(actual)}"
        )
    stale = [
        name
        for name, content in artifacts.items()
        if (output_dir / name).read_bytes() != content
    ]
    if stale:
        raise ValueError(f"PCMS artifacts are stale: {stale}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        artifacts = render_artifacts(args.root.resolve())
        if args.write:
            write_artifacts(args.output_dir.resolve(), artifacts)
            action = "WRITE"
        else:
            check_artifacts(args.output_dir.resolve(), artifacts)
            action = "CHECK"
        manifest = yaml.safe_load(artifacts["manifest.yml"])
        counts = manifest["counts"]
        print(
            f"PCMS_GRAPH_{action}=PASS nodes={counts['nodes']} "
            f"edges={counts['edges']} pcms_edges={counts['pcms_edges']} "
            f"narrative_claims={counts['narrative_claims']}"
        )
        return 0
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"PCMS_GRAPH=FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
