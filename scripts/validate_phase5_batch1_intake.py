#!/usr/bin/env python3
"""Validate Phase 5 Batch 1 derived graph intake and scope boundaries."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from build_derived_graph import (
    DEFAULT_BATCH_ID,
    DEFAULT_OUTPUT_DIR,
    ROOT,
    check_artifacts,
    render_artifacts,
)


PLAN_PATH = ROOT / "phase5" / "clonorchis-sinensis" / "admission-plan.yml"
SOURCE_REGISTRY_PATH = ROOT / "sources" / "registry.yml"


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be a mapping")
    return data


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} must be an object")
        rows.append(row)
    return rows


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    try:
        plan = load_yaml(PLAN_PATH)
        batch = next(
            item
            for item in plan["batches"]
            if item["batch_id"] == DEFAULT_BATCH_ID
        )
        if batch["status"] != "APPROVED":
            raise ValueError("P5-B1 is not approved")
        if plan["approval_gate"]["batch_2_and_3_write"] != "NOT_AUTHORIZED":
            raise ValueError("later batches are not blocked")
        if (
            plan["approval_gate"]["student_rag_release"]
            != "NOT_AUTHORIZED_PENDING_PHASE6"
        ):
            raise ValueError("student RAG boundary changed")

        expected_artifacts = render_artifacts(ROOT, DEFAULT_BATCH_ID)
        check_artifacts(DEFAULT_OUTPUT_DIR, expected_artifacts)
        manifest = load_yaml(DEFAULT_OUTPUT_DIR / "manifest.yml")
        nodes = load_jsonl(DEFAULT_OUTPUT_DIR / "nodes.jsonl")
        edges = load_jsonl(DEFAULT_OUTPUT_DIR / "edges.jsonl")

        expected_entity_ids = set(batch["entity_ids"])
        actual_entity_ids = {node["id"] for node in nodes}
        if actual_entity_ids != expected_entity_ids:
            raise ValueError("derived node IDs differ from approved batch")
        if len(nodes) != 14 or len(edges) != 10:
            raise ValueError(
                f"unexpected graph size nodes={len(nodes)} edges={len(edges)}"
            )
        if any(node["review_status"] != "reviewed" for node in nodes):
            raise ValueError("derived graph contains non-reviewed node")
        if any(edge["relation_status"] != "reviewed" for edge in edges):
            raise ValueError("derived graph contains non-reviewed edge")

        expected_atom_ids = set(batch["edge_atom_ids"])
        actual_atom_ids = {
            edge["qualifiers"]["source_atom_id"] for edge in edges
        }
        if actual_atom_ids != expected_atom_ids:
            raise ValueError("derived edge atoms differ from approved batch")

        forbidden_atom_ids: set[str] = set()
        for other_batch in plan["batches"]:
            if other_batch["batch_id"] == DEFAULT_BATCH_ID:
                continue
            forbidden_atom_ids.update(other_batch.get("edge_atom_ids", []))
            forbidden_atom_ids.update(other_batch.get("qualifier_atom_ids", []))
        if actual_atom_ids & forbidden_atom_ids:
            raise ValueError("later-batch atom leaked into derived graph")

        registry = load_yaml(SOURCE_REGISTRY_PATH)
        registered_sources = {
            source["source_id"] for source in registry["sources"]
        }
        evidence_sources = {
            evidence["source_id"]
            for edge in edges
            for evidence in edge["evidence"]
        }
        if not evidence_sources <= registered_sources:
            raise ValueError(
                "unknown evidence sources: "
                f"{sorted(evidence_sources - registered_sources)}"
            )

        triple_rows = list(
            csv.DictReader(
                io.StringIO(
                    (DEFAULT_OUTPUT_DIR / "triples.csv").read_text(
                        encoding="utf-8"
                    )
                )
            )
        )
        expected_triples = {
            (
                edge["subject"],
                edge["predicate"],
                edge["object"],
                edge["relation_status"],
                edge["qualifiers"]["source_atom_id"],
            )
            for edge in edges
        }
        actual_triples = {
            (
                row["subject"],
                row["predicate"],
                row["object"],
                row["relation_status"],
                row["source_atom_id"],
            )
            for row in triple_rows
        }
        if actual_triples != expected_triples or len(triple_rows) != len(edges):
            raise ValueError("triples.csv differs from edges.jsonl")

        for item in manifest["artifacts"]:
            path = DEFAULT_OUTPUT_DIR / item["path"]
            if sha256_file(path) != item["sha256"]:
                raise ValueError(f"manifest hash mismatch: {item['path']}")
            if path.stat().st_size != item["size_bytes"]:
                raise ValueError(f"manifest size mismatch: {item['path']}")

        serialized = "\n".join(
            path.read_text(encoding="utf-8")
            for path in DEFAULT_OUTPUT_DIR.iterdir()
            if path.is_file()
        )
        private_path_patterns = [
            re.compile(r"[A-Za-z]:\\" + "Users" + r"\\", re.IGNORECASE),
            re.compile("parasitology-kg" + "-private", re.IGNORECASE),
            re.compile("chrome" + "download", re.IGNORECASE),
            re.compile("market" + "-lab", re.IGNORECASE),
        ]
        leaks = [
            pattern.pattern
            for pattern in private_path_patterns
            if pattern.search(serialized)
        ]
        if leaks:
            raise ValueError(f"private path leak: {leaks}")

        print(
            "PHASE5_BATCH1_INTAKE=PASS "
            f"nodes={len(nodes)} edges={len(edges)} "
            f"sources={len(evidence_sources)} later_batches=0"
        )
        return 0
    except (
        json.JSONDecodeError,
        KeyError,
        OSError,
        StopIteration,
        TypeError,
        ValueError,
        yaml.YAMLError,
    ) as exc:
        print(f"PHASE5_BATCH1_INTAKE=FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
