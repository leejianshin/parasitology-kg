from __future__ import annotations

import copy
import hashlib
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
    analyze_query,
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

    def test_acceptance_record_hashes_and_example_result_are_current(self) -> None:
        acceptance = yaml.safe_load(
            (
                ROOT
                / "phase9/clonorchis-sinensis/p9b1-local-acceptance.yml"
            ).read_text(encoding="utf-8")
        )
        for artifact, declaration in acceptance["frozen_artifacts"].items():
            if not isinstance(declaration, dict) or "path" not in declaration:
                continue
            with self.subTest(artifact=artifact):
                actual = hashlib.sha256(
                    (ROOT / declaration["path"]).read_bytes()
                ).hexdigest()
                self.assertEqual(declaration["sha256"], actual)
        self.assertEqual(
            acceptance["acceptance_results"]["example_result_sha256"],
            canonical_sha256(self.result),
        )

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

    def test_revision_2_review_failures_are_frozen_and_now_recalled(self) -> None:
        path = (
            ROOT
            / "phase9/clonorchis-sinensis/acceptance-cases"
            / "p9b1-revision2-failure-regression.yml"
        )
        suite = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual("FROZEN_BEFORE_REVISION_3_IMPLEMENTATION", suite["status"])
        self.assertEqual(6, len(suite["cases"]))
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

    def test_revision_3_blind_suite_is_now_public_regression(self) -> None:
        path = (
            ROOT
            / "phase9/clonorchis-sinensis/acceptance-cases"
            / "p9b1-revision3-blind-disclosed-regression.yml"
        )
        suite = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(
            "DISCLOSED_AFTER_REVISION_3_COMMIT_PUBLIC_REGRESSION",
            suite["status"],
        )
        self.assertEqual(8, len(suite["cases"]))
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

    def test_revision_4_blind_suite_is_now_public_regression(self) -> None:
        path = (
            ROOT
            / "phase9/clonorchis-sinensis/acceptance-cases"
            / "p9b1-revision4-blind-disclosed-regression.yml"
        )
        suite = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(
            "DISCLOSED_AFTER_REVISION_4_COMMIT_PUBLIC_REGRESSION",
            suite["status"],
        )
        self.assertEqual(15, len(suite["cases"]))
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

    def test_revision_5_blind_suite_is_now_public_regression(self) -> None:
        path = (
            ROOT
            / "phase9/clonorchis-sinensis/acceptance-cases"
            / "p9b1-revision5-blind-disclosed-regression.yml"
        )
        suite = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(
            "DISCLOSED_AFTER_REVISION_5_COMMIT_PUBLIC_REGRESSION",
            suite["status"],
        )
        self.assertEqual(16, len(suite["cases"]))
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

    def test_mixed_polarity_is_bound_to_each_diagnostic_method(self) -> None:
        index = build_index(ROOT)
        for query_text in (
            "十二指肠引流液查卵未报阳性，粪便涂片随后寻获虫卵。",
            "十二指肠液检卵和粪便镜检结果分别阴性和阳性。",
        ):
            with self.subTest(query=query_text):
                plan = analyze_query(query_text, index)
                observations = {
                    item.evidence_entity_id: item.polarity
                    for item in plan.evidence_observations
                }
                self.assertEqual(
                    "negative",
                    observations["diagnostic.duodenal_fluid_egg_microscopy"],
                )
                self.assertEqual(
                    "positive",
                    observations["diagnostic.stool_egg_microscopy"],
                )
                self.assertIn(
                    "pathogen_confirmation", plan.negated_evidence_roles
                )

    def test_negative_detection_and_morphology_disambiguation(self) -> None:
        index = build_index(ROOT)
        for query_text in (
            "便涂片没有观察见虫卵，能否排除感染？",
            "粪便检查没能观察见卵，可以从鉴别中拿掉吗？",
        ):
            with self.subTest(query=query_text):
                plan = analyze_query(query_text, index)
                self.assertEqual(
                    "negative", plan.evidence_observations[0].polarity
                )
                self.assertNotIn("morphology", plan.topic_scopes)

        morphology = analyze_query(
            "如何依据卵盖和肩峰鉴别这种虫卵的形态？", index
        )
        self.assertIn("morphology", morphology.topic_scopes)

    def test_implicit_host_stage_events_trigger_complete_life_cycle(self) -> None:
        index = build_index(ROOT)
        queries = (
            "螺内幼体转换、入鱼形成包囊、在终宿主体内成熟，接通关系。",
            "解释螺和鱼的中间宿主分工及支撑它的虫态转换。",
            "感染人的包囊幼体由哪些前序虫态形成，之后变成成虫？",
        )
        for number, query_text in enumerate(queries, 1):
            with self.subTest(query=query_text):
                plan = analyze_query(query_text, index)
                self.assertIn("life_cycle", plan.topic_scopes)
                result = retrieve(
                    request(query_text, f"P9B1-R6-LC-{number:02d}"),
                    root=ROOT,
                )
                retrieved = {item["claim_id"] for item in result["candidates"]}
                self.assertTrue({
                    "PCMS-014", "PCMS-015", "PCMS-016", "PCMS-017",
                    "PCMS-018", "PCMS-019",
                } <= retrieved)

    def test_all_nonconfirmatory_roles_require_pathogen_contrast(self) -> None:
        index = build_index(ROOT)
        for query_text in (
            "长期吃生淡水鱼只是流行病学线索，确认边界是什么？",
            "MRI只能提供辅助线索，怎样形成最终判断？",
            "来自流行区只能算线索，确诊还缺什么？",
        ):
            with self.subTest(query=query_text):
                plan = analyze_query(query_text, index)
                self.assertIn(
                    "pathogen_confirmation", plan.required_evidence_roles
                )
                self.assertIn(
                    "diagnostic_evidence_roles", plan.coverage_groups
                )

    def test_formal_control_roles_are_exposed_in_query_plan(self) -> None:
        plan = analyze_query(
            "社区排污、犬猫猪粪便和改厕措施的靶点及外推边界是什么？",
            build_index(ROOT),
        )
        self.assertIn("control", plan.topic_scopes)
        self.assertTrue({
            "interrupt_egg_entry_to_intermediate_host_waters",
            "mechanism_and_recommendation",
            "recommendation_not_local_effect",
            "recommendation_not_quantified_effect",
            "universal_elimination_claim_false",
        } <= set(plan.control_semantic_roles))
        self.assertFalse(plan.evidence_observations)

    def test_negative_polarity_is_compositional_and_does_not_negate_conclusions(self) -> None:
        index = build_index(ROOT)
        negated_queries = (
            "粪样里没找到虫卵，这次检查如何解释？",
            "寄生虫学检查没有阳性发现，能据此排除吗？",
            "粪检报告为阴性时，证据角色是什么？",
            "镜检未能发现虫卵，是否等于没有感染？",
            "病原学检查查无虫卵，现有线索还能否确认？",
            "粪便标本里查不出虫卵，是否代表一定未感染？",
        )
        for query_text in negated_queries:
            with self.subTest(query=query_text):
                plan = analyze_query(query_text, index)
                self.assertIn(
                    "pathogen_confirmation", plan.negated_evidence_roles
                )
                self.assertIn("diagnosis", plan.topic_scopes)

        conclusion = analyze_query(
            "现有线索不能排除感染，但尚不能确诊。", index
        )
        self.assertNotIn(
            "pathogen_confirmation", conclusion.negated_evidence_roles
        )

    def test_formal_diagnostic_roles_trigger_confirmation_contrast_group(self) -> None:
        index = build_index(ROOT)
        plan = analyze_query(
            "MRI显示胆道改变，作最终判断还应合并哪些资料？", index
        )
        self.assertTrue({
            "diagnostic_evidence_integration",
            "diagnostic_confirmation_limit",
        } <= set(plan.semantic_roles))
        self.assertIn("pathogen_confirmation", plan.evidence_roles)
        self.assertIn("diagnostic_evidence_roles", plan.coverage_groups)
        result = retrieve(
            request(
                "MRI显示胆道改变，作最终判断还应合并哪些资料？",
                "P9B1-R5-DIAG",
            ),
            root=ROOT,
        )
        retrieved = {item["claim_id"] for item in result["candidates"]}
        self.assertTrue({
            "W2-ATOM-023", "W2-ATOM-024", "W2-ATOM-025", "PCMS-028"
        } <= retrieved)

    def test_life_cycle_and_control_compositions_use_typed_coverage(self) -> None:
        index = build_index(ROOT)
        life_cycle = analyze_query(
            "从卵到成虫的逐级变化应怎样衔接？", index
        )
        self.assertIn("life_cycle", life_cycle.topic_scopes)
        self.assertEqual(
            "life_cycle_development", life_cycle.coverage_groups[0]
        )
        life_cycle_range = analyze_query(
            "虫卵最终成为成虫要经过哪些中间阶段？", index
        )
        self.assertIn("life_cycle", life_cycle_range.topic_scopes)

        control = analyze_query(
            "改厕和处理畜禽粪污如何切断水域传播，能否保证根除？",
            index,
        )
        self.assertIn("intervention", control.entity_types)
        self.assertIn("control", control.topic_scopes)
        result = retrieve(
            request(
                "改厕和处理畜禽粪污如何切断水域传播，能否保证根除？",
                "P9B1-R5-CONTROL",
            ),
            root=ROOT,
        )
        retrieved = {item["claim_id"] for item in result["candidates"]}
        self.assertTrue({
            "W2-ATOM-026", "W2-ATOM-028", "PCMS-036"
        } <= retrieved)
        control_variant = analyze_query(
            "改良厕所并减少家畜排泄物进入水域，属于哪类治理？",
            index,
        )
        self.assertIn("intervention", control_variant.entity_types)
        self.assertIn("control", control_variant.topic_scopes)

    def test_formal_entity_types_and_semantic_roles_drive_query_plan(self) -> None:
        index = build_index(ROOT)
        records = {item.claim_id: item for item in index.records}
        self.assertEqual(
            ("diagnostic_method", "disease"),
            records["PCMS-028"].entity_types,
        )
        self.assertIn(
            "parasitological_confirmation",
            records["PCMS-028"].semantic_roles,
        )
        self.assertIn(
            "diagnostic_confirmation_limit",
            records["W2-ATOM-025"].semantic_roles,
        )

        plan = analyze_query(
            "超声提示胆道异常但没有检出虫卵，能否确诊？",
            index,
        )
        self.assertIn("diagnostic_method", plan.entity_types)
        self.assertIn("auxiliary", plan.semantic_roles)
        self.assertIn("parasitological_confirmation", plan.semantic_roles)
        self.assertIn("pathogen_confirmation", plan.negated_evidence_roles)
        self.assertEqual(("diagnosis",), plan.topic_scopes)

        detection_phrases = {
            "粪便镜检见虫卵，这属于哪类证据？": False,
            "便检未见虫卵，能否排除感染？": True,
            "粪样查到虫卵，能支持到什么程度？": False,
        }
        for query, is_negated in detection_phrases.items():
            with self.subTest(query=query):
                detection_plan = analyze_query(query, index)
                self.assertIn(
                    "parasitological_confirmation",
                    detection_plan.semantic_roles,
                )
                self.assertIn(
                    "pathogen_confirmation", detection_plan.evidence_roles
                )
                self.assertEqual(
                    is_negated,
                    "pathogen_confirmation"
                    in detection_plan.negated_evidence_roles,
                )

        source = (
            ROOT / "scripts/p9b1_local_retrieval.py"
        ).read_text(encoding="utf-8")
        for prefix in ("stage.", "host.", "treatment.", "hazard."):
            self.assertNotIn(f'startswith("{prefix}")', source)

    def test_query_plan_separates_entities_roles_intents_and_scope(self) -> None:
        index = build_index(ROOT)
        formal_alias = analyze_query("MRI能否作为确诊依据？", index)
        self.assertIn("diagnostic.biliary_imaging", formal_alias.entity_ids)
        self.assertEqual(
            ("imaging_auxiliary_clue", "pathogen_confirmation"),
            formal_alias.evidence_roles,
        )
        self.assertIn("diagnosis", formal_alias.topic_scopes)

        diagnosis = analyze_query(
            "吃过生腌淡水鱼，B超发现胆管改变，粪标本看到卵，三种信息该如何判读？",
            index,
        )
        self.assertEqual(
            {
                "epidemiologic_exposure_clue",
                "imaging_auxiliary_clue",
                "pathogen_confirmation",
            },
            set(diagnosis.evidence_roles),
        )
        self.assertIn("diagnosis", diagnosis.topic_scopes)
        self.assertEqual(
            {
                "diagnosed_by", "diagnostic_stage_for", "has_diagnostic_clue"
            },
            set(diagnosis.relation_intents),
        )
        self.assertTrue({
            "behavior.raw_undercooked_freshwater_fish_consumption",
            "diagnostic.biliary_imaging",
            "diagnostic.stool_egg_microscopy",
        } <= set(diagnosis.entity_ids))

        stage_roles = analyze_query(
            "人吃进去后真正建立感染的虫期是什么，主要引起胆道损伤的虫期是什么？",
            index,
        )
        self.assertEqual(("stage_roles",), stage_roles.topic_scopes)
        self.assertEqual(
            {"infective_stage_for", "pathogenic_stage_for"},
            set(stage_roles.relation_intents),
        )

        source_scope = analyze_query(
            "虫体变化、处方选择和肿瘤风险分级分别出自哪些机构或文献？",
            index,
        )
        self.assertEqual(
            {"life_cycle", "treatment", "carcinogenicity", "source_traceability"},
            set(source_scope.topic_scopes),
        )

    def test_coverage_groups_are_selected_by_graph_semantics_not_claim_literals(self) -> None:
        source = (
            ROOT / "scripts/p9b1_local_retrieval.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("CONCEPT_RULES", source)
        suite = yaml.safe_load(
            (
                ROOT
                / "phase9/clonorchis-sinensis/acceptance-cases"
                / "p9b1-revision2-failure-regression.yml"
            ).read_text(encoding="utf-8")
        )
        for case in suite["cases"]:
            for claim_id in case["required_claim_ids"]:
                self.assertNotIn(
                    repr(claim_id), source,
                    msg=f"implementation hard-codes regression claim {claim_id}",
                )

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
