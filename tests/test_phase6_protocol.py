from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.validate_phase6_protocol import (
    PLAN_PATH,
    RUBRIC_PATH,
    ROOT,
    SUITE_PATH,
    graph_context,
    load_yaml,
    validate_protocol_data,
    validate_run_structure,
)


class Phase6ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = load_yaml(PLAN_PATH)
        self.suite = load_yaml(SUITE_PATH)
        self.rubric = load_yaml(RUBRIC_PATH)

    def test_frozen_protocol_is_valid(self) -> None:
        summary = validate_protocol_data(
            self.plan, self.suite, self.rubric, ROOT
        )
        self.assertEqual(summary["cases"], 18)
        self.assertEqual(summary["nodes"], 14)
        self.assertEqual(summary["edges"], 10)

    def test_later_batch_atom_is_rejected(self) -> None:
        suite = copy.deepcopy(self.suite)
        suite["test_cases"][0]["required_relation_atom_ids"].append(
            "W2-ATOM-010"
        )
        with self.assertRaisesRegex(ValueError, "unknown atoms|later-batch"):
            validate_protocol_data(self.plan, suite, self.rubric, ROOT)

    def test_abstention_case_cannot_require_graph_fact(self) -> None:
        suite = copy.deepcopy(self.suite)
        boundary = next(
            case
            for case in suite["test_cases"]
            if case["expected_disposition"] == "ABSTAIN"
        )
        boundary["required_relation_atom_ids"] = ["W2-ATOM-005"]
        with self.assertRaisesRegex(
            ValueError, "ABSTAIN cannot require graph facts"
        ):
            validate_protocol_data(self.plan, suite, self.rubric, ROOT)

    def test_unknown_entity_is_rejected(self) -> None:
        suite = copy.deepcopy(self.suite)
        suite["test_cases"][0]["required_entity_ids"].append(
            "host.not_admitted"
        )
        with self.assertRaisesRegex(ValueError, "unknown entities"):
            validate_protocol_data(self.plan, suite, self.rubric, ROOT)

    def make_valid_rag_run(self) -> dict:
        context = graph_context(ROOT)
        responses = []
        disposition_map = {
            "ANSWER": "answered",
            "PARTIAL": "partial",
            "ABSTAIN": "abstained",
        }
        for case in self.suite["test_cases"]:
            atom_ids = case["required_relation_atom_ids"]
            source_ids = sorted(
                {
                    context["edge_by_atom"][atom_id]["evidence"][0][
                        "source_id"
                    ]
                    for atom_id in atom_ids
                }
            )
            responses.append(
                {
                    "case_id": case["case_id"],
                    "disposition": disposition_map[
                        case["expected_disposition"]
                    ],
                    "answer_text": "结构测试占位文本",
                    "retrieved_entity_ids": case["required_entity_ids"],
                    "used_relation_atom_ids": atom_ids,
                    "cited_source_ids": source_ids,
                    "reason_code": (
                        "corpus_not_covered"
                        if case["expected_disposition"] == "ABSTAIN"
                        else None
                    ),
                    "missing_coverage": (
                        [case["coverage_gap"]]
                        if case["expected_disposition"] == "PARTIAL"
                        else []
                    ),
                }
            )
        return {
            "run_schema_version": "1.0",
            "run_id": "test-rag-run",
            "suite_id": self.suite["suite_id"],
            "mode": "rag",
            "status": "COMPLETED",
            "run_metadata": {
                "model_provider": "test",
                "model_name": "test",
                "model_version": "1",
                "interface_or_tool": "unit-test",
                "generated_at": "2026-07-26T00:00:00Z",
                "knowledge_commit": (
                    "bf021d5af95042c1cda009f4230690008b94897e"
                ),
                "web_access": "DISABLED",
                "external_memory": "DISABLED",
                "session_isolation": "one_clean_session_per_case",
                "question_order": "as_listed_in_suite",
            },
            "responses": responses,
            "teacher_evaluation": {
                "status": "NOT_REVIEWED",
                "reviewer_role": None,
                "reviewed_on": None,
                "case_scores": [],
                "hard_fail_labels": [],
                "summary": None,
                "release_recommendation": None,
            },
        }

    def write_run_and_validate(self, run: dict) -> dict:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "run.yml"
            path.write_text(
                yaml.safe_dump(run, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            return validate_run_structure(path, self.suite, ROOT)

    def test_complete_rag_run_structure_is_valid(self) -> None:
        summary = self.write_run_and_validate(self.make_valid_rag_run())
        self.assertEqual(summary["responses"], 18)
        self.assertEqual(summary["disposition_matches"], 18)
        self.assertEqual(summary["provenance_contract_matches"], 14)
        self.assertEqual(summary["boundary_abstentions"], 4)

    def test_run_with_unknown_source_is_rejected(self) -> None:
        run = self.make_valid_rag_run()
        run["responses"][0]["cited_source_ids"] = ["source.not_registered"]
        with self.assertRaisesRegex(ValueError, "unknown sources"):
            self.write_run_and_validate(run)


if __name__ == "__main__":
    unittest.main()
