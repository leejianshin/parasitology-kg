#!/usr/bin/env python3
"""Build deterministic graph artifacts from reviewed knowledge Markdown."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BATCH_ID = "P5-B1"
DEFAULT_OUTPUT_DIR = (
    ROOT / "derived" / "clonorchis-sinensis" / "phase5-batch1"
)


def parse_front_matter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    marker = "\n---\n"
    if not text.startswith("---\n"):
        raise ValueError(f"{path} missing opening front matter")
    end = text.find(marker, 4)
    if end < 0:
        raise ValueError(f"{path} missing closing front matter")
    metadata = yaml.safe_load(text[4:end])
    if not isinstance(metadata, dict):
        raise ValueError(f"{path} front matter must be a mapping")
    return metadata


def selected_documents(
    root: Path, batch_id: str
) -> list[tuple[Path, dict[str, Any]]]:
    documents: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((root / "knowledge").rglob("*.md")):
        if path.name == "README.md":
            continue
        metadata = parse_front_matter(path)
        admission = metadata.get("admission")
        if (
            metadata.get("review_status") == "reviewed"
            and isinstance(admission, dict)
            and admission.get("batch_id") == batch_id
        ):
            documents.append((path, metadata))
    return documents


def build_graph(
    root: Path = ROOT, batch_id: str = DEFAULT_BATCH_ID
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    documents = selected_documents(root, batch_id)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    canonical_hasher = hashlib.sha256()

    for path, metadata in documents:
        relative_path = path.relative_to(root).as_posix()
        canonical_hasher.update(relative_path.encode("utf-8"))
        canonical_hasher.update(b"\0")
        canonical_hasher.update(path.read_bytes())
        canonical_hasher.update(b"\0")

        admission = metadata["admission"]
        nodes.append(
            {
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
                "source_file": relative_path,
            }
        )

        for relation in metadata["relations"]:
            if relation["relation_status"] != "reviewed":
                raise ValueError(
                    f"{metadata['id']} has non-reviewed relation in {batch_id}"
                )
            edges.append(
                {
                    "subject": metadata["id"],
                    "predicate": relation["predicate"],
                    "object": relation["object"],
                    "statement_zh": relation["statement_zh"],
                    "relation_status": relation["relation_status"],
                    "evidence": relation["evidence"],
                    "qualifiers": relation["qualifiers"],
                    "source_file": relative_path,
                }
            )

    nodes.sort(key=lambda item: item["id"])
    edges.sort(
        key=lambda item: (
            item["subject"],
            item["predicate"],
            item["object"],
            item["qualifiers"]["source_atom_id"],
        )
    )
    return nodes, edges, canonical_hasher.hexdigest()


def jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    text = "".join(
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for row in rows
    )
    return text.encode("utf-8")


def triples_csv_bytes(edges: list[dict[str, Any]]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(
        handle,
        fieldnames=[
            "subject",
            "predicate",
            "object",
            "relation_status",
            "source_atom_id",
            "evidence_source_ids",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    for edge in edges:
        writer.writerow(
            {
                "subject": edge["subject"],
                "predicate": edge["predicate"],
                "object": edge["object"],
                "relation_status": edge["relation_status"],
                "source_atom_id": edge["qualifiers"]["source_atom_id"],
                "evidence_source_ids": "|".join(
                    item["source_id"] for item in edge["evidence"]
                ),
            }
        )
    return handle.getvalue().encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def render_artifacts(
    root: Path = ROOT, batch_id: str = DEFAULT_BATCH_ID
) -> dict[str, bytes]:
    nodes, edges, canonical_hash = build_graph(root, batch_id)
    artifacts = {
        "nodes.jsonl": jsonl_bytes(nodes),
        "edges.jsonl": jsonl_bytes(edges),
        "triples.csv": triples_csv_bytes(edges),
    }
    manifest = {
        "manifest_version": "1.0",
        "batch_id": batch_id,
        "authority": "reviewed_structured_markdown",
        "source_glob": "knowledge/**/*.md",
        "selection_rule": (
            f"review_status=reviewed and admission.batch_id={batch_id}"
        ),
        "generator": "scripts/build_derived_graph.py",
        "canonical_file_count": len(nodes),
        "canonical_input_sha256": canonical_hash,
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "triples": len(edges),
        },
        "artifacts": [
            {
                "path": name,
                "sha256": sha256_bytes(content),
                "size_bytes": len(content),
            }
            for name, content in artifacts.items()
        ],
        "release_boundary": {
            "student_rag_authorized": False,
            "later_batches_included": False,
        },
    }
    artifacts["manifest.yml"] = yaml.safe_dump(
        manifest,
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")
    return artifacts


def write_artifacts(output_dir: Path, artifacts: dict[str, bytes]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in artifacts.items():
        (output_dir / name).write_bytes(content)


def check_artifacts(output_dir: Path, artifacts: dict[str, bytes]) -> None:
    expected_names = set(artifacts)
    actual_names = {
        path.name for path in output_dir.iterdir() if path.is_file()
    } if output_dir.exists() else set()
    if actual_names != expected_names:
        raise ValueError(
            "derived artifact set mismatch "
            f"missing={sorted(expected_names - actual_names)} "
            f"extra={sorted(actual_names - expected_names)}"
        )
    mismatches = [
        name
        for name, content in artifacts.items()
        if (output_dir / name).read_bytes() != content
    ]
    if mismatches:
        raise ValueError(f"derived artifacts are stale: {mismatches}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        artifacts = render_artifacts(args.root.resolve(), args.batch_id)
        if args.write:
            write_artifacts(args.output_dir.resolve(), artifacts)
            action = "WRITE"
        else:
            check_artifacts(args.output_dir.resolve(), artifacts)
            action = "CHECK"
        nodes, edges, _canonical_hash = build_graph(
            args.root.resolve(), args.batch_id
        )
        print(
            f"DERIVED_GRAPH_{action}=PASS "
            f"batch={args.batch_id} nodes={len(nodes)} edges={len(edges)}"
        )
        return 0
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"DERIVED_GRAPH=FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
