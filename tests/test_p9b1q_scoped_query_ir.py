from __future__ import annotations

import copy
import json
import unittest
from unittest import mock

from scripts.p9b1q_scoped_query_ir import (
    BindingValidationError,
    C1ValidationError,
    CLAUSE_AST_SCHEMA_PATH,
    NORMALIZED_REQUEST_SCHEMA_PATH,
    QUERY_IR_SCHEMA_PATH,
    ROOT,
    build_bound_execution,
    canonical_bytes,
    canonical_sha256,
    compile_c1,
    compile_clause_ast,
    execute_query_ir,
    interpret_request,
    normalize_request,
    run_scoped_query,
    validate_bound_execution,
    validate_c1_clause_ast,
    validate_c1_normalized_request,
    validate_c1_stop_boundary,
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


class C1RequestNormalizationTests(unittest.TestCase):
    def test_s0_normal_request_is_schema_valid_and_bound(self):
        actual = request("C1-S0", "粪便检卵阳性。")
        normalized = normalize_request(actual)
        validate_schema(normalized, NORMALIZED_REQUEST_SCHEMA_PATH)
        validate_c1_normalized_request(actual, normalized)
        self.assertEqual(actual["query_text"], normalized["normalized_query_text"])
        self.assertEqual(["NONE"], normalized["normalization_operations"])
        self.assertEqual(canonical_sha256(actual), normalized["request_sha256"])

    def test_s0_whitespace_profile_is_deterministic_and_losslessly_mapped(self):
        actual = request("C1-SPACE", "粪便\t检卵  阳性\r\n如何判断？")
        first = normalize_request(actual)
        second = normalize_request(copy.deepcopy(actual))
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual("粪便 检卵 阳性\n如何判断？", first["normalized_query_text"])
        self.assertEqual(
            ["CRLF_TO_LF", "TAB_TO_SINGLE_SPACE", "COLLAPSE_ASCII_SPACE_RUN"],
            first["normalization_operations"],
        )
        self.assertEqual(len(actual["query_text"]), first["raw_to_normalized_spans"][-1]["raw_end"])
        self.assertEqual(len(first["normalized_query_text"]), first["raw_to_normalized_spans"][-1]["normalized_end"])

    def test_s0_invalid_request_fails_closed(self):
        invalid = request("C1-INVALID", "粪便检卵")
        invalid["locale"] = "en-US"
        with self.assertRaises(C1ValidationError):
            normalize_request(invalid)

    def test_s0_property_style_allowed_transformations_are_idempotent(self):
        cases = ["甲  乙", "甲\t乙", "甲\r\n乙", "甲 \t 乙", "甲乙"]
        for index, text in enumerate(cases):
            with self.subTest(text=text):
                first = normalize_request(request(f"C1-PROP-{index}", text))
                second_request = request(f"C1-PROP-N-{index}", first["normalized_query_text"])
                second = normalize_request(second_request)
                self.assertEqual(first["normalized_query_text"], second["normalized_query_text"])


class C1ClauseASTTests(unittest.TestCase):
    def compile(self, case: str, text: str):
        normalized = normalize_request(request(case, text))
        ast = compile_clause_ast(normalized)
        validate_schema(ast, CLAUSE_AST_SCHEMA_PATH)
        validate_c1_clause_ast(normalized, ast)
        return normalized, ast

    def test_alias_authority_and_exact_spans_are_preserved(self):
        normalized, ast = self.compile("C1-ALIAS", "华支睾吸虫病采用粪便检卵。")
        observed = {
            (item["normalized_surface"], tuple(item["candidate_entity_ids"]))
            for item in ast["surface_mentions"]
        }
        self.assertIn(("华支睾吸虫病", ("disease.clonorchiasis",)), observed)
        self.assertIn(("粪便检卵", ("diagnostic.stool_egg_microscopy",)), observed)
        for item in ast["surface_mentions"]:
            span = item["source_span"]
            self.assertEqual(
                span["text"],
                normalized["normalized_query_text"][span["start_char"] : span["end_char"]],
            )

    def test_clause_segmentation_builds_non_crossing_coordination(self):
        _, ast = self.compile("C1-SEG", "生食淡水鱼，粪便检卵阳性。")
        operator = next(item for item in ast["nodes"] if item["node_kind"] == "COORDINATION")
        self.assertEqual(2, len(operator["child_node_ids"]))
        self.assertEqual("，", operator["operator_span"]["text"])
        self.assertEqual(
            ["生食淡水鱼", "粪便检卵阳性"],
            [
                next(node for node in ast["nodes"] if node["node_id"] == child)["source_span"]["text"]
                for child in operator["child_node_ids"]
            ],
        )

    def test_frozen_structural_operators_preserve_branch_roles(self):
        cases = (
            ("如果生食淡水鱼，粪便检卵阳性。", "CONDITION", ["CONDITION_ANTECEDENT", "CONDITION_CONSEQUENT"]),
            ("生食淡水鱼，但是粪便检卵阴性。", "CONTRAST", ["CONTRAST_LEFT", "CONTRAST_RIGHT"]),
            ("粪便检卵阴性，后来粪便检卵阳性。", "OVERRIDE", ["OVERRIDE_EARLIER", "OVERRIDE_LATER"]),
            ("选择粪便检卵或者十二指肠液检卵。", "ALTERNATIVE_GROUP", ["ALTERNATIVE_BRANCH", "ALTERNATIVE_BRANCH"]),
        )
        for index, (text, kind, roles) in enumerate(cases):
            with self.subTest(kind=kind):
                _, ast = self.compile(f"C1-OP-{index}", text)
                operator = next(item for item in ast["nodes"] if item["node_kind"] == kind)
                children = {
                    item["node_id"]: item for item in ast["nodes"]
                    if item["node_id"] in operator["child_node_ids"]
                }
                self.assertEqual(roles, [children[item]["scope_role"] for item in operator["child_node_ids"]])

    def test_nested_condition_and_contrast_are_compositional(self):
        normalized, ast = self.compile(
            "C1-CORRECTION-NESTED",
            "如果生食淡水鱼，但是粪便检卵阴性。",
        )
        operators = [
            item for item in ast["nodes"]
            if item["node_kind"] in {"CONDITION", "CONTRAST"}
        ]
        self.assertEqual(["CONDITION", "CONTRAST"], [item["node_kind"] for item in operators])
        self.assertEqual(["如果", "但是"], [item["operator_span"]["text"] for item in operators])
        self.assertEqual(
            [(0, 2), (8, 10)],
            [
                (item["operator_span"]["start_char"], item["operator_span"]["end_char"])
                for item in operators
            ],
        )
        propositions = [item for item in ast["nodes"] if item["node_kind"] == "PROPOSITION"]
        self.assertTrue(all("但是" not in item["source_span"]["text"] for item in propositions))
        for item in propositions:
            span = item["source_span"]
            self.assertEqual(
                span["text"],
                normalized["normalized_query_text"][span["start_char"] : span["end_char"]],
            )

    def test_repeated_or_preserves_every_operator_and_three_branches(self):
        _, ast = self.compile(
            "C1-CORRECTION-OR3",
            "粪便检卵或者十二指肠液检卵或者影像检查。",
        )
        alternatives = [
            item for item in ast["nodes"]
            if item["node_kind"] == "ALTERNATIVE_GROUP"
        ]
        self.assertEqual(2, len(alternatives))
        self.assertEqual(["或者", "或者"], [item["operator_span"]["text"] for item in alternatives])
        self.assertEqual(
            [(4, 6), (13, 15)],
            [
                (item["operator_span"]["start_char"], item["operator_span"]["end_char"])
                for item in alternatives
            ],
        )
        leaves = [
            item["source_span"]["text"]
            for item in ast["nodes"]
            if item["node_kind"] == "PROPOSITION"
        ]
        self.assertEqual(["粪便检卵", "十二指肠液检卵", "影像检查"], leaves)
        self.assertTrue(all("或者" not in leaf for leaf in leaves))

    def test_multilevel_coordination_is_non_crossing_and_source_bound(self):
        normalized, ast = self.compile(
            "C1-CORRECTION-MULTILEVEL",
            "粪便检卵或者十二指肠液检卵，但是影像检查阳性。",
        )
        operators = [
            item for item in ast["nodes"]
            if item["node_kind"] in {"ALTERNATIVE_GROUP", "CONTRAST"}
        ]
        self.assertEqual({"ALTERNATIVE_GROUP", "CONTRAST"}, {item["node_kind"] for item in operators})
        for item in ast["nodes"]:
            span = item["source_span"]
            self.assertEqual(
                span["text"],
                normalized["normalized_query_text"][span["start_char"] : span["end_char"]],
            )
        spans = [item["source_span"] for item in ast["nodes"]]
        for left_index, left in enumerate(spans):
            for right in spans[left_index + 1 :]:
                crossing = (
                    left["start_char"] < right["start_char"] < left["end_char"] < right["end_char"]
                    or right["start_char"] < left["start_char"] < right["end_char"] < left["end_char"]
                )
                self.assertFalse(crossing)

    def test_property_recognized_operators_have_exactly_one_structure(self):
        cases = (
            ("如果生食淡水鱼，但是粪便检卵阴性。", ("如果", "但是")),
            ("粪便检卵或者十二指肠液检卵或者影像检查。", ("或者", "或者")),
            ("粪便检卵，十二指肠液检卵，影像检查。", ("，", "，")),
        )
        structural_kinds = {
            "COORDINATION", "CONDITION", "CONTRAST", "OVERRIDE", "ALTERNATIVE_GROUP"
        }
        for index, (text, expected_surfaces) in enumerate(cases):
            with self.subTest(text=text):
                _, ast = self.compile(f"C1-CORRECTION-PROP-{index}", text)
                operator_surfaces = [
                    item["operator_span"]["text"]
                    for item in ast["nodes"]
                    if item["node_kind"] in structural_kinds
                ]
                self.assertEqual(list(expected_surfaces), operator_surfaces)
                leaves = [
                    item["source_span"]["text"]
                    for item in ast["nodes"]
                    if item["node_kind"] == "PROPOSITION"
                ]
                for surface in set(expected_surfaces):
                    self.assertTrue(all(surface not in leaf for leaf in leaves))

    def test_metamorphic_third_or_adds_structure_not_leaf_text(self):
        _, two = self.compile(
            "C1-CORRECTION-META-OR2",
            "粪便检卵或者十二指肠液检卵。",
        )
        _, three = self.compile(
            "C1-CORRECTION-META-OR3",
            "粪便检卵或者十二指肠液检卵或者影像检查。",
        )
        operators = lambda ast: [
            item for item in ast["nodes"] if item["node_kind"] == "ALTERNATIVE_GROUP"
        ]
        leaves = lambda ast: [
            item["source_span"]["text"]
            for item in ast["nodes"] if item["node_kind"] == "PROPOSITION"
        ]
        self.assertEqual(len(operators(two)) + 1, len(operators(three)))
        self.assertEqual(leaves(two), leaves(three)[:2])
        self.assertEqual("影像检查", leaves(three)[2])

    def test_recursive_ast_is_byte_deterministic(self):
        actual = request(
            "C1-CORRECTION-RECURSIVE-DETERMINISM",
            "如果生食淡水鱼，但是粪便检卵或者影像检查。",
        )
        runs = [compile_clause_ast(normalize_request(copy.deepcopy(actual))) for _ in range(3)]
        self.assertEqual(1, len({canonical_bytes(item) for item in runs}))

    def test_single_participant_target_remains_unique_without_selection(self):
        _, ast = self.compile(
            "C1-CORRECTION-ONE-TARGET",
            "粪便检查未检出虫卵。",
        )
        marker = next(item for item in ast["assertion_markers"] if item["source_span"]["text"] == "未检出")
        attachment = next(item for item in ast["attachment_sets"] if item["dependent_id"] == marker["marker_id"])
        self.assertEqual("UNIQUE", marker["scope_status"])
        self.assertEqual(1, len(marker["scope_target_candidate_ids"]))
        self.assertEqual(marker["scope_target_candidate_ids"], attachment["candidate_governor_ids"])
        self.assertEqual("UNIQUE", attachment["status"])

    def test_multiple_participant_targets_are_complete_ordered_and_unresolved(self):
        _, ast = self.compile(
            "C1-CORRECTION-MULTI-TARGET",
            "粪便检查未检出虫卵和成虫。",
        )
        marker = next(item for item in ast["assertion_markers"] if item["source_span"]["text"] == "未检出")
        attachment = next(item for item in ast["attachment_sets"] if item["dependent_id"] == marker["marker_id"])
        mentions = {item["surface_mention_id"]: item for item in ast["surface_mentions"]}
        self.assertEqual(
            ["虫卵", "成虫"],
            [mentions[item]["source_span"]["text"] for item in marker["scope_target_candidate_ids"]],
        )
        self.assertEqual("UNRESOLVED", marker["scope_status"])
        self.assertEqual(marker["scope_target_candidate_ids"], attachment["candidate_governor_ids"])
        self.assertEqual("UNRESOLVED", attachment["status"])
        self.assertNotIn("selected_target_id", marker)
        self.assertNotIn("selected_governor_id", attachment)

    def test_multiple_target_order_is_deterministic(self):
        actual = request(
            "C1-CORRECTION-TARGET-ORDER",
            "粪便检查未检出虫卵和成虫。",
        )
        runs = [compile_clause_ast(normalize_request(copy.deepcopy(actual))) for _ in range(3)]
        domains = [
            next(item for item in ast["assertion_markers"] if item["source_span"]["text"] == "未检出")["scope_target_candidate_ids"]
            for ast in runs
        ]
        self.assertEqual(domains[0], domains[1])
        self.assertEqual(domains[1], domains[2])

    def test_participant_negator_without_candidate_fails_closed(self):
        normalized = normalize_request(
            request("C1-CORRECTION-ZERO-TARGET", "粪便检查未检出。")
        )
        with self.assertRaises(C1ValidationError):
            compile_clause_ast(normalized)

    def test_unresolved_target_invokes_no_typed_solver_or_later_stage(self):
        actual = request(
            "C1-CORRECTION-NO-SOLVER",
            "粪便检查未检出虫卵和成虫。",
        )
        forbidden = (
            "interpret_request",
            "validate_query_ir",
            "execute_query_ir",
            "run_scoped_query",
            "build_bound_execution",
        )
        with mock.patch.multiple(
            "scripts.p9b1q_scoped_query_ir",
            **{
                name: mock.DEFAULT for name in forbidden
            },
        ) as patched:
            for value in patched.values():
                value.side_effect = AssertionError("S2+ must not run in C1")
            result = compile_c1(actual)
        self.assertEqual("S1_CLAUSE_AST", result["terminal_stage"])
        marker = next(
            item for item in result["clause_ast"]["assertion_markers"]
            if item["source_span"]["text"] == "未检出"
        )
        self.assertEqual("UNRESOLVED", marker["scope_status"])
        self.assertNotIn("event_frame", result)
        self.assertNotIn("typed_constraint_result", result)

    def test_wh_focus_is_bound_through_question_ast(self):
        _, ast = self.compile("C1-WH", "生食淡水鱼可作为什么证据？")
        marker = next(item for item in ast["assertion_markers"] if item["marker_kind"] == "WH_FOCUS")
        containing = next(item for item in ast["nodes"] if item["node_id"] == marker["containing_node_id"])
        target = next(item for item in ast["nodes"] if item["node_id"] == marker["scope_target_candidate_ids"][0])
        self.assertEqual("QUESTION", containing["node_kind"])
        self.assertEqual("PROPOSITION", target["node_kind"])

    def test_event_and_object_negation_remain_distinct_ast_targets(self):
        _, event_ast = self.compile("C1-EVENT-NEG", "未生食淡水鱼。")
        event_marker = next(item for item in event_ast["assertion_markers"] if item["marker_kind"] == "NEGATOR")
        self.assertTrue(event_marker["scope_target_candidate_ids"][0].startswith("S"))

        _, object_ast = self.compile("C1-OBJECT-NEG", "粪便检查未检出虫卵。")
        object_marker = next(item for item in object_ast["assertion_markers"] if item["marker_kind"] == "NEGATOR")
        self.assertEqual("未检出", object_marker["source_span"]["text"])
        self.assertTrue(object_marker["scope_target_candidate_ids"][0].startswith("U"))

    def test_configured_assertion_marker_classes_are_recorded(self):
        _, ast = self.compile(
            "C1-MARKERS",
            "如果曾经生食淡水鱼，未来不采用减少动物粪便污染。",
        )
        kinds = {item["marker_kind"] for item in ast["assertion_markers"]}
        self.assertTrue(
            {"HYPOTHETICAL", "HISTORICAL", "FUTURE", "EXCLUSION", "CONNECTIVE"}
            <= kinds
        )
        exclusion = next(
            item for item in ast["assertion_markers"]
            if item["marker_kind"] == "EXCLUSION"
        )
        self.assertTrue(
            all(target.startswith("U") for target in exclusion["scope_target_candidate_ids"])
        )

    def test_double_negation_preserves_two_surface_markers(self):
        _, ast = self.compile("C1-DOUBLE-NEG", "并非未生食淡水鱼。")
        self.assertEqual(
            ["并非", "未"],
            [item["source_span"]["text"] for item in ast["assertion_markers"] if item["marker_kind"] == "NEGATOR"],
        )

    def test_invalid_marker_source_combination_fails_closed(self):
        normalized, ast = self.compile("C1-BAD-MARKER", "未生食淡水鱼。")
        changed = copy.deepcopy(ast)
        marker = next(item for item in changed["assertion_markers"] if item["marker_kind"] == "NEGATOR")
        marker["source_span"]["text"] = "不"
        with self.assertRaises(C1ValidationError):
            validate_c1_clause_ast(normalized, changed)

    def test_invalid_scope_path_fails_closed(self):
        normalized, ast = self.compile("C1-BAD-SCOPE", "未生食淡水鱼。")
        changed = copy.deepcopy(ast)
        marker = next(item for item in changed["assertion_markers"] if item["marker_kind"] == "NEGATOR")
        marker["scope_target_candidate_ids"] = ["S000"]
        with self.assertRaises(C1ValidationError):
            validate_c1_clause_ast(normalized, changed)

    def test_ast_canonical_bytes_and_hash_are_deterministic(self):
        actual = request("C1-DETERMINISM", "生食淡水鱼可作为什么证据？")
        runs = [compile_c1(copy.deepcopy(actual)) for _ in range(3)]
        self.assertEqual(1, len({canonical_bytes(item) for item in runs}))
        self.assertEqual(1, len({item["clause_ast_sha256"] for item in runs}))

    def test_metamorphic_terminal_punctuation_preserves_surface_domains(self):
        _, first = self.compile("C1-META-A", "粪便检卵阳性。")
        _, second = self.compile("C1-META-B", "粪便检卵阳性！")
        project = lambda ast: [
            (item["normalized_surface"], item["candidate_entity_ids"], item["candidate_entity_types"])
            for item in ast["surface_mentions"]
        ]
        self.assertEqual(project(first), project(second))

    def test_c1_stop_boundary_invokes_no_downstream_stage(self):
        actual = request("C1-STOP", "生食淡水鱼可作为什么证据？")
        forbidden = (
            "interpret_request",
            "validate_query_ir",
            "execute_query_ir",
            "run_scoped_query",
            "build_bound_execution",
        )
        patches = [
            mock.patch(
                f"scripts.p9b1q_scoped_query_ir.{name}",
                side_effect=AssertionError(f"{name} must not run in C1"),
            )
            for name in forbidden
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        result = compile_c1(actual)
        self.assertEqual("S1_CLAUSE_AST", result["terminal_stage"])
        self.assertNotIn("event_frame", result)
        self.assertNotIn("query_ir", result)
        self.assertNotIn("retrieval_result", result)

    def test_stop_boundary_rejects_downstream_objects(self):
        with self.assertRaises(C1ValidationError):
            validate_c1_stop_boundary({"event_frame": {}})


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
