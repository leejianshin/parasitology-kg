from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.p9b1_local_retrieval import (  # noqa: E402
    ALLOWED_RUNTIME_INPUTS,
    BUNDLE_MANIFEST_PATH,
    REQUEST_SCHEMA_PATH,
    RESULT_SCHEMA_PATH,
    RETRIEVAL_CONTRACT_PATH,
    RUNTIME_CONTRACT_PATH,
    build_index,
    canonical_sha256,
    retrieve,
    validate_request,
    validate_result,
)


def request(query: str, request_id: str = "P9B1-TEST-001") -> dict:
    return {
        "schema_version": "1.0",
        "request_id": request_id,
        "knowledge_version": "clonorchis_pcms_v1",
        "locale": "zh-CN",
        "query_text": query,
    }


class P9B1RetrievalTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.request = request(
            "生食鱼史、影像学和粪便检卵在诊断中分别承担什么角色？"
        )
        self.result = retrieve(self.request, root=ROOT)

    def _copy_runtime(self, target: Path) -> None:
        paths = [
            *ALLOWED_RUNTIME_INPUTS,
            str(BUNDLE_MANIFEST_PATH),
            str(RUNTIME_CONTRACT_PATH),
            str(REQUEST_SCHEMA_PATH),
            str(RESULT_SCHEMA_PATH),
            str(RETRIEVAL_CONTRACT_PATH),
        ]
        for relative in paths:
            source = ROOT / relative
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    def test_verified_index_has_frozen_authority_counts(self) -> None:
        index = build_index(ROOT)
        self.assertEqual(31, len(index.entities))
        self.assertEqual(48, len(index.records))
        self.assertEqual(48, len({item.claim_id for item in index.records}))
        self.assertEqual(
            "cc812fd0085085d5e5e10758d0de3b6480680e3bd3ea908aeee446d57271481f",
            index.bundle_sha256,
        )

    def test_projected_claims_match_independent_authority_assertions(self) -> None:
        records = {item.claim_id: item.payload() for item in build_index(ROOT).records}
        citations = [
            {
                "source_id": "source.cdc_clinical_overview_clonorchis_2024",
                "source_label": "Clinical Overview of Clonorchis",
                "locator": "Diagnosis",
            },
            {
                "source_id": "source.who_foodborne_trematode_fact_sheet",
                "source_label": "Foodborne trematode infections",
                "locator": "Diagnosis",
            },
        ]
        expected = {
            "W2-ATOM-024": {
                "statement_zh": (
                    "华支睾吸虫病影像线索应结合暴露史、临床和实验室证据综合判断。"
                ),
                "semantic_role": "diagnostic_evidence_integration",
            },
            "W2-ATOM-025": {
                "statement_zh": "影像不能单独确诊华支睾吸虫病。",
                "semantic_role": "diagnostic_confirmation_limit",
            },
        }
        for claim_id, authority in expected.items():
            with self.subTest(claim_id=claim_id):
                record = records[claim_id]
                self.assertEqual("supporting_narrative", record["claim_kind"])
                self.assertEqual("diagnostic.biliary_imaging", record["subject"])
                self.assertIsNone(record["predicate"])
                self.assertIsNone(record["object"])
                self.assertEqual(
                    ["diagnostic.biliary_imaging", "disease.clonorchiasis"],
                    record["entity_ids"],
                )
                self.assertEqual(authority["statement_zh"], record["statement_zh"])
                self.assertEqual(claim_id, record["qualifiers"]["source_atom_id"])
                self.assertEqual(
                    authority["semantic_role"],
                    record["qualifiers"]["semantic_role"],
                )
                self.assertEqual("W2-ATOM-023", record["qualifiers"]["anchor_claim_id"])
                self.assertEqual(citations, record["citations"])
        self.assertNotEqual(
            records["W2-ATOM-024"]["statement_zh"],
            records["W2-ATOM-025"]["statement_zh"],
        )

    def test_public_retrieve_has_no_external_index_injection_path(self) -> None:
        forged = build_index(ROOT)
        with self.assertRaisesRegex(TypeError, "unexpected keyword argument 'index'"):
            retrieve(self.request, root=ROOT, index=forged)  # type: ignore[call-arg]

    def test_result_binds_actual_request_and_verified_index(self) -> None:
        validate_result(self.result, self.request, root=ROOT)
        self.assertEqual(canonical_sha256(self.request), self.result["request_sha256"])
        self.assertEqual(build_index(ROOT).index_sha256, self.result["index_sha256"])

    def test_relation_direction_is_preserved(self) -> None:
        result = retrieve(
            request("华支睾吸虫经历哪些生活史环节，各阶段如何衔接？"),
            root=ROOT,
        )
        claim = next(item for item in result["candidates"] if item["claim_id"] == "PCMS-014")
        self.assertEqual("stage.clonorchis_egg", claim["subject"])
        self.assertEqual("develops_into", claim["predicate"])
        self.assertEqual("stage.clonorchis_miracidium", claim["object"])
        self.assertEqual([claim["subject"], claim["object"]], claim["entity_ids"])

    def test_all_fixed_regression_cases_recall_required_claims(self) -> None:
        suite = yaml.safe_load(
            (ROOT / "phase7/clonorchis-sinensis/pilot-content-minimum-set-regression.yml").read_text(encoding="utf-8")
        )
        for number, case in enumerate(suite["test_cases"], 1):
            with self.subTest(case=case["case_id"]):
                result = retrieve(
                    request(case["question_zh"], f"P9B1-FIXED-{number:02d}"),
                    root=ROOT,
                )
                retrieved = {item["claim_id"] for item in result["candidates"]}
                self.assertTrue(set(case.get("required_claim_ids", [])) <= retrieved)

    def test_fixed_paraphrase_suite_recalls_required_claims(self) -> None:
        suite = yaml.safe_load(
            (ROOT / "phase9/clonorchis-sinensis/acceptance-cases/p9b1-paraphrase-cases.yml").read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(len(suite["cases"]), 8)
        for case in suite["cases"]:
            with self.subTest(case=case["case_id"]):
                result = retrieve(
                    request(case["query_zh"], case["case_id"]), root=ROOT
                )
                retrieved = {item["claim_id"] for item in result["candidates"]}
                self.assertTrue(set(case["required_claim_ids"]) <= retrieved)

    def test_independent_review_held_out_paraphrases_recall_required_claims(self) -> None:
        suite = yaml.safe_load(
            (
                ROOT
                / "phase9/clonorchis-sinensis/acceptance-cases"
                / "p9b1-held-out-paraphrase-cases.yml"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(4, len(suite["cases"]))
        implementation = (
            ROOT / "scripts/p9b1_local_retrieval.py"
        ).read_text(encoding="utf-8")
        for case in suite["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertNotIn(case["case_id"], implementation)
                self.assertNotIn(case["query_zh"], implementation)
                result = retrieve(
                    request(case["query_zh"], case["case_id"]), root=ROOT
                )
                retrieved = {item["claim_id"] for item in result["candidates"]}
                self.assertTrue(set(case["required_claim_ids"]) <= retrieved)

    def test_three_repeated_runs_are_byte_deterministic(self) -> None:
        outputs = [
            json.dumps(retrieve(self.request, root=ROOT), ensure_ascii=False, sort_keys=True)
            for _ in range(3)
        ]
        self.assertEqual(1, len(set(outputs)))

    def test_cross_process_hash_seed_does_not_change_result(self) -> None:
        code = (
            "import json; from scripts.p9b1_local_retrieval import retrieve; "
            f"r={self.request!r}; print(json.dumps(retrieve(r),ensure_ascii=False,sort_keys=True,separators=(',',':')))"
        )
        outputs = []
        for seed in ("1", "7", "23"):
            environment = dict(**__import__("os").environ, PYTHONHASHSEED=seed)
            outputs.append(
                subprocess.check_output(
                    [sys.executable, "-c", code], cwd=ROOT, env=environment,
                    text=True,
                )
            )
        self.assertEqual(1, len(set(outputs)))

    def test_malformed_result_schema_instances_are_rejected(self) -> None:
        mutations = []
        item = copy.deepcopy(self.result)
        item["request_id"] = " bad"
        mutations.append(item)
        item = copy.deepcopy(self.result)
        item["normalized_query"] = ""
        mutations.append(item)
        item = copy.deepcopy(self.result)
        item["excluded_candidate_count"] = -999
        mutations.append(item)
        item = copy.deepcopy(self.result)
        item["candidates"][0]["statement_zh"] = 7
        mutations.append(item)
        item = copy.deepcopy(self.result)
        item["candidates"][0]["entity_ids"] *= 2
        mutations.append(item)
        item = copy.deepcopy(self.result)
        item["candidates"][0]["qualifiers"] = []
        mutations.append(item)
        item = copy.deepcopy(self.result)
        item["candidates"][0]["qualifiers"]["malformed"] = ["array"]
        mutations.append(item)
        item = copy.deepcopy(self.result)
        item["candidates"][0]["citations"][0]["locator"] = ""
        mutations.append(item)
        item = copy.deepcopy(self.result)
        item["candidates"][0]["unexpected"] = True
        mutations.append(item)
        for number, malformed in enumerate(mutations):
            with self.subTest(mutation=number):
                with self.assertRaisesRegex(ValueError, "schema validation failed"):
                    validate_result(malformed, self.request, root=ROOT)

    def test_semantically_forged_candidates_are_rejected(self) -> None:
        mutations = []
        for field, value in (
            ("claim_id", "PCMS-999"),
            ("subject", "entity.unknown"),
            ("object", "entity.unknown"),
            ("statement_zh", "伪造陈述"),
        ):
            item = copy.deepcopy(self.result)
            item["candidates"][0][field] = value
            mutations.append(item)
        item = copy.deepcopy(self.result)
        item["candidates"][0]["citations"][0]["source_id"] = "source.fake"
        mutations.append(item)
        item = copy.deepcopy(self.result)
        item["candidates"][0]["citations"][0]["locator"] = "伪造定位"
        mutations.append(item)
        item = copy.deepcopy(self.result)
        candidate = item["candidates"][0]
        candidate["subject"], candidate["object"] = candidate["object"], candidate["subject"]
        mutations.append(item)
        for number, forged in enumerate(mutations):
            with self.subTest(mutation=number):
                with self.assertRaisesRegex(ValueError, "result semantic mismatch"):
                    validate_result(forged, self.request, root=ROOT)

    def test_ranking_and_request_binding_tampering_are_rejected(self) -> None:
        rank = copy.deepcopy(self.result)
        rank["candidates"][0]["score"] += 1
        with self.assertRaisesRegex(ValueError, "result semantic mismatch"):
            validate_result(rank, self.request, root=ROOT)

        changed_request = copy.deepcopy(self.request)
        changed_request["query_text"] = "WHO推荐何种治疗？"
        with self.assertRaisesRegex(ValueError, "result semantic mismatch"):
            validate_result(self.result, changed_request, root=ROOT)

    def test_bundle_tamper_fails_before_index_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_runtime(root)
            nodes = root / ALLOWED_RUNTIME_INPUTS[0]
            nodes.write_bytes(nodes.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                retrieve(self.request, root=root)

    def test_authority_projection_tamper_fails_before_index_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy_runtime(root)
            projection = root / ALLOWED_RUNTIME_INPUTS[4]
            projection.write_bytes(projection.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                retrieve(self.request, root=root)

    def test_unreviewed_entity_or_claim_tamper_fails_closed(self) -> None:
        for relative, needle, replacement in (
            (ALLOWED_RUNTIME_INPUTS[0], '"review_status":"reviewed"', '"review_status":"draft"'),
            (ALLOWED_RUNTIME_INPUTS[1], '"relation_status":"reviewed"', '"relation_status":"draft"'),
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._copy_runtime(root)
                path = root / relative
                path.write_text(path.read_text(encoding="utf-8").replace(needle, replacement, 1), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "runtime file (size|SHA) mismatch"):
                    retrieve(self.request, root=root)

    def test_control_and_schema_tamper_fail_closed(self) -> None:
        for relative in (
            RUNTIME_CONTRACT_PATH,
            REQUEST_SCHEMA_PATH,
            RESULT_SCHEMA_PATH,
            RETRIEVAL_CONTRACT_PATH,
        ):
            with self.subTest(relative=str(relative)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._copy_runtime(root)
                path = root / relative
                path.write_bytes(path.read_bytes() + b"\n")
                with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                    retrieve(self.request, root=root)

    def test_invalid_request_and_top_k_fail_before_retrieval(self) -> None:
        invalid = copy.deepcopy(self.request)
        invalid["query_text"] = ""
        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            validate_request(invalid, ROOT)
        for value in (0, 51, True, 1.5):
            with self.subTest(top_k=value):
                with self.assertRaisesRegex(ValueError, "top_k"):
                    retrieve(self.request, root=ROOT, top_k=value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
