from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.p9b1q_scoped_query_ir import (
    BindingValidationError,
    C1ValidationError,
    C2ValidationError,
    C3ValidationError,
    C3_PRE_CORRECTION_UNCOVERED_CONSTRAINT_IDS,
    CLAUSE_AST_SCHEMA_PATH,
    CONFIG_PATH,
    DIAGNOSTIC_ARGUMENT_BINDING_CONTRACT_PATH,
    EVENT_FRAME_SCHEMA_PATH,
    EVENT_RELATION_AUTHORITY_PATH,
    NORMALIZED_REQUEST_SCHEMA_PATH,
    QUERY_IR_SCHEMA_PATH,
    ROOT,
    build_bound_execution,
    c3_constraint_coverage,
    canonical_bytes,
    canonical_sha256,
    compile_c1,
    compile_c2,
    compile_c3,
    compile_clause_ast,
    compile_event_frame,
    execute_query_ir,
    file_sha256,
    interpret_request,
    normalize_request,
    normalized_event_identity,
    resolve_c3_proof_object,
    run_scoped_query,
    solve_typed_constraints,
    validate_bound_execution,
    validate_c1_clause_ast,
    validate_c1_normalized_request,
    validate_c1_stop_boundary,
    validate_c2_event_frame,
    validate_c2_stop_boundary,
    validate_c3_result,
    validate_c3_solution_core,
    validate_c3_stop_boundary,
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


def diagnostic_argument_binding(normalized, ast, occurrences):
    """Build public test input; this is not a production binding producer."""
    mentions = ast["surface_mentions"]

    def resolve(reference):
        surface, ordinal = (reference, 0) if isinstance(reference, str) else reference
        matches = [
            mention
            for mention in mentions
            if mention["normalized_surface"] == surface
            or mention["source_span"]["text"] == surface
        ]
        return matches[ordinal]

    method_binding_by_key = {}
    method_bindings = []
    predicate_occurrences = []
    method_side = {
        "diagnosed_by": "OBJECT",
        "diagnostic_stage_for": None,
        "has_diagnostic_clue": None,
    }
    for index, (predicate, subject_reference, object_reference) in enumerate(
        occurrences, start=1
    ):
        subject = resolve(subject_reference)
        object_ = resolve(object_reference)
        if subject["containing_node_id"] != object_["containing_node_id"]:
            raise AssertionError("test binding arguments must share one proposition")
        bindings = []
        for side, mention in (("SUBJECT", subject), ("OBJECT", object_)):
            method_binding_id = None
            if method_side[predicate] == side:
                key = (
                    tuple(mention["candidate_entity_ids"]),
                    mention["surface_mention_id"],
                )
                if key not in method_binding_by_key:
                    method_binding_id = f"DMB{len(method_bindings) + 1:03d}"
                    method_binding_by_key[key] = method_binding_id
                    method_bindings.append({
                        "method_entity_binding_id": method_binding_id,
                        "method_entity_id": mention["candidate_entity_ids"][0],
                        "binding_state": "BOUND",
                        "surface_mention_ids": [mention["surface_mention_id"]],
                    })
                else:
                    method_binding_id = method_binding_by_key[key]
            bindings.append({
                "argument_side": side,
                "binding_state": "BOUND",
                "surface_mention_ids": [mention["surface_mention_id"]],
                "method_entity_binding_id": method_binding_id,
            })
        predicate_occurrences.append({
            "predicate_occurrence_id": f"DPO{index:03d}",
            "canonical_predicate": predicate,
            "proposition_node_id": subject["containing_node_id"],
            "argument_bindings": bindings,
        })
    governing = sorted(
        {item["proposition_node_id"] for item in predicate_occurrences}
    )
    return {
        "binding_object_version": "0.1-candidate",
        "binding_scope": "DIAGNOSTIC_ONLY",
        "binding_contract_sha256": file_sha256(
            ROOT / DIAGNOSTIC_ARGUMENT_BINDING_CONTRACT_PATH
        ),
        "query_interpreter_config_sha256": file_sha256(ROOT / CONFIG_PATH),
        "event_relation_mapping_sha256": file_sha256(
            ROOT / EVENT_RELATION_AUTHORITY_PATH
        ),
        "request_bindings": [{
            "request_id": normalized["request_id"],
            "normalized_request_sha256": canonical_sha256(normalized),
            "clause_ast_sha256": canonical_sha256(ast),
            "diagnostic_contexts": [{
                "diagnostic_context_id": "DC001",
                "governing_ast_node_ids": governing,
                "method_entity_bindings": method_bindings,
                "predicate_occurrences": predicate_occurrences,
            }],
        }],
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
        condition, contrast = operators
        nodes = {item["node_id"]: item for item in ast["nodes"]}
        antecedent = nodes[condition["child_node_ids"][0]]
        consequent = nodes[condition["child_node_ids"][1]]
        right = nodes[contrast["child_node_ids"][0]]
        self.assertEqual("CONDITION_ANTECEDENT", antecedent["scope_role"])
        self.assertEqual(
            {"start_char": 2, "end_char": 7, "text": "生食淡水鱼"},
            antecedent["source_span"],
        )
        self.assertIs(consequent, contrast)
        self.assertEqual("CONDITION_CONSEQUENT", contrast["scope_role"])
        self.assertEqual(
            {"start_char": 8, "end_char": 16, "text": "但是粪便检卵阴性"},
            contrast["source_span"],
        )
        self.assertEqual(
            {"start_char": 8, "end_char": 10, "text": "但是"},
            contrast["operator_span"],
        )
        self.assertEqual(antecedent["node_id"], contrast["shared_left_argument_node_id"])
        self.assertNotIn(antecedent["node_id"], contrast["child_node_ids"])
        self.assertEqual([right["node_id"]], contrast["child_node_ids"])
        self.assertEqual("CONTRAST_RIGHT", right["scope_role"])
        self.assertLessEqual(
            antecedent["source_span"]["end_char"],
            contrast["source_span"]["start_char"],
        )
        self.assertEqual(
            1,
            sum(
                item["node_kind"] == "PROPOSITION"
                and item["source_span"] == antecedent["source_span"]
                for item in ast["nodes"]
            ),
        )
        propositions = [item for item in ast["nodes"] if item["node_kind"] == "PROPOSITION"]
        self.assertTrue(all("但是" not in item["source_span"]["text"] for item in propositions))
        for item in propositions:
            span = item["source_span"]
            self.assertEqual(
                span["text"],
                normalized["normalized_query_text"][span["start_char"] : span["end_char"]],
            )
        for mention in ast["surface_mentions"]:
            container = nodes[mention["containing_node_id"]]
            self.assertEqual("PROPOSITION", container["node_kind"])
            self.assertLessEqual(
                container["source_span"]["start_char"],
                mention["source_span"]["start_char"],
            )
            self.assertLessEqual(
                mention["source_span"]["end_char"],
                container["source_span"]["end_char"],
            )

    def test_shared_left_property_and_metamorphic_boundaries(self):
        cases = (
            ("若吃生鱼，不过十二指肠液检卵阳性。", "不过"),
            ("假如未充分加热淡水鱼，然而影像检查异常。", "然而"),
            ("如果生食淡水鱼，但是粪便检卵阴性。", "但是"),
        )
        for index, (text, contrast_surface) in enumerate(cases):
            with self.subTest(text=text):
                _, ast = self.compile(f"C1-SHARED-META-{index}", text)
                nodes = {item["node_id"]: item for item in ast["nodes"]}
                condition = next(
                    item for item in ast["nodes"] if item["node_kind"] == "CONDITION"
                )
                contrast = next(
                    item for item in ast["nodes"] if item["node_kind"] == "CONTRAST"
                )
                antecedent = nodes[condition["child_node_ids"][0]]
                delimiter = text.index("，")
                contrast_start = text.index(contrast_surface)
                self.assertEqual(delimiter, antecedent["source_span"]["end_char"])
                self.assertEqual(contrast_start, contrast["source_span"]["start_char"])
                self.assertEqual(
                    contrast_start,
                    contrast["operator_span"]["start_char"],
                )
                self.assertEqual(
                    antecedent["node_id"], contrast["shared_left_argument_node_id"]
                )
                self.assertLessEqual(
                    antecedent["source_span"]["end_char"],
                    contrast["source_span"]["start_char"],
                )

    def test_shared_left_contrast_can_own_repeated_coordination_right_subtree(self):
        _, ast = self.compile(
            "C1-SHARED-NESTED-OR",
            "如果生食淡水鱼，但是粪便检卵或者十二指肠液检卵或者影像检查。",
        )
        nodes = {item["node_id"]: item for item in ast["nodes"]}
        condition = next(item for item in ast["nodes"] if item["node_kind"] == "CONDITION")
        contrast = next(item for item in ast["nodes"] if item["node_kind"] == "CONTRAST")
        antecedent = nodes[condition["child_node_ids"][0]]
        right = nodes[contrast["child_node_ids"][0]]
        alternatives = [
            item for item in ast["nodes"] if item["node_kind"] == "ALTERNATIVE_GROUP"
        ]
        self.assertEqual(antecedent["node_id"], contrast["shared_left_argument_node_id"])
        self.assertEqual("CONTRAST_RIGHT", right["scope_role"])
        self.assertEqual("ALTERNATIVE_GROUP", right["node_kind"])
        self.assertEqual(2, len(alternatives))
        self.assertEqual(
            ["粪便检卵", "十二指肠液检卵", "影像检查"],
            [
                item["source_span"]["text"]
                for item in ast["nodes"]
                if item["node_kind"] == "PROPOSITION"
                and item["node_id"] != antecedent["node_id"]
            ],
        )

    def test_shared_left_integrity_mutations_fail_closed(self):
        normalized, valid = self.compile(
            "C1-SHARED-NEGATIVE",
            "如果生食淡水鱼，但是粪便检卵阴性。",
        )

        def node(ast, kind):
            return next(item for item in ast["nodes"] if item["node_kind"] == kind)

        mutations = {}

        non_unique = copy.deepcopy(valid)
        condition = node(non_unique, "CONDITION")
        antecedent = next(
            item for item in non_unique["nodes"]
            if item["scope_role"] == "CONDITION_ANTECEDENT"
        )
        duplicate = copy.deepcopy(antecedent)
        duplicate["node_id"] = "S998"
        condition["child_node_ids"].insert(1, duplicate["node_id"])
        non_unique["nodes"].append(duplicate)
        mutations["non-unique antecedent"] = non_unique

        illegal_target = copy.deepcopy(valid)
        node(illegal_target, "CONTRAST")["shared_left_argument_node_id"] = node(
            illegal_target, "CONDITION"
        )["node_id"]
        mutations["illegal target"] = illegal_target

        explicit_left = copy.deepcopy(valid)
        explicit_contrast = node(explicit_left, "CONTRAST")
        explicit_target = explicit_contrast["shared_left_argument_node_id"]
        explicit_contrast["child_node_ids"].insert(0, explicit_target)
        mutations["explicit left plus shared reference"] = explicit_left

        forward = copy.deepcopy(valid)
        forward_contrast = node(forward, "CONTRAST")
        forward_contrast["shared_left_argument_node_id"] = forward_contrast[
            "child_node_ids"
        ][0]
        mutations["forward target"] = forward

        duplicate_realization = copy.deepcopy(valid)
        duplicate_target = next(
            item for item in duplicate_realization["nodes"]
            if item["scope_role"] == "CONDITION_ANTECEDENT"
        )
        second_realization = copy.deepcopy(duplicate_target)
        second_realization["node_id"] = "S999"
        second_realization["parent_node_id"] = "S000"
        second_realization["scope_role"] = "MATERIAL_PROPOSITION"
        duplicate_realization["nodes"].append(second_realization)
        duplicate_realization["nodes"][0]["child_node_ids"].append("S999")
        mutations["duplicate target materialization"] = duplicate_realization

        for name, changed in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(C1ValidationError):
                    validate_c1_clause_ast(normalized, changed)

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


class C2EventFrameTests(unittest.TestCase):
    def compile(self, case: str, text: str):
        result = compile_c2(request(case, text))
        self.assertEqual("S2_EVENT_FRAME", result["terminal_stage"])
        validate_c2_event_frame(
            result["normalized_request"], result["clause_ast"], result["event_frame"]
        )
        return result

    def compile_bound(self, case: str, text: str, occurrences):
        normalized = normalize_request(request(case, text))
        ast = compile_clause_ast(normalized)
        authority = diagnostic_argument_binding(normalized, ast, occurrences)
        event_frame = compile_event_frame(
            normalized,
            ast,
            diagnostic_argument_binding=authority,
        )
        validate_c2_event_frame(
            normalized,
            ast,
            event_frame,
            diagnostic_argument_binding=authority,
        )
        return {
            "normalized_request": normalized,
            "clause_ast": ast,
            "event_frame": event_frame,
            "diagnostic_argument_binding": authority,
        }

    def assert_invalid_projection(self, result, mutate):
        changed = copy.deepcopy(result["event_frame"])
        mutate(changed)
        with self.assertRaises(C2ValidationError):
            validate_c2_event_frame(
                result["normalized_request"], result["clause_ast"], changed
            )

    def assert_invalid_semantics(self, result, mutate, authority=None):
        changed = copy.deepcopy(result["event_frame"])
        mutate(changed)
        with self.assertRaises(C2ValidationError):
            validate_c2_event_frame(
                result["normalized_request"],
                result["clause_ast"],
                changed,
                diagnostic_argument_binding=(
                    authority
                    if authority is not None
                    else result.get("diagnostic_argument_binding")
                ),
                require_compiler_projection=False,
            )

    def test_event_core_diagnostic_exposure_and_ordinary_frames(self):
        diagnostic = self.compile("C2-CORE-D", "粪便检卵阳性。")
        frame = diagnostic["event_frame"]["frames"][0]
        self.assertEqual(["DIAGNOSTIC_FINDING"], frame["event_type_domain"])
        self.assertEqual(["S001"], frame["source_ast_node_ids"])
        self.assertEqual("粪便检卵阳性", frame["source_spans"][0]["text"])
        self.assertIsNotNone(frame["diagnostic_binding"])

        exposure = self.compile(
            "C2-CORE-E",
            "来自流行地区并有生食淡水鱼史，可以作为华支睾吸虫病的什么证据？",
        )
        exposure_frame = exposure["event_frame"]["frames"][0]
        self.assertEqual(["EXPOSURE"], exposure_frame["event_type_domain"])
        self.assertIsNone(exposure_frame["diagnostic_binding"])

        ordinary = self.compile("C2-CORE-P", "成虫寄生于肝内胆管。")
        ordinary_frame = ordinary["event_frame"]["frames"][0]
        self.assertEqual(["PARASITISM"], ordinary_frame["event_type_domain"])
        roles = {slot["semantic_role"] for slot in ordinary_frame["participant_slots"]}
        self.assertEqual({"ACTOR", "LOCATION"}, roles)
        self.assertIsNone(ordinary_frame["diagnostic_binding"])

    def test_event_type_and_participant_ambiguity_are_preserved(self):
        behavior = self.compile("C2-DOMAIN", "生食淡水鱼。")
        frame = behavior["event_frame"]["frames"][0]
        self.assertEqual(["EXPOSURE", "INGESTION"], frame["event_type_domain"])
        self.assertEqual("COMPETING", frame["frame_status"])

        multiple = self.compile("C2-HIGH002", "粪便检查未检出虫卵和成虫。")
        frame = multiple["event_frame"]["frames"][0]
        target = next(
            slot for slot in frame["participant_slots"]
            if slot["semantic_role"] == "TARGET"
        )
        self.assertEqual("COMPETING", target["binding_status"])
        self.assertEqual(
            ["stage.clonorchis_adult", "stage.clonorchis_egg"],
            target["domain"]["entity_ids"],
        )
        marker = next(
            marker for marker in multiple["clause_ast"]["assertion_markers"]
            if marker["source_span"]["text"] == "未检出"
        )
        self.assertEqual("UNRESOLVED", marker["scope_status"])

    def test_diagnostic_components_are_same_frame_and_never_cross_bound(self):
        result = self.compile(
            "C2-DIAG-PAIR", "粪便检卵阳性，十二指肠液检卵阴性。"
        )
        event_frame = result["event_frame"]
        self.assertEqual(2, len(event_frame["frames"]))
        specimens = {
            slot["specimen_slot_id"]: slot
            for slot in event_frame["specimen_slots"]
        }
        self.assertEqual(
            [{"STOOL"}, {"DUODENAL_FLUID"}],
            [
                set(specimens[frame["diagnostic_binding"]["specimen_slot_id"]]["specimen_code_domain"])
                for frame in event_frame["frames"]
            ],
        )
        for frame in event_frame["frames"]:
            slots = {slot["slot_id"]: slot for slot in frame["participant_slots"]}
            binding = frame["diagnostic_binding"]
            self.assertEqual("METHOD", slots[binding["method_slot_id"]]["semantic_role"])
            self.assertTrue(
                all(slots[item]["semantic_role"] == "TARGET" for item in binding["target_slot_ids"])
            )

    def test_diagnostic_formal_catalog_materializes_method_and_target_only(self):
        for index, text in enumerate(("粪便检卵阳性。", "十二指肠液检卵阴性。")):
            with self.subTest(text=text):
                result = self.compile(f"C2-DIAG-ROLE-{index}", text)
                frame = result["event_frame"]["frames"][0]
                self.assertEqual(
                    ["METHOD", "TARGET"],
                    [slot["semantic_role"] for slot in frame["participant_slots"]],
                )
                self.assertEqual([], frame["normalized_identity"]["actor_slot_ids"])
                sources = [
                    source_id
                    for slot in frame["participant_slots"]
                    for source_id in slot["source_ids"]
                ]
                self.assertEqual(len(sources), len(set(sources)))

    def test_type_compatible_disease_without_predicate_is_not_materialized(self):
        result = self.compile(
            "C2-DIAG-DISEASE-ACTOR", "华支睾吸虫病粪便检查检出虫卵。"
        )
        frame = result["event_frame"]["frames"][0]
        self.assertEqual([], frame["normalized_identity"]["actor_slot_ids"])
        target = next(
            slot for slot in frame["participant_slots"]
            if slot["semantic_role"] == "TARGET"
        )
        self.assertEqual(["stage.clonorchis_egg"], target["domain"]["entity_ids"])

    def test_high003_all_option_b_predicate_sides_materialize_exact_roles(self):
        cases = (
            (
                "DIAGNOSED-BY",
                "华支睾吸虫病的确诊方法是粪便检查。",
                [("diagnosed_by", "华支睾吸虫病", "粪便检查")],
                {
                    ("ACTOR", "disease.clonorchiasis"),
                    ("METHOD", "diagnostic.stool_egg_microscopy"),
                },
            ),
            (
                "DIAGNOSTIC-STAGE",
                "华支睾吸虫病的确诊方法是粪便检查同时虫卵是人的诊断阶段。",
                [
                    ("diagnosed_by", "华支睾吸虫病", "粪便检查"),
                    ("diagnostic_stage_for", "虫卵", "人"),
                ],
                {
                    ("ACTOR", "disease.clonorchiasis"),
                    ("ACTOR", "host.human"),
                    ("METHOD", "diagnostic.stool_egg_microscopy"),
                    ("TARGET", "stage.clonorchis_egg"),
                },
            ),
            (
                "DIAGNOSTIC-CLUE",
                "华支睾吸虫病的诊断线索包括粪便检查。",
                [("has_diagnostic_clue", "华支睾吸虫病", "粪便检查")],
                {
                    ("ACTOR", "disease.clonorchiasis"),
                    ("METHOD", "diagnostic.stool_egg_microscopy"),
                },
            ),
        )
        for case, text, occurrences, expected in cases:
            with self.subTest(case=case):
                result = self.compile_bound(case, text, occurrences)
                frame = result["event_frame"]["frames"][0]
                observed = {
                    (slot["semantic_role"], entity_id)
                    for slot in frame["participant_slots"]
                    for entity_id in slot["domain"]["entity_ids"]
                }
                self.assertEqual(expected, observed)

    def test_high003_method_is_additive_and_multiple_predicates_are_complete(self):
        occurrences = [
            ("diagnosed_by", "华支睾吸虫病", "粪便检查"),
            ("has_diagnostic_clue", "华支睾吸虫病", "粪便检查"),
        ]
        result = self.compile_bound(
            "C2-HIGH003-MULTI",
            "华支睾吸虫病的确诊方法和诊断线索都是粪便检查。",
            occurrences,
        )
        frame = result["event_frame"]["frames"][0]
        self.assertEqual(
            ["ACTOR", "METHOD"],
            [slot["semantic_role"] for slot in frame["participant_slots"]],
        )
        authority = result["diagnostic_argument_binding"]
        self.assertEqual(
            {"diagnosed_by", "has_diagnostic_clue"},
            {
                item["canonical_predicate"]
                for item in authority["request_bindings"][0]["diagnostic_contexts"][0]["predicate_occurrences"]
            },
        )
        replay = compile_c2(
            request(
                "C2-HIGH003-MULTI",
                "华支睾吸虫病的确诊方法和诊断线索都是粪便检查。",
            ),
            diagnostic_argument_binding=result["diagnostic_argument_binding"],
        )
        self.assertEqual(
            canonical_bytes(result["event_frame"]),
            canonical_bytes(replay["event_frame"]),
        )
        missing = copy.deepcopy(authority)
        missing["request_bindings"][0]["diagnostic_contexts"][0]["predicate_occurrences"].pop()
        with self.assertRaises(C2ValidationError):
            validate_c2_event_frame(
                result["normalized_request"],
                result["clause_ast"],
                result["event_frame"],
                diagnostic_argument_binding=missing,
                require_compiler_projection=False,
            )

    def test_high011_unbound_same_entity_method_occurrence_is_excluded(self):
        result = self.compile_bound(
            "C2-HIGH011-BOUND-SECOND",
            "华支睾吸虫病的确诊方法是粪便检查粪便检查。",
            [("diagnosed_by", "华支睾吸虫病", ("粪便检查", 1))],
        )
        methods = [
            mention
            for mention in result["clause_ast"]["surface_mentions"]
            if mention["normalized_surface"] == "粪便检查"
        ]
        self.assertEqual(["U003", "U004"], [item["surface_mention_id"] for item in methods])
        slot = next(
            slot
            for slot in result["event_frame"]["frames"][0]["participant_slots"]
            if slot["semantic_role"] == "METHOD"
        )
        self.assertEqual(["U004"], slot["source_ids"])

        def add_unbound_same_entity_occurrence(value):
            method = next(
                item
                for item in value["frames"][0]["participant_slots"]
                if item["semantic_role"] == "METHOD"
            )
            method["source_ids"] = ["U003", "U004"]

        self.assert_invalid_semantics(result, add_unbound_same_entity_occurrence)

    def test_high011_mirror_bound_occurrence_defeats_position_heuristics(self):
        result = self.compile_bound(
            "C2-HIGH011-BOUND-FIRST",
            "华支睾吸虫病的确诊方法是粪便检查粪便检查。",
            [("diagnosed_by", "华支睾吸虫病", ("粪便检查", 0))],
        )
        method = next(
            slot
            for slot in result["event_frame"]["frames"][0]["participant_slots"]
            if slot["semantic_role"] == "METHOD"
        )
        self.assertEqual(["U003"], method["source_ids"])
        self.assertNotIn("U004", method["source_ids"])

    def test_high011_multiple_licensed_method_occurrences_are_exactly_additive(self):
        result = self.compile_bound(
            "C2-HIGH011-MULTI-BOUND",
            "华支睾吸虫病的确诊方法是粪便检查粪便检查。",
            [
                ("diagnosed_by", "华支睾吸虫病", ("粪便检查", 0)),
                ("diagnosed_by", "华支睾吸虫病", ("粪便检查", 1)),
            ],
        )
        method = next(
            slot
            for slot in result["event_frame"]["frames"][0]["participant_slots"]
            if slot["semantic_role"] == "METHOD"
        )
        self.assertEqual(["U003", "U004"], method["source_ids"])
        self.assertEqual(
            2,
            len(
                result["diagnostic_argument_binding"]["request_bindings"][0]
                ["diagnostic_contexts"][0]["method_entity_bindings"]
            ),
        )

    def test_high011_formal_stage_predicate_does_not_license_typed_method(self):
        normalized = normalize_request(request(
            "C2-HIGH011-STAGE-NO-METHOD-LICENSE",
            "粪便检查显示虫卵是人的诊断阶段。",
        ))
        ast = compile_clause_ast(normalized)
        binding = diagnostic_argument_binding(
            normalized,
            ast,
            [("diagnostic_stage_for", "虫卵", "人")],
        )
        with self.assertRaisesRegex(C2ValidationError, "lacks one method domain"):
            compile_event_frame(
                normalized,
                ast,
                diagnostic_argument_binding=binding,
            )

    def test_high003_validator_rejects_missing_reversed_and_unlicensed_roles(self):
        result = self.compile_bound(
            "C2-HIGH003-NEG-ROLE",
            "华支睾吸虫病的确诊方法是粪便检查同时虫卵是人的诊断阶段。",
            [
                ("diagnosed_by", "华支睾吸虫病", "粪便检查"),
                ("diagnostic_stage_for", "虫卵", "人"),
            ],
        )

        def omit_target(value):
            frame = value["frames"][0]
            target_id = frame["normalized_identity"]["target_slot_ids"][0]
            frame["participant_slots"] = [
                slot for slot in frame["participant_slots"] if slot["slot_id"] != target_id
            ]
            frame["normalized_identity"]["target_slot_ids"] = []
            frame["diagnostic_binding"]["target_slot_ids"] = []

        self.assert_invalid_semantics(result, omit_target)

        def reverse_actor_target(value):
            frame = value["frames"][0]
            actor = next(slot for slot in frame["participant_slots"] if slot["semantic_role"] == "ACTOR")
            target = next(slot for slot in frame["participant_slots"] if slot["semantic_role"] == "TARGET")
            actor["semantic_role"], target["semantic_role"] = "TARGET", "ACTOR"
            frame["normalized_identity"]["actor_slot_ids"] = [target["slot_id"]]
            frame["normalized_identity"]["target_slot_ids"] = [actor["slot_id"]]
            frame["diagnostic_binding"]["target_slot_ids"] = [actor["slot_id"]]

        self.assert_invalid_semantics(result, reverse_actor_target)

        def add_type_only_actor(value):
            frame = value["frames"][0]
            target = next(slot for slot in frame["participant_slots"] if slot["semantic_role"] == "TARGET")
            extra = copy.deepcopy(target)
            extra["slot_id"] = "V999"
            extra["semantic_role"] = "ACTOR"
            frame["participant_slots"].append(extra)
            frame["normalized_identity"]["actor_slot_ids"].append("V999")

        self.assert_invalid_semantics(result, add_type_only_actor)

    def test_high003_exact_occurrence_and_candidate_self_authorization_fail_closed(self):
        result = self.compile_bound(
            "C2-HIGH003-OCCURRENCE",
            "华支睾吸虫病的确诊方法是粪便检查同时虫卵和虫卵是人的诊断阶段。",
            [
                ("diagnosed_by", "华支睾吸虫病", "粪便检查"),
                ("diagnostic_stage_for", ("虫卵", 0), "人"),
            ],
        )
        egg_mentions = [
            mention
            for mention in result["clause_ast"]["surface_mentions"]
            if mention["normalized_surface"] == "虫卵"
        ]
        self.assertEqual(2, len(egg_mentions))

        def forge_same_entity_occurrence(value):
            target = next(
                slot
                for slot in value["frames"][0]["participant_slots"]
                if slot["semantic_role"] == "TARGET"
            )
            target["source_ids"] = [egg_mentions[1]["surface_mention_id"]]

        self.assert_invalid_semantics(result, forge_same_entity_occurrence)
        with self.assertRaises(C2ValidationError):
            validate_c2_event_frame(
                result["normalized_request"],
                result["clause_ast"],
                result["event_frame"],
                diagnostic_argument_binding=None,
                require_compiler_projection=False,
            )

    def test_high003_binding_ambiguity_and_forged_provenance_fail_closed(self):
        result = self.compile_bound(
            "C2-HIGH003-BINDING-NEG",
            "华支睾吸虫病的确诊方法是粪便检查同时虫卵是人的诊断阶段。",
            [
                ("diagnosed_by", "华支睾吸虫病", "粪便检查"),
                ("diagnostic_stage_for", "虫卵", "人"),
            ],
        )
        authority = copy.deepcopy(result["diagnostic_argument_binding"])
        subject = authority["request_bindings"][0]["diagnostic_contexts"][0]["predicate_occurrences"][1]["argument_bindings"][0]
        subject["binding_state"] = "AMBIGUOUS"
        subject["surface_mention_ids"].append("U999")
        with self.assertRaises(C2ValidationError):
            validate_c2_event_frame(
                result["normalized_request"],
                result["clause_ast"],
                result["event_frame"],
                diagnostic_argument_binding=authority,
                require_compiler_projection=False,
            )

        def forged_provenance(value):
            actor = next(
                slot
                for slot in value["frames"][0]["participant_slots"]
                if slot["semantic_role"] == "ACTOR"
            )
            actor["source_ids"] = ["U001"]

        self.assert_invalid_semantics(result, forged_provenance)

    def test_high003_metamorphic_method_surface_preserves_predicate_roles(self):
        cases = (
            (
                "华支睾吸虫病的确诊方法是粪便检查同时虫卵是人的诊断阶段。",
                "粪便检查",
            ),
            (
                "华支睾吸虫病的确诊方法是十二指肠液检查同时成虫是人的诊断期。",
                "十二指肠液检查",
            ),
        )
        for index, (text, method_surface) in enumerate(cases):
            with self.subTest(text=text):
                stage_surface = "虫卵" if index == 0 else "成虫"
                result = self.compile_bound(
                    f"C2-HIGH003-META-{index}",
                    text,
                    [
                        ("diagnosed_by", "华支睾吸虫病", method_surface),
                        ("diagnostic_stage_for", stage_surface, "人"),
                    ],
                )
                roles = {
                    (slot["semantic_role"], entity_type)
                    for slot in result["event_frame"]["frames"][0]["participant_slots"]
                    for entity_type in slot["domain"]["entity_types"]
                }
                self.assertIn(("ACTOR", "host"), roles)
                self.assertIn(("METHOD", "diagnostic_method"), roles)
                self.assertIn(("TARGET", "life_cycle_stage"), roles)
                self.assertIn(
                    method_surface,
                    [
                        mention["normalized_surface"]
                        for mention in result["clause_ast"]["surface_mentions"]
                    ],
                )

    def test_diagnostic_role_validator_rejects_duplicate_actor_target_mention(self):
        result = self.compile("C2-DIAG-ROLE-ADV", "粪便检卵阳性。")

        def duplicate_target_as_actor(value):
            frame = value["frames"][0]
            target = next(
                slot for slot in frame["participant_slots"]
                if slot["semantic_role"] == "TARGET"
            )
            actor = copy.deepcopy(target)
            actor["slot_id"] = "V999"
            actor["semantic_role"] = "ACTOR"
            frame["participant_slots"].append(actor)
            frame["normalized_identity"]["actor_slot_ids"] = ["V999"]

        self.assert_invalid_semantics(result, duplicate_target_as_actor)

    def test_negative_finding_is_not_infection_exclusion(self):
        result = self.compile("C2-DIAG-NEG", "粪便检查未检出虫卵。")
        assertion = result["event_frame"]["frames"][0]["assertion"]
        self.assertEqual("AFFIRMED", assertion["assertion_status"])
        self.assertEqual("NEGATIVE", assertion["finding_polarity"])

    def test_imaging_uses_formal_not_applicable_specimen_without_inference(self):
        result = self.compile("C2-DIAG-IMAGING", "影像检查异常。")
        event_frame = result["event_frame"]
        frame = event_frame["frames"][0]
        specimen = event_frame["specimen_slots"][0]
        self.assertEqual(["NOT_APPLICABLE"], specimen["specimen_code_domain"])
        self.assertEqual("影像检查", specimen["source_spans"][0]["text"])
        self.assertEqual([], frame["diagnostic_binding"]["target_slot_ids"])
        self.assertEqual("INCOMPLETE", frame["frame_status"])

    def test_assertion_and_temporal_scopes_come_from_ast_markers(self):
        cases = (
            ("未生食淡水鱼。", "NEGATED", "GENERAL"),
            ("不涉及生食淡水鱼。", "EXCLUDED", "GENERAL"),
            ("如果生食淡水鱼，粪便检卵阳性。", "HYPOTHETICAL", "GENERAL"),
        )
        for number, (text, status, temporal) in enumerate(cases):
            with self.subTest(text=text):
                result = self.compile(f"C2-ASSERT-{number}", text)
                frame = result["event_frame"]["frames"][0]
                self.assertEqual(status, frame["assertion"]["assertion_status"])
                self.assertEqual(temporal, frame["assertion"]["temporal_scope"])
                self.assertTrue(frame["assertion"]["marker_ids"])

        temporal = self.compile(
            "C2-TEMPORAL", "曾经生食淡水鱼，目前生食淡水鱼。"
        )
        self.assertEqual(
            ["HISTORICAL", "CURRENT"],
            [frame["assertion"]["temporal_scope"] for frame in temporal["event_frame"]["frames"]],
        )

    def test_event_negation_parity_zero_through_three(self):
        cases = (
            ("生食淡水鱼。", "AFFIRMED", 0),
            ("未生食淡水鱼。", "NEGATED", 1),
            ("并非未生食淡水鱼。", "AFFIRMED", 2),
            ("并非并非未生食淡水鱼。", "NEGATED", 3),
        )
        for index, (text, expected, count) in enumerate(cases):
            with self.subTest(text=text):
                result = self.compile(f"C2-PARITY-{index}", text)
                markers = [
                    marker
                    for marker in result["clause_ast"]["assertion_markers"]
                    if marker["marker_kind"] == "NEGATOR"
                ]
                self.assertEqual(count, len(markers))
                self.assertEqual(
                    expected,
                    result["event_frame"]["frames"][0]["assertion"]["assertion_status"],
                )

    def test_event_negation_parity_metamorphic_toggle_and_participant_isolation(self):
        surfaces = ("生食淡水鱼。", "未生食淡水鱼。", "未未生食淡水鱼。", "未未未生食淡水鱼。")
        statuses = [
            self.compile(f"C2-PARITY-META-{index}", text)["event_frame"]["frames"][0]["assertion"]["assertion_status"]
            for index, text in enumerate(surfaces)
        ]
        self.assertEqual(["AFFIRMED", "NEGATED", "AFFIRMED", "NEGATED"], statuses)
        participant = self.compile(
            "C2-PARITY-PARTICIPANT", "粪便检查未检出虫卵。"
        )["event_frame"]["frames"][0]
        self.assertEqual("AFFIRMED", participant["assertion"]["assertion_status"])
        self.assertEqual("NEGATIVE", participant["assertion"]["finding_polarity"])

    def test_assertion_validator_rederives_odd_and_even_parity(self):
        even = self.compile("C2-PARITY-ADV-EVEN", "并非未生食淡水鱼。")
        self.assert_invalid_semantics(
            even,
            lambda value: value["frames"][0]["assertion"].__setitem__(
                "assertion_status", "NEGATED"
            ),
        )
        odd = self.compile("C2-PARITY-ADV-ODD", "未生食淡水鱼。")
        self.assert_invalid_semantics(
            odd,
            lambda value: value["frames"][0]["assertion"].__setitem__(
                "assertion_status", "AFFIRMED"
            ),
        )

    def test_normalized_identity_excludes_assertion_and_frame_id(self):
        result = self.compile(
            "C2-ID-SAME", "粪便检卵阳性，粪便检卵阴性。"
        )
        first, second = result["event_frame"]["frames"]
        self.assertNotEqual(
            first["assertion"]["finding_polarity"],
            second["assertion"]["finding_polarity"],
        )
        self.assertEqual(
            normalized_event_identity(first, result["event_frame"]),
            normalized_event_identity(second, result["event_frame"]),
        )
        renamed = copy.deepcopy(first)
        renamed["frame_id"] = "EF999"
        self.assertEqual(
            normalized_event_identity(first, result["event_frame"]),
            normalized_event_identity(renamed, result["event_frame"]),
        )

    def test_identity_changes_for_method_specimen_target_and_anatomy(self):
        method = self.compile(
            "C2-ID-METHOD", "粪便检卵阳性，十二指肠液检卵阳性。"
        )
        left, right = method["event_frame"]["frames"]
        self.assertNotEqual(
            normalized_event_identity(left, method["event_frame"]),
            normalized_event_identity(right, method["event_frame"]),
        )

        target = self.compile(
            "C2-ID-TARGET", "粪便检查检出虫卵，粪便检查检出成虫。"
        )
        left, right = target["event_frame"]["frames"]
        self.assertNotEqual(
            normalized_event_identity(left, target["event_frame"]),
            normalized_event_identity(right, target["event_frame"]),
        )

        anatomy = self.compile(
            "C2-ID-SITE", "成虫寄生于肝内胆管，成虫寄生于胆道。"
        )
        left, right = anatomy["event_frame"]["frames"]
        self.assertNotEqual(
            normalized_event_identity(left, anatomy["event_frame"]),
            normalized_event_identity(right, anatomy["event_frame"]),
        )

    def test_reference_unique_and_unresolved_candidate_completeness(self):
        unique = self.compile(
            "C2-REF-UNIQUE",
            "粪便检卵阳性，粪便检卵阴性，两次检查是同一诊断事件。",
        )["event_frame"]["reference_hypotheses"][0]
        self.assertEqual("UNIQUE", unique["status"])
        self.assertEqual(["EF001"], unique["candidate_referent_ids"])
        self.assertEqual(["SAME_EVENT"], unique["identity_relation_domain"])

        unresolved = self.compile(
            "C2-REF-UNRESOLVED",
            "粪便检卵阳性，粪便检卵阴性，粪便检卵阳性，这些检查是同一诊断事件。",
        )["event_frame"]["reference_hypotheses"][0]
        self.assertEqual("UNRESOLVED", unresolved["status"])
        self.assertEqual(["EF001", "EF002"], unresolved["candidate_referent_ids"])

    def test_reference_preserves_all_prior_legal_candidates_without_nearest_selection(self):
        result = self.compile(
            "C2-REF-COMPLETE",
            "粪便检卵阳性，十二指肠液检卵阴性，生食淡水鱼是另一暴露事件。",
        )
        reference = result["event_frame"]["reference_hypotheses"][0]
        self.assertEqual(["EF001", "EF002"], reference["candidate_referent_ids"])
        self.assertEqual(["DISTINCT_EVENT"], reference["identity_relation_domain"])
        self.assertEqual("UNRESOLVED", reference["status"])
        self.assert_invalid_semantics(
            result,
            lambda value: value["reference_hypotheses"][0].update(
                {"candidate_referent_ids": ["EF002"], "status": "UNIQUE"}
            ),
        )

    def test_reference_relation_domain_enumerates_overlapping_typed_assignments(self):
        result = self.compile(
            "C2-REF-OVERLAP",
            "生食淡水鱼，来自流行地区并有生食淡水鱼史，两次暴露是同一事件。",
        )
        reference = result["event_frame"]["reference_hypotheses"][0]
        self.assertEqual(["EF001"], reference["candidate_referent_ids"])
        self.assertEqual(
            ["SAME_EVENT", "DISTINCT_EVENT"],
            reference["identity_relation_domain"],
        )
        self.assertEqual("UNRESOLVED", reference["status"])
        for incomplete in (["SAME_EVENT"], ["DISTINCT_EVENT"]):
            with self.subTest(incomplete=incomplete):
                self.assert_invalid_semantics(
                    result,
                    lambda value, domain=incomplete: value["reference_hypotheses"][0].__setitem__(
                        "identity_relation_domain", domain
                    ),
                )

    def test_reference_relation_domain_same_only_and_distinct_only(self):
        same = self.compile(
            "C2-REF-SAME-ONLY",
            "粪便检卵阳性，粪便检卵阴性，两次检查是同一诊断事件。",
        )["event_frame"]["reference_hypotheses"][0]
        self.assertEqual(["SAME_EVENT"], same["identity_relation_domain"])
        self.assertEqual("UNIQUE", same["status"])

        distinct = self.compile(
            "C2-REF-DISTINCT-ONLY",
            "粪便检卵阳性，生食淡水鱼是另一暴露事件。",
        )["event_frame"]["reference_hypotheses"][0]
        self.assertEqual(["DISTINCT_EVENT"], distinct["identity_relation_domain"])
        self.assertEqual("UNIQUE", distinct["status"])

    def test_public_r3a_reference_override_evidence_projection(self):
        result = self.compile(
            "C2-R3A-EVIDENCE",
            "华支睾吸虫病粪便检查检出虫卵，华支睾吸虫病粪便检查未检出虫卵；"
            "两次检查是同一诊断事件，生食淡水鱼是另一暴露事件，后次结果覆盖前次结果。",
        )["event_frame"]
        self.assertEqual(
            [
                ("EF002", ["EF001"], ["SAME_EVENT"], "UNIQUE"),
                (
                    "EF003",
                    ["EF001", "EF002"],
                    ["DISTINCT_EVENT"],
                    "UNRESOLVED",
                ),
            ],
            [
                (
                    item["anaphor_frame_id"],
                    item["candidate_referent_ids"],
                    item["identity_relation_domain"],
                    item["status"],
                )
                for item in result["reference_hypotheses"]
            ],
        )
        override = result["override_hypotheses"][0]
        self.assertEqual(["EF001"], override["earlier_frame_ids"])
        self.assertEqual(["EF002"], override["later_frame_ids"])
        self.assertEqual(["FINDING_POLARITY"], override["overridden_dimension_domain"])
        self.assertEqual("UNIQUE", override["status"])

    def test_override_unique_unresolved_and_no_match(self):
        unique = self.compile(
            "C2-OVERRIDE-UNIQUE", "粪便检卵阳性，后来粪便检卵阴性。"
        )["event_frame"]["override_hypotheses"][0]
        self.assertEqual("UNIQUE", unique["status"])
        self.assertEqual(["FINDING_POLARITY"], unique["overridden_dimension_domain"])

        unresolved = self.compile(
            "C2-OVERRIDE-UNRESOLVED",
            "粪便检卵阳性，粪便检卵阴性，后来粪便检卵阴性，粪便检卵阳性。",
        )["event_frame"]["override_hypotheses"][0]
        self.assertEqual("UNRESOLVED", unresolved["status"])
        self.assertEqual(["EF001", "EF002"], unresolved["earlier_frame_ids"])
        self.assertEqual(["EF003", "EF004"], unresolved["later_frame_ids"])

        no_match = self.compile(
            "C2-OVERRIDE-NO-MATCH", "粪便检卵阳性，后来十二指肠液检卵阴性。"
        )["event_frame"]["override_hypotheses"][0]
        self.assertEqual("NO_MATCH", no_match["status"])

    def test_shared_left_is_s1_only_and_c1_object_is_unchanged(self):
        actual = request("C2-SHARED", "如果生食淡水鱼，但是粪便检卵阴性。")
        before = compile_c1(copy.deepcopy(actual))
        after = compile_c2(copy.deepcopy(actual))
        self.assertEqual(canonical_bytes(before["clause_ast"]), canonical_bytes(after["clause_ast"]))
        contrast = next(
            node for node in after["clause_ast"]["nodes"] if node["node_kind"] == "CONTRAST"
        )
        self.assertIsNotNone(contrast["shared_left_argument_node_id"])
        self.assertEqual([], after["event_frame"]["reference_hypotheses"])

    def test_condition_contrast_or_and_coordination_frame_completeness(self):
        condition = self.compile("C2-CONDITION", "如果生食淡水鱼，粪便检卵阳性。")
        self.assertEqual(2, len(condition["event_frame"]["frames"]))
        contrast = self.compile("C2-CONTRAST", "生食淡水鱼，但是粪便检卵阴性。")
        self.assertEqual(2, len(contrast["event_frame"]["frames"]))
        repeated = self.compile(
            "C2-OR",
            "粪便检卵或者十二指肠液检卵或者成虫寄生于肝内胆管。",
        )
        self.assertEqual(3, len(repeated["event_frame"]["frames"]))
        coordinated = self.compile(
            "C2-COORD", "粪便检卵阳性，十二指肠液检卵阴性。"
        )
        self.assertEqual(2, len(coordinated["event_frame"]["frames"]))

    def test_public_s2_fixtures_remain_schema_valid_evidence(self):
        fixture_root = ROOT / "phase9/clonorchis-sinensis/p9b1q-architecture-review/fixtures"
        for name in (
            "event-frame-exposure-positive.json",
            "event-frame-diagnostic-positive.json",
        ):
            with self.subTest(name=name):
                fixture = json.loads((fixture_root / name).read_text(encoding="utf-8"))
                validate_schema(fixture, EVENT_FRAME_SCHEMA_PATH)

    def test_invalid_s1_fails_closed_without_event_frame(self):
        actual = request("C2-BAD-S1", "未生食淡水鱼。")
        normalized = normalize_request(actual)
        ast = compile_clause_ast(normalized)
        ast["nodes"][0]["source_span"]["text"] = "corrupt"
        with self.assertRaises(C2ValidationError):
            compile_event_frame(normalized, ast)

    def test_adversarial_participant_domain_and_cardinality_fail(self):
        result = self.compile("C2-ADV-DOMAIN", "粪便检卵阳性。")

        def unlicensed(value):
            value["frames"][0]["participant_slots"][0]["domain"]["entity_ids"] = [
                "stage.unlicensed"
            ]
        self.assert_invalid_projection(result, unlicensed)

        multiple = self.compile("C2-ADV-FIXED", "粪便检查未检出虫卵和成虫。")
        self.assert_invalid_projection(
            multiple,
            lambda value: value["frames"][0]["participant_slots"][-1].__setitem__(
                "binding_status", "FIXED"
            ),
        )
        self.assert_invalid_projection(
            result,
            lambda value: value["frames"][0]["participant_slots"][0].__setitem__(
                "binding_status", "COMPETING"
            ),
        )

    def test_adversarial_diagnostic_specimen_and_identity_mutations_fail(self):
        pair = self.compile(
            "C2-ADV-DIAG", "粪便检卵阳性，十二指肠液检卵阴性。"
        )

        def cross_bind(value):
            first = value["frames"][0]["diagnostic_binding"]["specimen_slot_id"]
            value["frames"][1]["diagnostic_binding"]["specimen_slot_id"] = first
            value["frames"][1]["normalized_identity"]["specimen_slot_ids"] = [first]
        self.assert_invalid_projection(pair, cross_bind)

        self.assert_invalid_projection(
            pair,
            lambda value: value["specimen_slots"][0]["source_spans"][0].__setitem__(
                "text", "胆汁"
            ),
        )

        def wrong_role(value):
            frame = value["frames"][0]
            target = next(
                slot["slot_id"] for slot in frame["participant_slots"]
                if slot["semantic_role"] == "TARGET"
            )
            frame["normalized_identity"]["actor_slot_ids"] = [target]
        self.assert_invalid_projection(pair, wrong_role)

        def reuse_slot(value):
            frame = value["frames"][0]
            frame["normalized_identity"]["target_slot_ids"] = [
                frame["normalized_identity"]["method_slot_id"]
            ]
        self.assert_invalid_projection(pair, reuse_slot)

    def test_adversarial_reference_override_and_shared_left_mutations_fail(self):
        reference = self.compile(
            "C2-ADV-REF",
            "粪便检卵阳性，粪便检卵阴性，粪便检卵阳性，这些检查是同一诊断事件。",
        )
        self.assert_invalid_projection(
            reference,
            lambda value: value["reference_hypotheses"][0].__setitem__(
                "candidate_referent_ids", ["EF002"]
            ),
        )
        self.assert_invalid_projection(
            reference,
            lambda value: value["reference_hypotheses"][0].__setitem__(
                "status", "UNIQUE"
            ),
        )

        override = self.compile(
            "C2-ADV-OVERRIDE", "粪便检卵阳性，后来粪便检卵阴性。"
        )
        self.assert_invalid_projection(
            override,
            lambda value: value["override_hypotheses"][0].__setitem__(
                "overridden_dimension_domain", ["EVENT_TYPE"]
            ),
        )

        shared = self.compile("C2-ADV-SHARED", "如果生食淡水鱼，但是粪便检卵阴性。")
        def invent_reference(value):
            value["reference_hypotheses"].append({
                "reference_hypothesis_id": "RH001",
                "anaphor_source_id": "S004",
                "anaphor_frame_id": "EF002",
                "candidate_referent_ids": ["EF001"],
                "identity_relation_domain": ["DISTINCT_EVENT"],
                "status": "UNIQUE",
            })
        self.assert_invalid_projection(shared, invent_reference)

    def test_hash_bindings_determinism_and_stop_boundary(self):
        actual = request("C2-DETERMINISM", "粪便检卵阳性，粪便检卵阴性。")
        runs = [compile_c2(copy.deepcopy(actual)) for _ in range(3)]
        self.assertEqual(1, len({canonical_bytes(item["event_frame"]) for item in runs}))
        self.assertEqual(1, len({item["event_frame_sha256"] for item in runs}))
        self.assertEqual(
            canonical_sha256(runs[0]["event_frame"]), runs[0]["event_frame_sha256"]
        )
        self.assert_invalid_projection(
            runs[0],
            lambda value: value.__setitem__("clause_ast_sha256", "0" * 64),
        )
        with self.assertRaises(C2ValidationError):
            validate_c2_stop_boundary({"query_ir": {}})

    def test_c2_invokes_no_solver_queryir_retrieval_or_model(self):
        forbidden = (
            "interpret_request",
            "validate_query_ir",
            "execute_query_ir",
            "run_scoped_query",
            "build_bound_execution",
        )
        with mock.patch.multiple(
            "scripts.p9b1q_scoped_query_ir",
            **{name: mock.DEFAULT for name in forbidden},
        ) as patched:
            for value in patched.values():
                value.side_effect = AssertionError("S3+ must not run in C2")
            result = compile_c2(request("C2-STOP", "粪便检卵阳性。"))
        self.assertEqual("S2_EVENT_FRAME", result["terminal_stage"])
        self.assertNotIn("typed_constraint_result", result)
        self.assertNotIn("query_ir", result)
        self.assertNotIn("retrieval_result", result)


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


class C3TypedConstraintSolverTests(unittest.TestCase):
    UNIQUE_TEXT = (
        "来自流行地区并有生食淡水鱼史，可以作为华支睾吸虫病的什么证据？"
    )

    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory(prefix="p9b1q-c3-tests-")
        cls.proof_root = Path(cls._temporary.name)
        cls.compiled = compile_c3(
            request("C3-UNIQUE", cls.UNIQUE_TEXT),
            proof_root=cls.proof_root,
        )
        cls.typed = cls.compiled["typed_constraint_result"]

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    @staticmethod
    def refresh_core(core):
        material = {
            key: core[key]
            for key in (
                "resolved_mentions",
                "resolved_events",
                "resolved_relations",
                "semantic_roles",
                "narrative_intents",
                "forbidden_relations",
                "resolved_references",
                "resolved_overrides",
            )
        }
        core["semantic_object_set_sha256"] = canonical_sha256(material)
        core["solution_id"] = f"SOL-{core['semantic_object_set_sha256'][:24]}"

    def core(self):
        value = copy.deepcopy(self.typed["selected_solution"])
        value.pop("queryir_emission_record")
        return value

    def persist_proof(self, directory, value):
        digest = canonical_sha256(value)
        relative = f"proof-objects/{directory}/{digest}.json"
        destination = self.proof_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(canonical_bytes(value))
        return relative, digest

    @staticmethod
    def refresh_minimality(result):
        minimality = result["selected_solution"]["queryir_emission_record"][
            "minimality_witness"
        ]
        body = copy.deepcopy(minimality)
        body.pop("witness_sha256")
        minimality["witness_sha256"] = canonical_sha256(body)

    def test_unique_solution_has_complete_content_addressed_proofs(self):
        self.assertEqual("S3_TYPED_CONSTRAINT_SOLVER", self.compiled["terminal_stage"])
        self.assertEqual("UNIQUE", self.typed["status"])
        self.assertEqual("ONE", self.typed["solution_cardinality"])
        validate_c3_result(
            self.typed,
            self.compiled["normalized_request"],
            self.compiled["clause_ast"],
            self.compiled["event_frame"],
            proof_root=self.proof_root,
        )
        selected = self.typed["selected_solution"]
        emission = selected["queryir_emission_record"]
        self.assertEqual("VALID", emission["query_ir"]["interpretation_status"])
        material_count = sum(
            len(selected[key])
            for key in (
                "resolved_mentions",
                "resolved_events",
                "resolved_relations",
                "semantic_roles",
                "narrative_intents",
                "forbidden_relations",
                "resolved_references",
                "resolved_overrides",
            )
        )
        self.assertEqual(
            material_count,
            len(emission["minimality_witness"]["retained_object_witnesses"]),
        )
        self.assertEqual(
            material_count,
            len(emission["license_dag"]["nodes"]),
        )
        self.assertNotIn("query_ir", self.compiled)
        self.assertNotIn("retrieval_result", self.compiled)

    def test_zero_valid_profile_is_unsupported_not_invalid(self):
        with tempfile.TemporaryDirectory(prefix="p9b1q-c3-unsupported-") as directory:
            result = compile_c3(
                request("C3-UNSUPPORTED", "粪便检卵阳性。"),
                proof_root=Path(directory),
            )["typed_constraint_result"]
        self.assertEqual(("UNSUPPORTED", "ZERO"), (result["status"], result["solution_cardinality"]))
        self.assertIsNone(result["selected_solution"])
        self.assertTrue(result["unsatisfied_constraints"])

    def test_hash_binding_mismatch_is_invalid_zero(self):
        c2 = compile_c2(request("C3-INVALID", self.UNIQUE_TEXT))
        result = solve_typed_constraints(
            c2["normalized_request"],
            c2["clause_ast"],
            c2["event_frame"],
            bound_hashes={"CLAUSE_AST": "0" * 64},
        )
        self.assertEqual(("INVALID", "ZERO"), (result["status"], result["solution_cardinality"]))
        self.assertIsNone(result["selected_solution"])
        self.assertEqual(["CNS-SOLVER-HASH_BINDING"], result["unsatisfied_constraints"])

    def test_duplicate_same_entity_occurrences_remain_ambiguous(self):
        text = (
            "来自流行地区并有生食淡水鱼史，可以作为华支睾吸虫病"
            "华支睾吸虫病的什么证据？"
        )
        result = compile_c3(request("C3-AMB", text))["typed_constraint_result"]
        self.assertEqual(("AMBIGUOUS", "MULTIPLE"), (result["status"], result["solution_cardinality"]))
        self.assertIsNone(result["selected_solution"])
        certificate = result["ambiguity_certificate"]
        self.assertGreaterEqual(len(certificate["solution_fingerprint_sha256s"]), 2)
        self.assertTrue(all(value.startswith("U") for value in certificate["differing_variable_ids"]))

    def test_reverse_relation_direction_and_unlicensed_role_fail_closed(self):
        reversed_core = self.core()
        relation = reversed_core["resolved_relations"][0]
        relation["subject_selector"], relation["object_selector"] = (
            relation["object_selector"],
            relation["subject_selector"],
        )
        self.refresh_core(reversed_core)
        with self.assertRaises(C3ValidationError):
            validate_c3_solution_core(
                reversed_core,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
            )

        extra_role = self.core()
        extra_role["semantic_roles"].append({
            "role_key": "RQ999",
            "role_namespace": "TOPIC_SCOPE",
            "role_value": "exposure",
            "activation_policy": "REQUIRED",
            "root_keys": ["RR001"],
        })
        self.refresh_core(extra_role)
        with self.assertRaises(C3ValidationError):
            validate_c3_solution_core(
                extra_role,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
            )

    def test_formal_prohibition_assertion_and_event_identity_are_enforced(self):
        prohibited = self.core()
        relation = prohibited["resolved_relations"][0]
        prohibited["forbidden_relations"] = [{
            "forbidden_key": "RF001",
            "predicate": relation["predicate"],
            "subject_selector": copy.deepcopy(relation["subject_selector"]),
            "object_selector": copy.deepcopy(relation["object_selector"]),
            "reason": "EXPLICIT_EXCLUSION",
            "root_keys": ["RM001"],
        }]
        self.refresh_core(prohibited)
        with self.assertRaises(C3ValidationError):
            validate_c3_solution_core(
                prohibited,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
            )

        assertion = self.core()
        assertion["resolved_mentions"][0]["assertion_status"] = "NEGATED"
        self.refresh_core(assertion)
        with self.assertRaises(C3ValidationError):
            validate_c3_solution_core(
                assertion,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
            )

        identity = self.core()
        identity["resolved_events"][0]["frame_id"] = "EF999"
        self.refresh_core(identity)
        with self.assertRaises(C3ValidationError):
            validate_c3_solution_core(
                identity,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
            )

    def test_high011_bound_method_occurrence_is_preserved_into_s3_input(self):
        actual = request(
            "C3-HIGH011",
            "华支睾吸虫病的确诊方法是粪便检查粪便检查。",
        )
        normalized = normalize_request(actual)
        ast = compile_clause_ast(normalized)
        binding = diagnostic_argument_binding(
            normalized,
            ast,
            [("diagnosed_by", "华支睾吸虫病", ("粪便检查", 1))],
        )
        result = compile_c3(actual, diagnostic_argument_binding=binding)
        method = next(
            slot
            for slot in result["event_frame"]["frames"][0]["participant_slots"]
            if slot["semantic_role"] == "METHOD"
        )
        self.assertEqual(["U004"], method["source_ids"])
        self.assertNotIn("U003", method["source_ids"])
        self.assertEqual("UNSUPPORTED", result["typed_constraint_result"]["status"])

    def test_candidate_output_cannot_self_authorize_core_changes(self):
        changed = self.core()
        changed["resolved_relations"][0]["root_keys"] = ["RM002", "RM005"]
        self.refresh_core(changed)
        with self.assertRaises(C3ValidationError):
            validate_c3_solution_core(
                changed,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
            )

    def test_candidate_status_cannot_self_authorize_cardinality(self):
        forged = copy.deepcopy(self.typed)
        forged["status"] = "UNSUPPORTED"
        forged["solution_cardinality"] = "ZERO"
        forged["selected_solution"] = None
        forged["ambiguity_certificate"] = None
        forged["unsatisfied_constraints"] = [
            "CNS-SOLVER-EVENT_RELATION_DERIVATION"
        ]
        with self.assertRaises(C3ValidationError):
            validate_c3_result(
                forged,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
                proof_root=self.proof_root,
            )

    def test_reference_candidates_remain_ambiguous_and_override_is_not_a_winner(self):
        text = (
            "华支睾吸虫病粪便检查检出虫卵，华支睾吸虫病粪便检查未检出虫卵；"
            "两次检查是同一诊断事件，生食淡水鱼是另一暴露事件，"
            "后次结果覆盖前次结果。"
        )
        compiled = compile_c3(request("C3-REFERENCE-OVERRIDE", text))
        event_frame = compiled["event_frame"]
        result = compiled["typed_constraint_result"]
        self.assertEqual("UNIQUE", event_frame["override_hypotheses"][0]["status"])
        self.assertEqual(("AMBIGUOUS", "MULTIPLE"), (
            result["status"], result["solution_cardinality"]
        ))
        self.assertIn(
            "RH002", result["ambiguity_certificate"]["differing_variable_ids"]
        )
        validate_c3_result(
            result,
            compiled["normalized_request"],
            compiled["clause_ast"],
            event_frame,
        )

    def test_schema_valid_but_non_authoritative_override_input_is_invalid(self):
        text = (
            "华支睾吸虫病粪便检查检出虫卵，华支睾吸虫病粪便检查未检出虫卵；"
            "两次检查是同一诊断事件，后次结果覆盖前次结果。"
        )
        c2 = compile_c2(request("C3-OVERRIDE-INVALID", text))
        changed = copy.deepcopy(c2["event_frame"])
        changed["override_hypotheses"][0]["overridden_dimension_domain"] = [
            "ASSERTION_STATUS"
        ]
        result = solve_typed_constraints(
            c2["normalized_request"], c2["clause_ast"], changed
        )
        self.assertEqual(("INVALID", "ZERO"), (
            result["status"], result["solution_cardinality"]
        ))

    def test_proof_path_and_binding_mutations_fail_closed(self):
        emission = self.typed["selected_solution"]["queryir_emission_record"]
        witness = emission["minimality_witness"]
        bad_paths = (
            "../proof-objects/semantic-universe/" + "0" * 64 + ".json",
            "..\\proof-objects\\semantic-universe\\" + "0" * 64 + ".json",
            "/tmp/" + "0" * 64 + ".json",
            "C:/tmp/" + "0" * 64 + ".json",
            "\\\\server\\share\\proof.json",
            "file:///tmp/proof.json",
            "http://example.invalid/proof.json",
            "https://example.invalid/proof.json",
            "fixtures/semantic-universe-exposure-positive.json",
        )
        for path in bad_paths:
            with self.subTest(path=path):
                changed = copy.deepcopy(self.typed)
                changed["selected_solution"]["queryir_emission_record"][
                    "minimality_witness"
                ]["semantic_universe_path"] = path
                with self.assertRaises(C3ValidationError):
                    validate_c3_result(
                        changed,
                        self.compiled["normalized_request"],
                        self.compiled["clause_ast"],
                        self.compiled["event_frame"],
                        proof_root=self.proof_root,
                    )

        for mutation in ("DETACH", "CYCLE"):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.typed)
                dag = changed["selected_solution"]["queryir_emission_record"]["license_dag"]
                if mutation == "DETACH":
                    dag["edges"].pop()
                else:
                    dag["edges"].append({
                        "edge_id": f"LE{len(dag['edges']) + 1:04d}",
                        "from_node_id": dag["topological_order"][-1],
                        "to_node_id": dag["topological_order"][0],
                        "edge_kind": "ROOTS_EVENT_OR_RELATION",
                        "constraint_ids": ["CNS-SOLVER-LICENSE_DAG"],
                    })
                body = copy.deepcopy(dag)
                body.pop("dag_sha256")
                dag["dag_sha256"] = canonical_sha256(body)
                with self.assertRaises(C3ValidationError):
                    validate_c3_result(
                        changed,
                        self.compiled["normalized_request"],
                        self.compiled["clause_ast"],
                        self.compiled["event_frame"],
                        proof_root=self.proof_root,
                    )

        wrong_kind = copy.deepcopy(self.typed)
        first_probe = witness["retained_object_witnesses"][0]["removal_probe_path"]
        wrong_kind["selected_solution"]["queryir_emission_record"][
            "minimality_witness"
        ]["semantic_universe_path"] = first_probe
        with self.assertRaises(C3ValidationError):
            validate_c3_result(
                wrong_kind,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
                proof_root=self.proof_root,
            )

        wrong_hash = copy.deepcopy(self.typed)
        wrong_hash["selected_solution"]["queryir_emission_record"][
            "minimality_witness"
        ]["semantic_universe_sha256"] = "0" * 64
        with self.assertRaises(C3ValidationError):
            validate_c3_result(
                wrong_hash,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
                proof_root=self.proof_root,
            )

    def test_missing_solution_semantic_universe_and_probe_fail_closed(self):
        mutations = []
        missing_universe = copy.deepcopy(self.typed)
        missing_universe["selected_solution"]["queryir_emission_record"][
            "minimality_witness"
        ]["semantic_universe_path"] = (
            "proof-objects/semantic-universe/" + "1" * 64 + ".json"
        )
        mutations.append(missing_universe)

        solution_mismatch = copy.deepcopy(self.typed)
        solution_mismatch["selected_solution"]["queryir_emission_record"][
            "semantic_solution_core_sha256"
        ] = "2" * 64
        mutations.append(solution_mismatch)

        universe_mismatch = copy.deepcopy(self.typed)
        universe_mismatch["selected_solution"]["queryir_emission_record"][
            "query_ir_sha256"
        ] = "3" * 64
        mutations.append(universe_mismatch)

        missing_probe = copy.deepcopy(self.typed)
        missing_probe["selected_solution"]["queryir_emission_record"][
            "minimality_witness"
        ]["retained_object_witnesses"][0]["removal_probe_path"] = (
            "proof-objects/removal-probe/" + "4" * 64 + ".json"
        )
        mutations.append(missing_probe)
        for value in mutations:
            with self.assertRaises(C3ValidationError):
                validate_c3_result(
                    value,
                    self.compiled["normalized_request"],
                    self.compiled["clause_ast"],
                    self.compiled["event_frame"],
                    proof_root=self.proof_root,
                )

    def test_persisted_request_universe_and_solution_mismatches_fail_closed(self):
        emission = self.typed["selected_solution"]["queryir_emission_record"]
        universe_path = emission["minimality_witness"]["semantic_universe_path"]
        universe = json.loads((self.proof_root / universe_path).read_text())

        for field, value in (
            ("request_id", "P9B1Q-OTHER-REQUEST"),
            ("query_ir_sha256", "5" * 64),
        ):
            with self.subTest(field=field):
                changed_universe = copy.deepcopy(universe)
                changed_universe[field] = value
                path, digest = self.persist_proof(
                    "semantic-universe", changed_universe
                )
                changed = copy.deepcopy(self.typed)
                minimality = changed["selected_solution"][
                    "queryir_emission_record"
                ]["minimality_witness"]
                minimality["semantic_universe_path"] = path
                minimality["semantic_universe_sha256"] = digest
                self.refresh_minimality(changed)
                with self.assertRaises(C3ValidationError):
                    validate_c3_result(
                        changed,
                        self.compiled["normalized_request"],
                        self.compiled["clause_ast"],
                        self.compiled["event_frame"],
                        proof_root=self.proof_root,
                    )

        changed_core = self.core()
        changed_core["resolved_mentions"].pop()
        self.refresh_core(changed_core)
        core_path, core_hash = self.persist_proof(
            "typed-solution-core", changed_core
        )
        changed = copy.deepcopy(self.typed)
        first_witness = changed["selected_solution"]["queryir_emission_record"][
            "minimality_witness"
        ]["retained_object_witnesses"][0]
        original_probe = json.loads(
            (self.proof_root / first_witness["removal_probe_path"]).read_text()
        )
        original_probe["base_typed_solution_path"] = core_path
        original_probe["base_typed_solution_sha256"] = core_hash
        probe_path, probe_hash = self.persist_proof(
            "removal-probe", original_probe
        )
        first_witness["removal_probe_path"] = probe_path
        first_witness["removal_probe_sha256"] = probe_hash
        self.refresh_minimality(changed)
        with self.assertRaises(C3ValidationError):
            validate_c3_result(
                changed,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
                proof_root=self.proof_root,
            )

    def test_symlink_escape_is_rejected_after_resolution(self):
        universe_path = self.typed["selected_solution"]["queryir_emission_record"][
            "minimality_witness"
        ]["semantic_universe_path"]
        universe = json.loads((self.proof_root / universe_path).read_text())
        with tempfile.TemporaryDirectory(prefix="p9b1q-c3-external-") as directory:
            external = Path(directory) / "object.json"
            external.write_bytes(canonical_bytes(universe))
            digest = canonical_sha256(universe)
            relative = f"proof-objects/semantic-universe/{digest}.json"
            internal = self.proof_root / relative
            internal.unlink()
            internal.symlink_to(external)
            try:
                self.assertIsNone(
                    resolve_c3_proof_object(
                        self.proof_root,
                        relative,
                        "SEMANTIC_UNIVERSE",
                        self.typed["request_id"],
                    )
                )
            finally:
                internal.unlink()
                internal.write_bytes(canonical_bytes(universe))

    def test_three_fresh_runs_are_byte_identical(self):
        hashes = []
        for index in range(3):
            with tempfile.TemporaryDirectory(prefix=f"p9b1q-c3-det-{index}-") as directory:
                value = compile_c3(
                    request("C3-DETERMINISM", self.UNIQUE_TEXT),
                    proof_root=Path(directory),
                )
                proof_bytes = [
                    path.read_bytes()
                    for path in sorted(Path(directory).rglob("*.json"))
                ]
                hashes.append(canonical_sha256({
                    "result": value,
                    "proof_sha256s": [
                        __import__("hashlib").sha256(item).hexdigest()
                        for item in proof_bytes
                    ],
                }))
        self.assertEqual([hashes[0]] * 3, hashes)

    def test_production_cli_reaches_c3_and_stops_before_downstream_stages(self):
        with tempfile.TemporaryDirectory(prefix="p9b1q-c3-cli-") as directory:
            work = Path(directory)
            request_path = work / "request.json"
            request_path.write_text(
                json.dumps(request("C3-CLI", self.UNIQUE_TEXT), ensure_ascii=False),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/p9b1q_scoped_query_ir.py"),
                    "--request", str(request_path),
                    "--proof-root", str(work),
                ],
                cwd=work,
                check=True,
                capture_output=True,
                text=True,
            )
            output = json.loads(completed.stdout)
            self.assertEqual("S3_TYPED_CONSTRAINT_SOLVER", output["terminal_stage"])
            self.assertEqual("UNIQUE", output["typed_constraint_result"]["status"])
            self.assertNotIn("query_ir", output)
            self.assertNotIn("retrieval_result", output)
            self.assertNotIn("runtime_binding", output)
            self.assertGreater(len(list((work / "proof-objects").rglob("*.json"))), 2)

    def test_exposure_solution_is_the_strict_inclusion_minimum(self):
        core = self.core()
        self.assertEqual(8, sum(len(core[key]) for key in (
            "resolved_mentions", "resolved_events", "resolved_relations",
            "semantic_roles", "narrative_intents", "forbidden_relations",
            "resolved_references", "resolved_overrides",
        )))
        self.assertEqual(
            {"U001", "U005"},
            {item["surface_mention_id"] for item in core["resolved_mentions"]},
        )
        ast_mention = next(
            item for item in self.compiled["clause_ast"]["surface_mentions"]
            if item["surface_mention_id"] == "U002"
        )
        strict_superset = copy.deepcopy(core)
        strict_superset["resolved_mentions"].append({
            "mention_key": "RM002",
            "surface_mention_id": "U002",
            "entity_id": ast_mention["candidate_entity_ids"][0],
            "entity_type": ast_mention["candidate_entity_types"][0],
            "assertion_status": "AFFIRMED",
            "temporal_scope": "GENERAL",
        })
        self.refresh_core(strict_superset)
        with self.assertRaises(C3ValidationError):
            validate_c3_solution_core(
                strict_superset,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
            )

    def test_strict_supersets_drop_but_incomparable_minima_and_order_survive(self):
        from scripts.p9b1q_scoped_query_ir import _c3_remove_strict_supersets

        first = self.core()
        superset = copy.deepcopy(first)
        extra = next(
            item for item in self.compiled["clause_ast"]["surface_mentions"]
            if item["surface_mention_id"] == "U002"
        )
        superset["resolved_mentions"].append({
            "mention_key": "RM002",
            "surface_mention_id": "U002",
            "entity_id": extra["candidate_entity_ids"][0],
            "entity_type": extra["candidate_entity_types"][0],
            "assertion_status": "AFFIRMED",
            "temporal_scope": "GENERAL",
        })
        self.refresh_core(superset)
        incomparable = copy.deepcopy(first)
        incomparable["resolved_relations"][0]["predicate"] = "risk_increased_by"
        self.refresh_core(incomparable)
        values = {
            canonical_sha256(value): value
            for value in (superset, incomparable, first)
        }
        forward = _c3_remove_strict_supersets(values)
        reverse = _c3_remove_strict_supersets(dict(reversed(list(values.items()))))
        self.assertEqual(set(forward), set(reverse))
        self.assertEqual(2, len(forward))
        self.assertNotIn(canonical_sha256(superset), forward)

    def test_removal_probes_replay_and_external_binding_tamper_fails(self):
        core = self.core()
        witnesses = self.typed["selected_solution"]["queryir_emission_record"][
            "minimality_witness"
        ]["retained_object_witnesses"]
        self.assertEqual(8, len(witnesses))
        for witness in witnesses:
            probe = json.loads(
                (self.proof_root / witness["removal_probe_path"]).read_text()
            )
            changed = copy.deepcopy(core)
            collection, index = probe["mutation"][0]["path"].strip("/").split("/")
            changed[collection].pop(int(index))
            self.refresh_core(changed)
            self.assertEqual(canonical_sha256(changed), probe["candidate_typed_solution_sha256"])
            self.assertEqual(0, probe["enumerated_solution_count_after_removal"])
            with self.assertRaises(C3ValidationError):
                validate_c3_solution_core(
                    changed,
                    self.compiled["normalized_request"],
                    self.compiled["clause_ast"],
                    self.compiled["event_frame"],
                )

        changed = copy.deepcopy(self.typed)
        witness = changed["selected_solution"]["queryir_emission_record"][
            "minimality_witness"
        ]["retained_object_witnesses"][0]
        probe = json.loads((self.proof_root / witness["removal_probe_path"]).read_text())
        for field in (
            "validator_contract_sha256", "validator_executable_sha256",
            "validator_configuration_sha256", "constraint_set_sha256",
        ):
            probe[field] = "0" * 64
        witness["removal_probe_path"], witness["removal_probe_sha256"] = self.persist_proof(
            "removal-probe", probe
        )
        self.refresh_minimality(changed)
        with self.assertRaises(C3ValidationError):
            validate_c3_result(
                changed,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
                proof_root=self.proof_root,
            )

    def test_trace_and_license_candidate_self_authorization_fail_closed(self):
        trace_tamper = copy.deepcopy(self.typed)
        trace_tamper["selected_solution"]["queryir_emission_record"]["field_traces"][0][
            "source_bindings"
        ][0]["object_sha256"] = "0" * 64
        with self.assertRaises(C3ValidationError):
            validate_c3_result(
                trace_tamper,
                self.compiled["normalized_request"],
                self.compiled["clause_ast"],
                self.compiled["event_frame"],
                proof_root=self.proof_root,
            )

        for semantic_kind in ("SEMANTIC_ROLE", "NARRATIVE"):
            with self.subTest(semantic_kind=semantic_kind):
                changed = copy.deepcopy(self.typed)
                emission = changed["selected_solution"]["queryir_emission_record"]
                dag = emission["license_dag"]
                node = next(item for item in dag["nodes"] if item["node_kind"] == semantic_kind)
                dag["edges"] = [item for item in dag["edges"] if item["to_node_id"] != node["node_id"]]
                node["node_kind"] = "EXPLICIT_QUESTION_SLOT_ROOT"
                body = copy.deepcopy(dag)
                body.pop("dag_sha256")
                dag["dag_sha256"] = canonical_sha256(body)
                witness = next(
                    item for item in emission["minimality_witness"]["retained_object_witnesses"]
                    if item["semantic_object_id"] == node["semantic_object_id"]
                )
                witness["license_path_node_ids"] = [node["node_id"]]
                self.refresh_minimality(changed)
                with self.assertRaises(C3ValidationError):
                    validate_c3_result(
                        changed,
                        self.compiled["normalized_request"],
                        self.compiled["clause_ast"],
                        self.compiled["event_frame"],
                        proof_root=self.proof_root,
                    )

    def test_authority_domains_cover_non_exposure_event_classes(self):
        cases = (
            ("PARASITISM", "成虫寄生于肝内胆管。"),
            ("TREATMENT", "吡喹酮治疗华支睾吸虫病。"),
            (
                "DEVELOPMENT",
                "华支睾吸虫虫卵如何经过毛蚴、胞蚴、雷蚴和尾蚴发育为囊蚴，再成为成虫？",
            ),
        )
        for name, text in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                typed = compile_c3(
                    request(f"C3-DOMAIN-{name}", text),
                    proof_root=Path(directory),
                )["typed_constraint_result"]
                self.assertNotEqual("UNSUPPORTED", typed["status"])
                self.assertNotEqual("INVALID", typed["status"])

    def test_formal_control_prohibition_is_materialized_and_eliminates_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            typed = compile_c3(
                request(
                    "C3-CONTROL-PROHIBITION",
                    "综合防控华支睾吸虫病，但不采用减少动物粪便污染。",
                ),
                proof_root=Path(directory),
            )["typed_constraint_result"]
        self.assertEqual("UNIQUE", typed["status"])
        query_ir = typed["selected_solution"]["queryir_emission_record"]["query_ir"]
        forbidden = query_ir["forbidden_relation_intents"]
        self.assertEqual(["EXPLICIT_EXCLUSION"], [item["reason"] for item in forbidden])
        excluded = forbidden[0]["object_selector"]["entity_ids"][0]
        self.assertNotIn(
            excluded,
            {
                entity_id
                for relation in query_ir["relation_intents"]
                for entity_id in relation["object_selector"]["entity_ids"]
            },
        )

    def test_temporal_scope_is_part_of_normalized_event_identity(self):
        from scripts.p9b1q_scoped_query_ir import _c3_event_identity

        current = copy.deepcopy(self.core()["resolved_events"][0])
        historical = copy.deepcopy(current)
        current["temporal_scope"] = "CURRENT"
        historical["temporal_scope"] = "HISTORICAL"
        self.assertNotEqual(_c3_event_identity(current), _c3_event_identity(historical))
        self.assertEqual(_c3_event_identity(current), _c3_event_identity(copy.deepcopy(current)))

    def test_all_48_constraints_have_executable_or_bound_discharge_sites(self):
        receipt = c3_constraint_coverage()
        self.assertEqual(48, len(receipt))
        self.assertEqual(48, len({item["constraint_id"] for item in receipt}))
        self.assertEqual(
            {
                "CNS-SOLVER-EVENT_IDENTITY",
                "CNS-SOLVER-LICENSE_DAG",
                "CNS-SOLVER-MINIMALITY",
                "CNS-EMIT-QUERYIR_SCHEMA",
            },
            set(C3_PRE_CORRECTION_UNCOVERED_CONSTRAINT_IDS),
        )
        self.assertTrue(all(item["enforcement_or_discharge_site"] for item in receipt))

    def test_s3_stop_boundary_rejects_later_stage_objects(self):
        validate_c3_stop_boundary(self.compiled)
        with self.assertRaises(C3ValidationError):
            validate_c3_stop_boundary({
                "implemented_stages": [
                    "S0_REQUEST_NORMALIZATION",
                    "S1_CLAUSE_AST",
                    "S2_EVENT_FRAME",
                    "S3_TYPED_CONSTRAINT_SOLVER",
                ],
                "terminal_stage": "S3_TYPED_CONSTRAINT_SOLVER",
                "retrieval_result": {},
            })


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
