#!/usr/bin/env python3
"""Build the allowlisted Phase 6 RAG evaluation corpus."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    from .build_derived_graph import (
        DEFAULT_BATCH_ID,
        ROOT,
        build_graph,
        selected_documents,
    )
except ImportError:
    from build_derived_graph import (
        DEFAULT_BATCH_ID,
        ROOT,
        build_graph,
        selected_documents,
    )


DEFAULT_OUTPUT_DIR = (
    ROOT / "derived" / "clonorchis-sinensis" / "phase6-rag-corpus"
)
SOURCE_REGISTRY_PATH = ROOT / "sources" / "registry.yml"


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be a mapping")
    return data


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def render_corpus_markdown(
    root: Path, documents: list[tuple[Path, dict[str, Any]]]
) -> bytes:
    parts = [
        "# 华支睾吸虫 Phase 6 RAG白名单语料包\n\n",
        "> 本文件由正式`reviewed` Markdown确定性生成；原文件仍是权威主数据。\n\n",
        "## 使用边界\n\n",
        "- 只能依据本文件实际包含的内容回答；\n",
        "- 未覆盖的问题应明确说明当前语料不足；\n",
        "- 不得调用网页搜索、模型记忆或其他仓库文件补足缺口；\n",
        "- 诊断线索、传播条件和防控建议不得扩大为确诊、必然感染或已证效果。\n\n",
        "## 正式实体文档\n",
    ]
    ordered_documents = sorted(documents, key=lambda item: item[1]["id"])
    for path, metadata in ordered_documents:
        relative_path = path.relative_to(root).as_posix()
        parts.extend(
            [
                "\n---\n\n",
                f"## {metadata['id']}｜{metadata['name_zh']}\n\n",
                f"canonical_source_file: `{relative_path}`\n\n",
                path.read_text(encoding="utf-8").rstrip(),
                "\n",
            ]
        )
    return "".join(parts).encode("utf-8")


def render_source_catalog(
    registry: dict[str, Any], edges: list[dict[str, Any]]
) -> tuple[bytes, int]:
    locators_by_source: dict[str, set[str]] = {}
    evidence_types_by_source: dict[str, set[str]] = {}
    for edge in edges:
        for evidence in edge["evidence"]:
            source_id = evidence["source_id"]
            locators_by_source.setdefault(source_id, set()).add(
                evidence["locator"]
            )
            evidence_types_by_source.setdefault(source_id, set()).add(
                evidence["evidence_type"]
            )

    registry_by_id = {
        item["source_id"]: item for item in registry["sources"]
    }
    missing = set(locators_by_source) - set(registry_by_id)
    if missing:
        raise ValueError(f"unregistered corpus sources: {sorted(missing)}")

    catalog_sources: list[dict[str, Any]] = []
    for source_id in sorted(locators_by_source):
        source = registry_by_id[source_id]
        catalog_sources.append(
            {
                "source_id": source_id,
                "source_type": source["source_type"],
                "title": source["title"],
                "organization": source.get("organization"),
                "creators": source.get("creators", []),
                "publication_date": (
                    source.get("publication_date")
                    or source.get("page_date")
                    or source.get("page_last_reviewed")
                ),
                "url": source.get("url"),
                "allowed_evidence_types": sorted(
                    evidence_types_by_source[source_id]
                ),
                "allowed_locators": sorted(locators_by_source[source_id]),
            }
        )

    catalog = {
        "catalog_version": "1.0",
        "scope": "P5-B1_RELATION_EVIDENCE_ONLY",
        "source_count": len(catalog_sources),
        "sources": catalog_sources,
        "boundary": (
            "只登记P5-B1关系实际引用的来源与定位；不得从来源总表或网页"
            "扩展未进入正式知识层的命题。"
        ),
    }
    content = yaml.safe_dump(
        catalog,
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")
    return content, len(catalog_sources)


def render_artifacts(
    root: Path = ROOT, batch_id: str = DEFAULT_BATCH_ID
) -> dict[str, bytes]:
    documents = selected_documents(root, batch_id)
    nodes, edges, canonical_hash = build_graph(root, batch_id)
    registry = load_yaml(root / "sources" / "registry.yml")
    corpus_content = render_corpus_markdown(root, documents)
    source_catalog_content, source_count = render_source_catalog(
        registry, edges
    )
    artifacts = {
        "corpus.md": corpus_content,
        "source-catalog.yml": source_catalog_content,
    }
    manifest = {
        "manifest_version": "1.0",
        "corpus_id": "clonorchis_phase6_rag_corpus_v1",
        "batch_id": batch_id,
        "authority": "derived_from_reviewed_structured_markdown",
        "generator": "scripts/build_phase6_rag_corpus.py",
        "canonical_input_sha256": canonical_hash,
        "counts": {
            "documents": len(documents),
            "nodes": len(nodes),
            "edges": len(edges),
            "sources": source_count,
        },
        "allowed_runtime_files": [
            "corpus.md",
            "source-catalog.yml",
        ],
        "excluded_runtime_inputs": [
            "整个GitHub仓库",
            "sources/registry.yml",
            "candidates/",
            "reviews/",
            "phase6/固定题集与评分规则",
            "Phase 5第二、三批内容",
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
            "evaluation_only": True,
            "student_release_authorized": False,
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
    actual_names = (
        {path.name for path in output_dir.iterdir() if path.is_file()}
        if output_dir.exists()
        else set()
    )
    if actual_names != expected_names:
        raise ValueError(
            "Phase 6 corpus artifact set mismatch "
            f"missing={sorted(expected_names - actual_names)} "
            f"extra={sorted(actual_names - expected_names)}"
        )
    stale = [
        name
        for name, content in artifacts.items()
        if (output_dir / name).read_bytes() != content
    ]
    if stale:
        raise ValueError(f"Phase 6 RAG corpus is stale: {stale}")


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
        root = args.root.resolve()
        output_dir = args.output_dir.resolve()
        artifacts = render_artifacts(root, args.batch_id)
        if args.write:
            write_artifacts(output_dir, artifacts)
            action = "WRITE"
        else:
            check_artifacts(output_dir, artifacts)
            action = "CHECK"
        manifest = yaml.safe_load(artifacts["manifest.yml"])
        counts = manifest["counts"]
        print(
            f"PHASE6_RAG_CORPUS_{action}=PASS "
            f"documents={counts['documents']} nodes={counts['nodes']} "
            f"edges={counts['edges']} sources={counts['sources']}"
        )
        return 0
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"PHASE6_RAG_CORPUS=FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
