from __future__ import annotations

import copy
import json
import unittest

from scripts.p9b1q_scoped_query_ir import (
    BindingValidationError,
    QUERY_IR_SCHEMA_PATH,
    ROOT,
    build_bound_execution,
    canonical_bytes,
    execute_query_ir,
    interpret_request,
    run_scoped_query,
    validate_bound_execution,
    validate_query_ir,
    validate_schema,
)


def request(case: str, text: str) -> dict[str, str]:
    return {
        "schema_version": "1.0",
        "request_id": f"P9B1Q-{case}",
        "knowledge_version": "clonorchis_pcms_v1",
        "locale": "zh-CN",
        "query_text": text,
    }


def replace_object(sidecar, store, name, value):
    ref = store.put_object(value)
    ref["object_kind"] = sidecar["objects"][name]["object_kind"]
    sidecar["objects"][name] = ref


class ScopedQueryIRTests(unittest.TestCase):
    def test_exposure_question_is_formal_directed_intent(self):
        actual = request(
            "EXPOSURE",
            "来自流行地区并有生食淡水鱼史，可以作为华支睾吸虫病的什么证据？",
        )
        result = run_scoped_query(actual)
        query_ir = result["query_ir"]
        validate_schema(query_ir, QUERY_IR_SCHEMA_PATH)
        self.assertEqual("VALID", query_ir["interpretation_status"])
        self.assertEqual(
            ["has_diagnostic_clue"],
            [item["predicate"] for item in query_ir["relation_intents"]],
        )
        self.assertEqual("PASS", result["semantic_validation"]["result"])
        self.assertEqual(
            ["W2-ATOM-001"],
            [item["claim_id"] for item in result["retrieval_result"]["candidates"]],
        )

    def test_method_specimen_polarity_is_locally_bound(self):
        actual = request(
            "POLARITY",
            "粪便检卵未检出虫卵，但十二指肠液检卵检出虫卵，如何判断？",
        )
        result = run_scoped_query(actual)
        events = result["query_ir"]["events"]
        self.assertEqual(
            [
                ("diagnostic.stool_egg_microscopy", "STOOL", "NEGATIVE"),
                (
                    "diagnostic.duodenal_fluid_egg_microscopy",
                    "DUODENAL_FLUID",
                    "POSITIVE",
                ),
            ],
            [
                (item["method_entity_id"], item["specimen_code"], item["finding_polarity"])
                for item in events
            ],
        )
        self.assertNotIn(
            "diagnostic.stool_egg_microscopy",
            {
                entity_id
                for item in result["query_ir"]["relation_intents"]
                for entity_id in item["object_selector"]["entity_ids"]
                if item["predicate"] == "diagnosed_by"
            },
        )
        self.assertEqual(["PCMS-029"], [
            item["claim_id"] for item in result["retrieval_result"]["candidates"]
            if item["predicate"] == "diagnosed_by"
        ])

    def test_life_cycle_uses_directed_graph_and_top12(self):
        actual = request(
            "LIFE",
            "华支睾吸虫虫卵如何经过毛蚴、胞蚴、雷蚴和尾蚴发育为囊蚴，再成为成虫？",
        )
        result = run_scoped_query(actual)
        self.assertEqual("PASS", result["semantic_validation"]["result"])
        self.assertEqual(
            {"PCMS-014", "PCMS-015", "PCMS-016", "PCMS-017", "PCMS-018"},
            {item["claim_id"] for item in result["retrieval_result"]["candidates"]},
        )
        for candidate in result["retrieval_result"]["candidates"]:
            self.assertEqual("develops_into", candidate["predicate"])
            self.assertIsNotNone(candidate["subject"])
            self.assertIsNotNone(candidate["object"])

    def test_excluded_control_becomes_prohibition(self):
        actual = request(
            "CONTROL",
            "防控华支睾吸虫病时采用改善卫生设施和综合防控，但不采用减少动物粪便污染，哪些措施被肯定？",
        )
        result = run_scoped_query(actual)
        query_ir = result["query_ir"]
        self.assertEqual("PASS", result["semantic_validation"]["result"])
        self.assertEqual(
            [("controlled_by", "EXPLICIT_EXCLUSION")],
            [
                (item["predicate"], item["reason"])
                for item in query_ir["forbidden_relation_intents"]
            ],
        )
        self.assertNotIn(
            "intervention.reduce_animal_fecal_contamination",
            {
                candidate["object"]
                for candidate in result["retrieval_result"]["candidates"]
            },
        )

    def test_unresolved_or_is_structured_and_fail_closed(self):
        actual = request(
            "OR",
            "应选择粪便检卵或者十二指肠液检卵作为确证方法？",
        )
        result = run_scoped_query(actual)
        query_ir = result["query_ir"]
        self.assertEqual("AMBIGUOUS", query_ir["interpretation_status"])
        ambiguity = query_ir["ambiguities"][0]
        self.assertEqual("OR_SELECTION", ambiguity["ambiguity_type"])
        self.assertEqual(2, len(ambiguity["candidate_options"]))
        self.assertEqual("FAIL_CLOSED", result["semantic_validation"]["result"])
        self.assertIsNone(result["retrieval_result"])

    def test_deterministic_result_arrays_reject_reordering(self):
        actual = request(
            "ORDER",
            "粪便检卵检出华支睾吸虫虫卵，可形成哪些诊断证据并如何理解其边界？",
        )
        query_ir = interpret_request(actual)
        result = validate_query_ir(actual, query_ir)
        self.assertEqual("PASS", result["result"])
        self.assertGreaterEqual(
            len(result["executable_narrative_intent_ids"]), 2
        )
        reordered = copy.deepcopy(result)
        reordered["executable_narrative_intent_ids"].reverse()
        self.assertNotEqual(canonical_bytes(result), canonical_bytes(reordered))

    def test_explicit_later_finding_supersedes_same_event(self):
        actual = request(
            "OVERRIDE",
            "粪便检卵未检出虫卵，后来复查粪便检卵检出虫卵，如何判断？",
        )
        result = run_scoped_query(actual)
        self.assertEqual("PASS", result["semantic_validation"]["result"])
        self.assertEqual(
            ["E01"], result["semantic_validation"]["superseded_event_ids"]
        )
        self.assertEqual(
            [("E01", "E02")],
            [
                (item["earlier_event_id"], item["later_event_id"])
                for item in result["query_ir"]["resolved_overrides"]
            ],
        )

    def test_double_negative_is_positive_but_hypothetical_does_not_execute(self):
        positive = run_scoped_query(request(
            "DOUBLE-NEG",
            "粪便检卵并非没有检出虫卵，这次结果如何记录？",
        ))
        self.assertEqual(
            "POSITIVE", positive["query_ir"]["events"][0]["finding_polarity"]
        )
        hypothetical = run_scoped_query(request(
            "HYPOTHETICAL",
            "如果粪便检卵检出虫卵，是否就能确诊？",
        ))
        self.assertEqual(
            "HYPOTHETICAL",
            hypothetical["query_ir"]["events"][0]["assertion_status"],
        )
        self.assertIsNone(hypothetical["retrieval_result"])

    def test_nonconfirmatory_clue_has_closed_confirmation_contrast(self):
        actual = request(
            "CONTRAST",
            "胆道影像异常只是辅助线索，不能单独确诊华支睾吸虫病，应怎样取得确证？",
        )
        result = run_scoped_query(actual)
        self.assertEqual("PASS", result["semantic_validation"]["result"])
        contrast = [
            item for item in result["query_ir"]["relation_intents"]
            if item["derivation_mode"] == "CLOSED_CONTRAST_DERIVED"
        ]
        self.assertEqual(1, len(contrast))
        self.assertEqual("diagnosed_by", contrast[0]["predicate"])
        self.assertEqual("REQUIRED_CONTRAST", contrast[0]["activation_policy"])
        self.assertIn(
            "pathogen_confirmation",
            [item["role_value"] for item in result["query_ir"]["required_roles"]],
        )

    def test_implicit_life_cycle_path_uses_open_typed_graph_edge(self):
        actual = request(
            "IMPLICIT-LIFE",
            "不直接点出各虫期名称，只按事件描述：螺内连续发育、游出后进入鱼体、被人摄入后在胆管成熟。系统应召回哪条完整发育路径？",
        )
        result = run_scoped_query(actual)
        self.assertEqual("PASS", result["semantic_validation"]["result"])
        self.assertIn(
            "develops_into",
            [item["predicate"] for item in result["query_ir"]["relation_intents"]],
        )
        self.assertEqual(
            {"PCMS-014", "PCMS-015", "PCMS-016", "PCMS-017", "PCMS-018", "PCMS-019"},
            {item["claim_id"] for item in result["retrieval_result"]["candidates"]},
        )

    def test_ordered_reviewed_hosts_form_directed_role_intents(self):
        actual = request(
            "HOST-EVENTS",
            "虫体先后借助淡水螺和淡水鱼，最后在人这一宿主体内成熟；三类宿主各是什么角色？",
        )
        result = run_scoped_query(actual)
        self.assertEqual(
            {"has_first_intermediate_host", "has_second_intermediate_host", "has_definitive_host"},
            {item["predicate"] for item in result["query_ir"]["relation_intents"]},
        )
        self.assertEqual(
            {"PCMS-020", "PCMS-021", "PCMS-022"},
            {item["claim_id"] for item in result["retrieval_result"]["candidates"]},
        )

    def test_hazard_classification_carries_individual_boundary(self):
        result = run_scoped_query(request(
            "HAZARD",
            "华支睾吸虫病的IARC 1类致癌分类是否意味着个体一定患癌？",
        ))
        self.assertEqual("PASS", result["semantic_validation"]["result"])
        self.assertIn(
            "hazard_class_is_not_individual_certainty",
            [item["role_value"] for item in result["query_ir"]["required_roles"]],
        )

    def test_semantic_validator_rejects_cross_clause_event_span(self):
        actual = request(
            "EVENT-SPAN",
            "胆道影像异常只是辅助线索，华支睾吸虫病仍需确证。",
        )
        query_ir = interpret_request(actual)
        changed = copy.deepcopy(query_ir)
        changed["events"][0]["source_span"] = {
            "start_char": 0,
            "end_char": len(actual["query_text"]) - 1,
            "text": actual["query_text"][:-1],
        }
        result = validate_query_ir(actual, changed)
        self.assertEqual("FAIL_CLOSED", result["result"])
        self.assertIn("EVENT_FIELD_OR_TYPE_MISMATCH", result["fail_codes"])


class BindingChainTests(unittest.TestCase):
    def setUp(self):
        self.actual = request(
            "BIND",
            "来自流行地区并有生食淡水鱼史，可以作为华支睾吸虫病的什么证据？",
        )
        self.sidecar, self.store, self.bundle = build_bound_execution(self.actual)

    def test_positive_chain_recomputes(self):
        evidence = validate_bound_execution(self.sidecar, self.store)
        self.assertEqual("PASS", evidence["result"])

    def test_ambiguous_chain_has_no_retrieval(self):
        actual = request(
            "AMB-BIND",
            "应选择粪便检卵或者十二指肠液检卵作为确证方法？",
        )
        sidecar, store, _ = build_bound_execution(actual)
        self.assertEqual("QUERY_IR_FAIL_CLOSED", sidecar["disposition"])
        self.assertIsNone(sidecar["objects"]["retrieval_result"])
        self.assertEqual("PASS", validate_bound_execution(sidecar, store)["result"])

    def test_unresolvable_object_fails(self):
        sidecar = copy.deepcopy(self.sidecar)
        sidecar["objects"]["query_ir"]["content_address"] = (
            "private-audit://objects/sha256/" + "0" * 64
        )
        with self.assertRaises(BindingValidationError):
            validate_bound_execution(sidecar, self.store)

    def test_store_byte_tamper_fails(self):
        store = self.store.clone()
        address = self.sidecar["objects"]["request"]["content_address"]
        store.replace_for_test(address, b"{}")
        with self.assertRaises(BindingValidationError):
            validate_bound_execution(self.sidecar, store)

    def test_request_query_ir_mismatch_fails(self):
        sidecar = copy.deepcopy(self.sidecar)
        changed = copy.deepcopy(self.bundle["execution"]["query_ir"])
        changed["request_id"] = "OTHER"
        replace_object(sidecar, self.store, "query_ir", changed)
        with self.assertRaises(BindingValidationError):
            validate_bound_execution(sidecar, self.store)

    def test_semantic_reordering_fails_recomputation(self):
        sidecar = copy.deepcopy(self.sidecar)
        semantic = copy.deepcopy(self.bundle["execution"]["semantic_validation"])
        self.assertGreaterEqual(len(semantic["executable_narrative_intent_ids"]), 2)
        semantic["executable_narrative_intent_ids"].reverse()
        replace_object(sidecar, self.store, "semantic_validation", semantic)
        with self.assertRaises(BindingValidationError) as caught:
            validate_bound_execution(sidecar, self.store)
        self.assertEqual("RECOMPUTE_QUERY_IR_SEMANTIC_VALIDATION", caught.exception.stage)

    def test_normative_artifact_substitution_fails(self):
        sidecar = copy.deepcopy(self.sidecar)
        sidecar["schema_artifacts"]["query_ir_schema"] = copy.deepcopy(
            sidecar["schema_artifacts"]["semantic_validation_result_schema"]
        )
        with self.assertRaises(BindingValidationError):
            validate_bound_execution(sidecar, self.store)

    def test_component_executable_drift_fails(self):
        store = self.store.clone()
        address = self.sidecar["components"]["graph_executor"][
            "executable_artifact_address"
        ]
        store.replace_for_test(address, store.resolve(address) + b"\n")
        with self.assertRaises(BindingValidationError):
            validate_bound_execution(self.sidecar, store)

    def test_component_configuration_substitution_fails_even_if_readdressed(self):
        sidecar = copy.deepcopy(self.sidecar)
        changed = canonical_bytes({"top_k": 12, "mapping_sha256": "0" * 64})
        digest, address, length = self.store.put_bytes(changed, artifact=True)
        component = sidecar["components"]["graph_executor"]
        component["configuration_sha256"] = digest
        component["configuration_address"] = address
        component["configuration_byte_length"] = length
        build = canonical_bytes({
            "component_kind": component["component_kind"],
            "implementation_kind": component["implementation_kind"],
            "executable_artifact_sha256": component["executable_artifact_sha256"],
            "configuration_sha256": digest,
            "build_format": "P9B1Q_DETERMINISTIC_COMPONENT_V1",
        })
        build_digest, build_address, build_length = self.store.put_bytes(
            build, artifact=True
        )
        component["build_manifest_sha256"] = build_digest
        component["build_manifest_address"] = build_address
        component["build_manifest_byte_length"] = build_length
        with self.assertRaises(BindingValidationError):
            validate_bound_execution(sidecar, self.store)

    def test_logical_bundle_digest_cannot_be_manifest_byte_digest(self):
        sidecar = copy.deepcopy(self.sidecar)
        sidecar["runtime_bundle_sha256"] = sidecar["authority_artifacts"][
            "runtime_bundle"
        ]["artifact_sha256"]
        with self.assertRaises(BindingValidationError):
            validate_bound_execution(sidecar, self.store)

    def test_state_summary_tamper_fails(self):
        sidecar = copy.deepcopy(self.sidecar)
        sidecar["state_summary"]["semantic_executable_intent_count"] += 1
        with self.assertRaises(BindingValidationError):
            validate_bound_execution(sidecar, self.store)

    def test_response_or_audit_reuse_fails(self):
        other = request("OTHER", "华支睾吸虫病用什么药物治疗？")
        other_sidecar, other_store, _ = build_bound_execution(other)
        for object_name in ("response", "audit_record"):
            with self.subTest(object_name=object_name):
                sidecar = copy.deepcopy(self.sidecar)
                ref = other_sidecar["objects"][object_name]
                data = other_store.resolve(ref["content_address"])
                inserted = self.store.put_bytes(data, artifact=False)
                sidecar["objects"][object_name] = {
                    "object_kind": ref["object_kind"],
                    "content_sha256": inserted[0],
                    "content_address": inserted[1],
                    "media_type": "application/json",
                    "byte_length": inserted[2],
                }
                with self.assertRaises(BindingValidationError):
                    validate_bound_execution(sidecar, self.store)


if __name__ == "__main__":
    unittest.main()
