from __future__ import annotations

import unittest

import yaml

from scripts.build_phase6_rag_corpus import (
    DEFAULT_OUTPUT_DIR,
    ROOT,
    render_artifacts,
)


class Phase6CorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.artifacts = render_artifacts(ROOT)
        self.manifest = yaml.safe_load(self.artifacts["manifest.yml"])
        self.catalog = yaml.safe_load(self.artifacts["source-catalog.yml"])
        self.corpus_text = self.artifacts["corpus.md"].decode("utf-8")

    def test_committed_corpus_is_deterministic(self) -> None:
        for name, content in self.artifacts.items():
            self.assertEqual(
                (DEFAULT_OUTPUT_DIR / name).read_bytes(),
                content,
                name,
            )

    def test_runtime_corpus_contains_only_six_used_sources(self) -> None:
        source_ids = {
            source["source_id"] for source in self.catalog["sources"]
        }
        self.assertEqual(len(source_ids), 6)
        self.assertNotIn("source.iarc_clonorchis_group1", source_ids)
        self.assertEqual(
            self.manifest["allowed_runtime_files"],
            ["corpus.md", "source-catalog.yml"],
        )

    def test_test_suite_and_review_material_do_not_leak_into_corpus(self) -> None:
        self.assertNotIn("CS-RAG-", self.corpus_text)
        self.assertNotIn("APPROVE_PILOT_RELEASE", self.corpus_text)
        self.assertNotIn("clonorchis_phase6_fixed_questions_v1", self.corpus_text)


if __name__ == "__main__":
    unittest.main()
