from __future__ import annotations

import copy
import hashlib
import json
import os
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
    C4ValidationError,
    C4_IMPLEMENTED_STAGES,
    C4_TERMINAL_STAGE,
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
    compile_c4,
    compile_clause_ast,
    compile_event_frame,
    execute_query_ir,
    extract_queryir_c4,
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
    validate_c4_stop_boundary,
    validate_query_ir,
    validate_schema,
)
from scripts.p9b1q_scoped_query_ir import (
    _c3_authority_inputs,
    _c3_event_relation_derivation_matches,
    _c3_pointer_get,
    _c3_recomputed_solution_space,
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
        self.assertEqual("UNIQUE", result["typed_constraint_result"]["status"])
        core = result["typed_constraint_result"]["selected_solution"]
        relation = core["resolved_relations"][0]
        self.assertEqual("diagnosed_by", relation["predicate"])
        rooted_mentions = {
            item["surface_mention_id"]
            for item in core["resolved_mentions"]
            if item["mention_key"] in relation["root_keys"]
        }
        self.assertIn("U004", rooted_mentions)
        self.assertNotIn("U003", rooted_mentions)

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

    def test_production_cli_reaches_c3_then_c4_and_stops_before_downstream_stages(self):
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
            self.assertEqual("S4_QUERYIR_EMISSION_IMPLEMENTATION", output["terminal_stage"])
            self.assertEqual("UNIQUE", output["typed_constraint_result"]["status"])
            self.assertEqual(
                canonical_bytes(output["query_ir"]),
                canonical_bytes(
                    output["typed_constraint_result"]["selected_solution"]
                    ["queryir_emission_record"]["query_ir"]
                ),
            )
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
            {"CNS-SOLVER-EVENT_RELATION_DERIVATION"},
            set(C3_PRE_CORRECTION_UNCOVERED_CONSTRAINT_IDS),
        )
        self.assertTrue(all(item["enforcement_or_discharge_site"] for item in receipt))

    def test_trace_sources_resolve_to_exact_occurrences_and_spans(self):
        emission = self.typed["selected_solution"]["queryir_emission_record"]
        traces = emission["field_traces"]
        query_ir = emission["query_ir"]
        pointers = [item["query_ir_json_pointer"] for item in traces]
        self.assertEqual(len(pointers), len(set(pointers)))
        text = self.compiled["normalized_request"]["normalized_query_text"]
        material_heads = {
            "mentions", "events", "relation_intents", "narrative_intents",
            "required_roles", "forbidden_relation_intents",
            "resolved_references", "resolved_overrides",
        }
        broad_material_bindings = 0
        for trace in traces:
            self.assertEqual(
                canonical_sha256(_c3_pointer_get(
                    query_ir, trace["query_ir_json_pointer"]
                )),
                trace["emitted_value_sha256"],
            )
            for binding in trace["source_bindings"]:
                self.assertTrue(binding["source_ids"])
                for span in binding["source_spans"]:
                    self.assertEqual(
                        span["text"], text[span["start_char"]:span["end_char"]]
                    )
                    if (
                        trace["query_ir_json_pointer"].split("/")[1]
                        in material_heads
                        and _c3_pointer_get(
                            query_ir, trace["query_ir_json_pointer"]
                        ) not in ([], {})
                        and span["start_char"] == 0
                        and span["end_char"] == len(text)
                    ):
                        broad_material_bindings += 1
        self.assertEqual(0, broad_material_bindings)

        ast_mentions = {
            item["surface_mention_id"]: item
            for item in self.compiled["clause_ast"]["surface_mentions"]
        }
        selected = self.core()["resolved_mentions"][0]
        source = ast_mentions[selected["surface_mention_id"]]
        trace = next(
            item for item in traces
            if item["query_ir_json_pointer"] == "/mentions/0/entity_id"
        )
        ast_binding = next(
            item for item in trace["source_bindings"]
            if item["object_kind"] == "CLAUSE_AST"
        )
        self.assertEqual([source["surface_mention_id"]], ast_binding["source_ids"])
        self.assertEqual([source["source_span"]], ast_binding["source_spans"])

    def test_trace_source_binding_tampers_and_wrong_occurrence_fail_closed(self):
        text = "华支睾吸虫病的确诊方法是粪便检查粪便检查。"
        actual = request("C3-TRACE-OCCURRENCE", text)
        normalized = normalize_request(actual)
        ast = compile_clause_ast(normalized)
        binding = diagnostic_argument_binding(
            normalized,
            ast,
            [("diagnosed_by", "华支睾吸虫病", ("粪便检查", 1))],
        )
        with tempfile.TemporaryDirectory(prefix="p9b1q-c3-trace-tamper-") as directory:
            proof_root = Path(directory)
            compiled = compile_c3(
                actual,
                diagnostic_argument_binding=binding,
                proof_root=proof_root,
            )
            typed = compiled["typed_constraint_result"]
            core = typed["selected_solution"]
            method_index = next(
                index for index, item in enumerate(core["resolved_mentions"])
                if item["surface_mention_id"] == "U004"
            )
            pointer = f"/mentions/{method_index}/entity_id"
            first_method = next(
                item for item in ast["surface_mentions"]
                if item["surface_mention_id"] == "U003"
            )

            def changed_result(mutator):
                changed = copy.deepcopy(typed)
                trace = next(
                    item for item in changed["selected_solution"]
                    ["queryir_emission_record"]["field_traces"]
                    if item["query_ir_json_pointer"] == pointer
                )
                source = next(
                    item for item in trace["source_bindings"]
                    if item["object_kind"] == "CLAUSE_AST"
                )
                mutator(trace, source)
                with self.assertRaises(C3ValidationError):
                    validate_c3_result(
                        changed,
                        compiled["normalized_request"],
                        compiled["clause_ast"],
                        compiled["event_frame"],
                        proof_root=proof_root,
                        diagnostic_argument_binding=binding,
                    )

            changed_result(lambda trace, source: source.__setitem__(
                "object_sha256", "0" * 64
            ))
            changed_result(lambda trace, source: source.update({
                "object_kind": "EVENT_FRAME",
                "object_sha256": canonical_sha256(compiled["event_frame"]),
                "source_ids": ["EF001"],
            }))
            changed_result(lambda trace, source: source.__setitem__(
                "source_ids", ["U999"]
            ))
            changed_result(lambda trace, source: source.update({
                "source_ids": ["U003"],
                "source_spans": [first_method["source_span"]],
            }))
            changed_result(lambda trace, source: source.__setitem__(
                "source_spans", [first_method["source_span"]]
            ))
            changed_result(lambda trace, source: trace.__setitem__(
                "emitted_value_sha256", "0" * 64
            ))

    def test_profile_and_general_domains_coexist_before_constraints(self):
        text = (
            "来自流行地区并有生食淡水鱼史，可以作为华支睾吸虫病的什么证据？"
            "吡喹酮治疗华支睾吸虫病。"
        )
        c2 = compile_c2(request("C3-MIXED-DOMAIN", text))
        inputs = _c3_authority_inputs(
            c2["normalized_request"], c2["clause_ast"], c2["event_frame"], ROOT
        )
        space = _c3_recomputed_solution_space(inputs)
        predicates = {
            relation["predicate"]
            for core in space["cores"].values()
            for relation in core["resolved_relations"]
        }
        self.assertIn("has_diagnostic_clue", predicates)
        self.assertIn("treated_by", predicates)
        self.assertEqual(
            {"EXPOSURE", "TREATMENT"},
            {
                event["event_type"]
                for core in space["cores"].values()
                for event in core["resolved_events"]
            },
        )

    def test_profile_general_candidate_interleaving_is_order_invariant(self):
        import scripts.p9b1q_scoped_query_ir as scoped

        text = (
            "来自流行地区并有生食淡水鱼史，可以作为华支睾吸虫病的什么证据？"
            "吡喹酮治疗华支睾吸虫病。"
        )
        c2 = compile_c2(request("C3-CANDIDATE-ORDER", text))
        baseline = solve_typed_constraints(
            c2["normalized_request"], c2["clause_ast"], c2["event_frame"]
        )
        original = scoped._c3_profile_cores

        def reversed_candidates(*args, **kwargs):
            return list(reversed(original(*args, **kwargs)))

        with mock.patch.object(
            scoped, "_c3_profile_cores", side_effect=reversed_candidates
        ):
            permuted = solve_typed_constraints(
                c2["normalized_request"], c2["clause_ast"], c2["event_frame"]
            )
        self.assertEqual(canonical_bytes(baseline), canonical_bytes(permuted))

    def test_diagnosed_by_unspecified_polarity_is_a_legal_unique_solution(self):
        text = "华支睾吸虫病的确诊方法是粪便检查。"
        actual = request("C3-DIAGNOSED-BY-UNSPECIFIED", text)
        normalized = normalize_request(actual)
        ast = compile_clause_ast(normalized)
        binding = diagnostic_argument_binding(
            normalized, ast, [("diagnosed_by", "华支睾吸虫病", "粪便检查")]
        )
        with tempfile.TemporaryDirectory(prefix="p9b1q-c3-diagnostic-") as directory:
            compiled = compile_c3(
                actual,
                diagnostic_argument_binding=binding,
                proof_root=Path(directory),
            )
        typed = compiled["typed_constraint_result"]
        self.assertEqual("UNIQUE", typed["status"])
        selected = typed["selected_solution"]
        self.assertEqual("UNSPECIFIED", selected["resolved_events"][0]["finding_polarity"])
        self.assertEqual("diagnosed_by", selected["resolved_relations"][0]["predicate"])

    def test_event_relation_derivation_constraint_executes_on_mutation(self):
        text = "吡喹酮治疗华支睾吸虫病。"
        compiled = compile_c3(request("C3-EVENT-RELATION-CNS", text))
        typed = compiled["typed_constraint_result"]
        self.assertEqual("UNIQUE", typed["status"])
        core = copy.deepcopy(typed["selected_solution"])
        core.pop("queryir_emission_record")
        inputs = _c3_authority_inputs(
            compiled["normalized_request"],
            compiled["clause_ast"],
            compiled["event_frame"],
            ROOT,
        )
        relation = core["resolved_relations"][0]
        self.assertTrue(_c3_event_relation_derivation_matches(
            relation, core["resolved_events"], core["resolved_mentions"], inputs
        ))
        for mutation in ("predicate", "direction", "root"):
            changed = copy.deepcopy(core)
            candidate = changed["resolved_relations"][0]
            if mutation == "predicate":
                candidate["predicate"] = "controlled_by"
            elif mutation == "direction":
                candidate["subject_selector"], candidate["object_selector"] = (
                    candidate["object_selector"], candidate["subject_selector"]
                )
            else:
                candidate["root_keys"] = [
                    value for value in candidate["root_keys"]
                    if not value.startswith("RE")
                ]
            self.refresh_core(changed)
            self.assertFalse(_c3_event_relation_derivation_matches(
                candidate,
                changed["resolved_events"],
                changed["resolved_mentions"],
                inputs,
            ))
            with self.assertRaises(C3ValidationError):
                validate_c3_solution_core(
                    changed,
                    compiled["normalized_request"],
                    compiled["clause_ast"],
                    compiled["event_frame"],
                )

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


class C4PureQueryIREmitterTests(unittest.TestCase):
    UNIQUE_TEXT = (
        "来自流行地区并有生食淡水鱼史，可以作为华支睾吸虫病的什么证据？"
    )

    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory(prefix="p9b1q-c4-tests-")
        cls.proof_root = Path(cls._temporary.name)
        cls.c3 = compile_c3(
            request("C4-UNIQUE", cls.UNIQUE_TEXT), proof_root=cls.proof_root
        )

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    @staticmethod
    def emission(value):
        return value["typed_constraint_result"]["selected_solution"][
            "queryir_emission_record"
        ]

    @staticmethod
    def readdress(value):
        value["typed_constraint_result_sha256"] = canonical_sha256(
            value["typed_constraint_result"]
        )

    @classmethod
    def refresh_dag(cls, value):
        dag = cls.emission(value)["license_dag"]
        body = copy.deepcopy(dag)
        body.pop("dag_sha256")
        dag["dag_sha256"] = canonical_sha256(body)
        cls.readdress(value)

    @classmethod
    def refresh_minimality(cls, value):
        witness = cls.emission(value)["minimality_witness"]
        body = copy.deepcopy(witness)
        body.pop("witness_sha256")
        witness["witness_sha256"] = canonical_sha256(body)
        cls.readdress(value)

    def assert_c4_rejected(self, value, constraint=None, proof_root=None):
        with self.assertRaises(C4ValidationError) as caught:
            extract_queryir_c4(
                value,
                proof_root=proof_root or self.proof_root,
            )
        if constraint:
            self.assertIn(constraint, str(caught.exception))

    def test_unique_extraction_is_byte_identical_and_pure(self):
        extracted = extract_queryir_c4(self.c3, proof_root=self.proof_root)
        embedded = self.emission(self.c3)["query_ir"]
        self.assertEqual(canonical_bytes(embedded), canonical_bytes(extracted))
        self.assertIsNot(embedded, extracted)
        self.assertEqual(
            self.emission(self.c3)["query_ir_sha256"], canonical_sha256(extracted)
        )
        validate_schema(extracted, QUERY_IR_SCHEMA_PATH)

    def test_production_entry_reaches_c4_and_stops_before_s5(self):
        with tempfile.TemporaryDirectory(prefix="p9b1q-c4-production-") as directory:
            with mock.patch(
                "scripts.p9b1q_scoped_query_ir.run_scoped_query",
                side_effect=AssertionError("retrieval invoked"),
            ), mock.patch(
                "scripts.p9b1q_scoped_query_ir.execute_query_ir",
                side_effect=AssertionError("runtime binding invoked"),
            ), mock.patch(
                "scripts.p9b1q_scoped_query_ir.build_bound_execution",
                side_effect=AssertionError("response generation invoked"),
            ):
                value = compile_c4(
                    request("C4-PRODUCTION", self.UNIQUE_TEXT),
                    proof_root=Path(directory),
                )
        self.assertEqual(C4_TERMINAL_STAGE, value["terminal_stage"])
        self.assertEqual(list(C4_IMPLEMENTED_STAGES), value["implemented_stages"])
        self.assertEqual("UNIQUE", value["typed_constraint_result"]["status"])
        self.assertIn("query_ir", value)
        self.assertNotIn("retrieval_result", value)
        self.assertNotIn("runtime_binding", value)
        validate_c4_stop_boundary(value)

    def test_non_unique_and_failed_predecessors_emit_no_queryir(self):
        ambiguous = compile_c3(request(
            "C4-AMBIGUOUS",
            "来自流行地区并有生食淡水鱼史，可以作为华支睾吸虫病"
            "华支睾吸虫病的什么证据？",
        ))
        unsupported = compile_c3(request("C4-UNSUPPORTED", "粪便检卵阳性。"))
        c2 = compile_c2(request("C4-INVALID", self.UNIQUE_TEXT))
        invalid = copy.deepcopy(self.c3)
        invalid["typed_constraint_result"] = solve_typed_constraints(
            c2["normalized_request"], c2["clause_ast"], c2["event_frame"],
            bound_hashes={"CLAUSE_AST": "0" * 64},
        )
        self.readdress(invalid)
        for name, value in (
            ("AMBIGUOUS", ambiguous),
            ("UNSUPPORTED", unsupported),
            ("INVALID", invalid),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                self.assertIsNone(
                    extract_queryir_c4(value, proof_root=Path(directory))
                )
        failed = copy.deepcopy(self.c3)
        failed.pop("typed_constraint_result")
        self.assert_c4_rejected(failed, "CNS-EMIT-VALID_STATUS")

    def test_queryir_schema_hash_and_explicit_array_tampers_fail(self):
        schema_tamper = copy.deepcopy(self.c3)
        del self.emission(schema_tamper)["query_ir"]["ambiguities"]
        self.emission(schema_tamper)["query_ir_sha256"] = canonical_sha256(
            self.emission(schema_tamper)["query_ir"]
        )
        self.readdress(schema_tamper)
        self.assert_c4_rejected(schema_tamper, "CNS-EMIT-QUERYIR_SCHEMA")

        hash_tamper = copy.deepcopy(self.c3)
        self.emission(hash_tamper)["query_ir_sha256"] = "0" * 64
        self.readdress(hash_tamper)
        self.assert_c4_rejected(hash_tamper, "CNS-EMIT-TRACE_VALUE_HASH")

    def test_trace_coverage_pointer_and_value_tampers_fail(self):
        missing = copy.deepcopy(self.c3)
        self.emission(missing)["field_traces"].pop()
        self.readdress(missing)
        self.assert_c4_rejected(missing, "CNS-EMIT-LEAF_TRACE_COVERAGE")

        duplicate = copy.deepcopy(self.c3)
        copied = copy.deepcopy(self.emission(duplicate)["field_traces"][0])
        copied["trace_id"] = "TR9999"
        self.emission(duplicate)["field_traces"].append(copied)
        self.readdress(duplicate)
        self.assert_c4_rejected(duplicate)

        redirected = copy.deepcopy(self.c3)
        first, second = self.emission(redirected)["field_traces"][:2]
        first["query_ir_json_pointer"], second["query_ir_json_pointer"] = (
            second["query_ir_json_pointer"], first["query_ir_json_pointer"]
        )
        self.readdress(redirected)
        self.assert_c4_rejected(redirected, "CNS-EMIT-TRACE_VALUE_HASH")

        value_hash = copy.deepcopy(self.c3)
        self.emission(value_hash)["field_traces"][0]["emitted_value_sha256"] = "0" * 64
        self.readdress(value_hash)
        self.assert_c4_rejected(value_hash, "CNS-EMIT-TRACE_VALUE_HASH")

    def test_trace_source_hash_kind_id_and_span_tampers_fail(self):
        pointer = "/mentions/0/entity_id"

        def source(value):
            trace = next(
                item for item in self.emission(value)["field_traces"]
                if item["query_ir_json_pointer"] == pointer
            )
            return next(
                item for item in trace["source_bindings"]
                if item["object_kind"] == "CLAUSE_AST"
            )

        changed = copy.deepcopy(self.c3)
        source(changed)["object_sha256"] = "0" * 64
        self.readdress(changed)
        self.assert_c4_rejected(changed, "CNS-EMIT-TRACE_VALUE_HASH")

        changed = copy.deepcopy(self.c3)
        binding = source(changed)
        binding["object_kind"] = "EVENT_FRAME"
        binding["object_sha256"] = canonical_sha256(changed["event_frame"])
        binding["source_ids"] = ["EF001"]
        self.readdress(changed)
        self.assert_c4_rejected(changed, "CNS-EMIT-TRACE_VALUE_HASH")

        changed = copy.deepcopy(self.c3)
        source(changed)["source_ids"] = ["U002"]
        self.readdress(changed)
        self.assert_c4_rejected(changed, "CNS-EMIT-TRACE_VALUE_HASH")

        changed = copy.deepcopy(self.c3)
        wrong = next(
            item["source_span"] for item in changed["clause_ast"]["surface_mentions"]
            if item["surface_mention_id"] == "U002"
        )
        source(changed)["source_spans"] = [wrong]
        self.readdress(changed)
        self.assert_c4_rejected(changed, "CNS-EMIT-TRACE_VALUE_HASH")

    def test_synchronized_queryir_and_trace_hash_mutation_fails_projection(self):
        changed = copy.deepcopy(self.c3)
        emission = self.emission(changed)
        relation = emission["query_ir"]["relation_intents"][0]
        relation["predicate"] = "treated_by"
        trace = next(
            item for item in emission["field_traces"]
            if item["query_ir_json_pointer"] == "/relation_intents/0/predicate"
        )
        trace["emitted_value_sha256"] = canonical_sha256("treated_by")
        emission["query_ir_sha256"] = canonical_sha256(emission["query_ir"])
        self.readdress(changed)
        self.assert_c4_rejected(changed, "CNS-EMIT-PROJECTION_ONLY")

    def test_readdressed_request_binding_tamper_fails(self):
        changed = copy.deepcopy(self.c3)
        emission = self.emission(changed)
        emission["request_id"] = "P9B1Q-C4-REDIRECTED"
        self.readdress(changed)
        self.assert_c4_rejected(changed, "CNS-EMIT-PROJECTION_ONLY")

    def test_request_clause_mention_event_and_relation_projection_tampers_fail(self):
        mutations = {
            "request": lambda q: q.__setitem__("request_id", "P9B1Q-OTHER"),
            "clause": lambda q: q["clauses"][0].__setitem__("order", 2),
            "mention": lambda q: q["mentions"][0].__setitem__(
                "entity_id", "disease.clonorchiasis"
            ),
            "event": lambda q: q["events"][0].__setitem__("event_type", "TREATMENT"),
            "relation": lambda q: q["relation_intents"][0].__setitem__(
                "activation_policy", "OPTIONAL"
            ),
            "role": lambda q: q["required_roles"][0].__setitem__(
                "role_value", "treatment"
            ),
            "narrative": lambda q: q["narrative_intents"][0].__setitem__(
                "topic_scope", "treatment"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(self.c3)
                emission = self.emission(changed)
                mutate(emission["query_ir"])
                emission["query_ir_sha256"] = canonical_sha256(emission["query_ir"])
                self.readdress(changed)
                self.assert_c4_rejected(changed)

    def test_license_dag_negative_matrix_fails_closed(self):
        def missing_node(value):
            dag = self.emission(value)["license_dag"]
            removed = dag["nodes"].pop()
            dag["topological_order"].remove(removed["node_id"])
            dag["edges"] = [
                item for item in dag["edges"]
                if removed["node_id"] not in (item["from_node_id"], item["to_node_id"])
            ]

        def orphan_node(value):
            dag = self.emission(value)["license_dag"]
            extra = copy.deepcopy(dag["nodes"][0])
            extra.update({"node_id": "LN9999", "semantic_object_id": "M999"})
            dag["nodes"].append(extra)
            dag["topological_order"].append("LN9999")

        def missing_edge(value):
            self.emission(value)["license_dag"]["edges"].pop()

        def invalid_from(value):
            self.emission(value)["license_dag"]["edges"][0]["from_node_id"] = "LN9999"

        def invalid_to(value):
            self.emission(value)["license_dag"]["edges"][0]["to_node_id"] = "LN9999"

        def cycle(value):
            dag = self.emission(value)["license_dag"]
            edge = copy.deepcopy(dag["edges"][0])
            edge["edge_id"] = "LE9999"
            edge["from_node_id"], edge["to_node_id"] = edge["to_node_id"], edge["from_node_id"]
            dag["edges"].append(edge)

        def bad_order(value):
            self.emission(value)["license_dag"]["topological_order"].reverse()

        def wrong_terminal(value):
            nodes = self.emission(value)["license_dag"]["nodes"]
            nodes[0]["semantic_object_id"], nodes[-1]["semantic_object_id"] = (
                nodes[-1]["semantic_object_id"], nodes[0]["semantic_object_id"]
            )

        def wrong_trace(value):
            dag = self.emission(value)["license_dag"]
            dag["nodes"][0]["source_binding_ids"] = [
                self.emission(value)["field_traces"][-1]["trace_id"]
            ]

        for name, mutate in (
            ("missing_node", missing_node),
            ("orphan_node", orphan_node),
            ("missing_edge", missing_edge),
            ("invalid_from", invalid_from),
            ("invalid_to", invalid_to),
            ("cycle", cycle),
            ("bad_order", bad_order),
            ("wrong_terminal", wrong_terminal),
            ("wrong_trace", wrong_trace),
        ):
            with self.subTest(name=name):
                changed = copy.deepcopy(self.c3)
                mutate(changed)
                self.refresh_dag(changed)
                self.assert_c4_rejected(changed, "CNS-EMIT-LICENSE_COVERAGE")

    def test_minimality_witness_and_removal_probe_negative_matrix(self):
        def missing(value):
            self.emission(value)["minimality_witness"]["retained_object_witnesses"].pop()

        def orphan(value):
            self.emission(value)["minimality_witness"]["retained_object_witnesses"][0][
                "semantic_object_id"
            ] = "M999"

        def duplicate(value):
            witnesses = self.emission(value)["minimality_witness"]["retained_object_witnesses"]
            witnesses.append(copy.deepcopy(witnesses[0]))

        def wrong_pointer(value):
            self.emission(value)["minimality_witness"]["retained_object_witnesses"][0][
                "query_ir_json_pointer"
            ] = "/mentions/1"

        def wrong_probe_hash(value):
            self.emission(value)["minimality_witness"]["retained_object_witnesses"][0][
                "removal_probe_sha256"
            ] = "0" * 64

        def wrong_probe_path(value):
            self.emission(value)["minimality_witness"]["retained_object_witnesses"][0][
                "removal_probe_path"
            ] = "proof-objects/removal-probe/" + "0" * 64 + ".json"

        def wrong_constraints(value):
            item = self.emission(value)["minimality_witness"]["retained_object_witnesses"][0]
            item["supporting_constraint_ids"] = ["CNS-SOLVER-EVENT_IDENTITY"]
            item["removal_unsatisfied_constraint_ids"] = ["CNS-SOLVER-EVENT_IDENTITY"]

        for name, mutate in (
            ("missing", missing),
            ("orphan", orphan),
            ("duplicate", duplicate),
            ("wrong_pointer", wrong_pointer),
            ("wrong_probe_hash", wrong_probe_hash),
            ("wrong_probe_path", wrong_probe_path),
            ("wrong_constraints", wrong_constraints),
        ):
            with self.subTest(name=name):
                changed = copy.deepcopy(self.c3)
                mutate(changed)
                self.refresh_minimality(changed)
                self.assert_c4_rejected(changed)

    def test_readdressed_semantic_universe_and_removal_probe_tampers_fail(self):
        with tempfile.TemporaryDirectory(prefix="p9b1q-c4-readdressed-proof-") as directory:
            proof_root = Path(directory)
            compiled = compile_c3(
                request("C4-READDRESSED-PROOF", self.UNIQUE_TEXT), proof_root=proof_root
            )
            emission = self.emission(compiled)
            minimality = emission["minimality_witness"]

            universe_path = proof_root / minimality["semantic_universe_path"]
            universe = json.loads(universe_path.read_text(encoding="utf-8"))
            universe["semantic_objects"][0]["query_ir_json_pointer"] = "/mentions/1"
            new_universe_sha = canonical_sha256(universe)
            new_universe_path = (
                proof_root / "proof-objects/semantic-universe" / f"{new_universe_sha}.json"
            )
            new_universe_path.write_bytes(canonical_bytes(universe))
            minimality["semantic_universe_path"] = str(
                new_universe_path.relative_to(proof_root)
            )
            minimality["semantic_universe_sha256"] = new_universe_sha
            self.refresh_minimality(compiled)
            self.assert_c4_rejected(
                compiled, "CNS-EMIT-MINIMALITY_WITNESS", proof_root
            )

        with tempfile.TemporaryDirectory(prefix="p9b1q-c4-readdressed-probe-") as directory:
            proof_root = Path(directory)
            compiled = compile_c3(
                request("C4-READDRESSED-PROBE", self.UNIQUE_TEXT), proof_root=proof_root
            )
            emission = self.emission(compiled)
            witness = emission["minimality_witness"]["retained_object_witnesses"][0]
            old_path = proof_root / witness["removal_probe_path"]
            probe = json.loads(old_path.read_text(encoding="utf-8"))
            probe["expected_unsatisfied_constraint_ids"] = [
                "CNS-SOLVER-EVENT_IDENTITY"
            ]
            new_probe_sha = canonical_sha256(probe)
            new_probe_path = proof_root / "proof-objects/removal-probe" / f"{new_probe_sha}.json"
            new_probe_path.write_bytes(canonical_bytes(probe))
            witness["removal_probe_path"] = str(new_probe_path.relative_to(proof_root))
            witness["removal_probe_sha256"] = new_probe_sha
            self.refresh_minimality(compiled)
            self.assert_c4_rejected(
                compiled, "CNS-EMIT-MINIMALITY_WITNESS", proof_root
            )

    def test_persisted_core_universe_and_path_security_fail_closed(self):
        bad_paths = (
            "../proof-objects/removal-probe/" + "0" * 64 + ".json",
            "/tmp/" + "0" * 64 + ".json",
            "C:/tmp/" + "0" * 64 + ".json",
            "\\\\server\\share\\proof.json",
            "https://example.invalid/proof.json",
        )
        for path in bad_paths:
            with self.subTest(path=path):
                changed = copy.deepcopy(self.c3)
                self.emission(changed)["minimality_witness"]["retained_object_witnesses"][0][
                    "removal_probe_path"
                ] = path
                self.refresh_minimality(changed)
                self.assert_c4_rejected(changed)

        with tempfile.TemporaryDirectory(prefix="p9b1q-c4-proof-security-") as directory:
            proof_root = Path(directory)
            compiled = compile_c3(
                request("C4-MISSING-CORE", self.UNIQUE_TEXT), proof_root=proof_root
            )
            digest = self.emission(compiled)["semantic_solution_core_sha256"]
            (proof_root / "proof-objects/typed-solution-core" / f"{digest}.json").unlink()
            self.assert_c4_rejected(
                compiled, "CNS-EMIT-MINIMALITY_WITNESS", proof_root
            )

        with tempfile.TemporaryDirectory(prefix="p9b1q-c4-symlink-") as directory:
            proof_root = Path(directory)
            compiled = compile_c3(
                request("C4-SYMLINK", self.UNIQUE_TEXT), proof_root=proof_root
            )
            witness = self.emission(compiled)["minimality_witness"]["retained_object_witnesses"][0]
            target = proof_root / witness["removal_probe_path"]
            outside = proof_root / "outside.json"
            outside.write_bytes(target.read_bytes())
            target.unlink()
            target.symlink_to(outside)
            self.assert_c4_rejected(
                compiled, "CNS-EMIT-MINIMALITY_WITNESS", proof_root
            )

    def test_c3_solver_trace_and_high008_regressions_survive_c4(self):
        mixed = compile_c3(request(
            "C4-MIXED-REGRESSION",
            self.UNIQUE_TEXT + "吡喹酮治疗华支睾吸虫病。",
        ))
        predicates = {
            relation["predicate"]
            for core in _c3_recomputed_solution_space(_c3_authority_inputs(
                mixed["normalized_request"], mixed["clause_ast"], mixed["event_frame"], ROOT
            ))["cores"].values()
            for relation in core["resolved_relations"]
        }
        self.assertTrue({"has_diagnostic_clue", "treated_by"} <= predicates)
        self.assertEqual(48, len(c3_constraint_coverage()))

        actual = request("C4-HIGH008", "华支睾吸虫病的确诊方法是粪便检查。")
        normalized = normalize_request(actual)
        ast = compile_clause_ast(normalized)
        binding = diagnostic_argument_binding(
            normalized, ast, [("diagnosed_by", "华支睾吸虫病", "粪便检查")]
        )
        with tempfile.TemporaryDirectory(prefix="p9b1q-c4-high008-") as directory:
            value = compile_c4(
                actual,
                diagnostic_argument_binding=binding,
                proof_root=Path(directory),
            )
        self.assertEqual("AFFIRMED", value["query_ir"]["events"][0]["assertion_status"])
        self.assertEqual("UNSPECIFIED", value["query_ir"]["events"][0]["finding_polarity"])

    def test_three_fresh_c4_runs_are_byte_deterministic(self):
        hashes = []
        for index in range(3):
            with tempfile.TemporaryDirectory(prefix=f"p9b1q-c4-det-{index}-") as directory:
                root = Path(directory)
                for name in (("z", "a") if index % 2 else ("a", "z")):
                    (root / f"{name}{index}").mkdir()
                request_path = root / "request.json"
                request_path.write_text(json.dumps(
                    request("C4-DETERMINISM", self.UNIQUE_TEXT), ensure_ascii=False
                ), encoding="utf-8")
                environment = os.environ.copy()
                environment["PYTHONHASHSEED"] = str(101 + index)
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts/p9b1q_scoped_query_ir.py"),
                        "--request", str(request_path),
                        "--proof-root", str(root),
                    ],
                    cwd=root,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                value = json.loads(completed.stdout)
                hashes.append(canonical_sha256(value["query_ir"]))
        self.assertEqual([hashes[0]] * 3, hashes)


class ProductionProofChainCorrectionTests(unittest.TestCase):
    """Compare production proof bytes with the unchanged reference predicate."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        import yaml

        cls.temporary = tempfile.TemporaryDirectory(prefix="p9b1q-d1-d2-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.proof_root = Path(cls.temporary.name)
        for target in (
            "scripts.p9b1q_scoped_query_ir.execute_query_ir",
            "scripts.p9b1q_scoped_query_ir.run_scoped_query",
            "socket.create_connection",
            "socket.socket.connect",
        ):
            trap = mock.patch(target, side_effect=AssertionError(target))
            trap.start()
            cls.addClassCleanup(trap.stop)
        cls.execution = compile_c3(
            request("D1-D2", C3TypedConstraintSolverTests.UNIQUE_TEXT),
            proof_root=cls.proof_root,
        )
        if cls.execution["typed_constraint_result"]["status"] != "UNIQUE":
            raise AssertionError(cls.execution["typed_constraint_result"])
        cls.emission = cls.execution["typed_constraint_result"]["selected_solution"][
            "queryir_emission_record"
        ]
        review = ROOT / "phase9/clonorchis-sinensis/p9b1q-architecture-review"
        # Load the oracle directly, independently of the production loader/replay.
        spec = importlib.util.spec_from_file_location(
            "d1_d2_reference_oracle", review / "reference-stage-semantic-validator.py"
        )
        cls.reference = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "path", [str(review)] + sys.path):
            spec.loader.exec_module(cls.reference)
        cls.inputs = {
            "NORMALIZED_REQUEST": cls.execution["normalized_request"],
            "CLAUSE_AST": cls.execution["clause_ast"],
            "EVENT_FRAME": cls.execution["event_frame"],
            "ENTITY_ONTOLOGY": yaml.safe_load((ROOT / "schema/entity-types.yml").read_text()),
            "RELATION_ONTOLOGY": yaml.safe_load((ROOT / "schema/relation-types.yml").read_text()),
        }
        for kind, filename in (
            ("PREDICATE_TYPE_MAPPING", "fixtures/authority-predicate-type-mapping.json"),
            ("EVENT_RELATION_MAPPING", "fixtures/authority-event-relation-mapping.json"),
            ("SEMANTIC_ROLE_MAPPING", "fixtures/authority-semantic-role-mapping.json"),
            ("PROJECTION_RULE_SET", "queryir-projection-rule-set.yml"),
            ("CONSTRAINT_SET", "constraint-set-v0.1.yml"),
            ("CONSTRAINT_REGISTRY", "constraint-id-registry.yml"),
        ):
            cls.inputs[kind] = yaml.safe_load((review / filename).read_text())

    @staticmethod
    def encoded(value):
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @classmethod
    def digest(cls, value):
        return hashlib.sha256(cls.encoded(value)).hexdigest()

    def replay_witness(self, witness):
        raw = (self.proof_root / witness["removal_probe_path"]).read_bytes()
        probe = json.loads(raw)
        self.assertEqual(self.encoded(probe), raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), witness["removal_probe_sha256"])
        core_raw = (self.proof_root / probe["base_typed_solution_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(core_raw).hexdigest(), probe["base_typed_solution_sha256"])
        candidate = json.loads(core_raw)
        self.assertEqual(1, len(probe["mutation"]))
        operation = probe["mutation"][0]
        self.assertEqual("remove", operation["op"])
        collection, index = operation["path"].strip("/").split("/")
        candidate[collection].pop(int(index))
        material = {key: candidate[key] for key in (
            "resolved_mentions", "resolved_events", "resolved_relations",
            "semantic_roles", "narrative_intents", "forbidden_relations",
            "resolved_references", "resolved_overrides",
        )}
        candidate["semantic_object_set_sha256"] = self.digest(material)
        candidate["solution_id"] = "SOL-" + self.digest(material)[:24]
        self.assertEqual(self.digest(candidate), probe["candidate_typed_solution_sha256"])
        self.assertEqual(self.digest(material), probe["candidate_semantic_object_set_sha256"])
        errors = self.reference.validate_semantic_authority(
            candidate, self.inputs, require_complete=True
        )
        self.assertTrue(errors)
        order = {entry["id"]: entry["order"] for entry in self.inputs["CONSTRAINT_REGISTRY"]["entries"]}
        first = min(errors, key=lambda item: (order[item["constraint_id"]], item["json_pointer"]))
        self.assertEqual(first, errors[0])
        observed = [first["constraint_id"]]
        self.assertEqual(observed, probe["expected_unsatisfied_constraint_ids"])
        self.assertEqual(observed, witness["supporting_constraint_ids"])
        self.assertEqual(observed, witness["removal_unsatisfied_constraint_ids"])
        self.assertEqual("FAIL_CLOSED", probe["expected_result"])
        self.assertEqual(0, self.reference.finite_solution_count(candidate, self.emission, self.inputs))
        self.assertEqual(0, probe["enumerated_solution_count_after_removal"])
        return probe, errors

    def test_minimality_probe_replay_matches_reference_semantic_order(self):
        probes = {}
        for witness in self.emission["minimality_witness"]["retained_object_witnesses"]:
            with self.subTest(material=witness["semantic_object_id"]):
                probe, errors = self.replay_witness(witness)
                probes[probe["probe_id"]] = errors
        self.assertEqual({"MINPROBE-" + key for key in (
            "M01", "M05", "E01", "R01", "N01", "N02", "Q01", "Q02",
        )}, set(probes))
        # Both failures are real; registry order, not relation collection identity,
        # makes entity completeness the governing failure after removing R01.
        self.assertEqual([
            "CNS-SOLVER-ENTITY_RESOLUTION",
            "CNS-SOLVER-EVENT_RELATION_DERIVATION",
        ], [item["constraint_id"] for item in probes["MINPROBE-R01"]])

    def test_s4_consumes_semantically_replayed_minimality_proof(self):
        from scripts import p9b1q_scoped_query_ir as production

        for witness in self.emission["minimality_witness"]["retained_object_witnesses"]:
            self.replay_witness(witness)
        consume = production._c4_validate_persisted_proofs_and_minimality

        def independent_consume(*args, **kwargs):
            with mock.patch.object(
                production, "_c3_subset_satisfies", side_effect=AssertionError("shortcut replay")
            ):
                return consume(*args, **kwargs)

        with mock.patch.object(
            production, "_c3_build_emission", side_effect=AssertionError("proof regeneration")
        ), mock.patch.object(
            production, "_c4_validate_persisted_proofs_and_minimality", side_effect=independent_consume
        ):
            extracted = extract_queryir_c4(self.execution, proof_root=self.proof_root)
        self.assertEqual(self.encoded(self.emission["query_ir"]), self.encoded(extracted))

        for attack in ("later_constraint", "wrong_count", "candidate_hash"):
            with self.subTest(attack=attack):
                changed = copy.deepcopy(self.execution)
                emission = changed["typed_constraint_result"]["selected_solution"]["queryir_emission_record"]
                minimality = emission["minimality_witness"]
                witness = next(item for item in minimality["retained_object_witnesses"] if item["semantic_object_id"] == "R01")
                probe = json.loads((self.proof_root / witness["removal_probe_path"]).read_bytes())
                if attack == "later_constraint":
                    wrong = ["CNS-SOLVER-EVENT_RELATION_DERIVATION"]
                    probe["expected_unsatisfied_constraint_ids"] = wrong
                    witness["supporting_constraint_ids"] = wrong
                    witness["removal_unsatisfied_constraint_ids"] = wrong
                elif attack == "wrong_count":
                    probe["enumerated_solution_count_after_removal"] = 1
                else:
                    probe["candidate_typed_solution_sha256"] = "0" * 64
                digest = self.digest(probe)
                relative = f"proof-objects/removal-probe/{digest}.json"
                (self.proof_root / relative).write_bytes(self.encoded(probe))
                witness["removal_probe_path"] = relative
                witness["removal_probe_sha256"] = digest
                minimality["witness_sha256"] = self.digest({k: v for k, v in minimality.items() if k != "witness_sha256"})
                changed["typed_constraint_result_sha256"] = self.digest(changed["typed_constraint_result"])
                with self.assertRaisesRegex(C4ValidationError, "CNS-EMIT-MINIMALITY_WITNESS"):
                    extract_queryir_c4(changed, proof_root=self.proof_root)



class ReferenceProductionParityTests(unittest.TestCase):
    """Actual fresh production objects, independently read normative inputs."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        import yaml
        cls.temporary = tempfile.TemporaryDirectory(prefix="p9b1q-d3-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.proof_root = Path(cls.temporary.name)
        cls.traps = []
        for target in (
            "scripts.p9b1q_scoped_query_ir.execute_query_ir",
            "scripts.p9b1q_scoped_query_ir.run_scoped_query",
            "socket.create_connection", "socket.socket.connect",
        ):
            patch = mock.patch(target, side_effect=AssertionError(target))
            cls.traps.append(patch.start())
            cls.addClassCleanup(patch.stop)
        cls.execution = compile_c4(
            request("D3-PARITY", C3TypedConstraintSolverTests.UNIQUE_TEXT),
            proof_root=cls.proof_root,
        )
        cls.typed = cls.execution["typed_constraint_result"]
        cls.emission = cls.typed["selected_solution"]["queryir_emission_record"]
        cls.query_ir = cls.execution["query_ir"]
        review = ROOT / "phase9/clonorchis-sinensis/p9b1q-architecture-review"
        spec = importlib.util.spec_from_file_location(
            "d3_reference_oracle", review / "reference-stage-semantic-validator.py"
        )
        cls.reference = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "path", [str(review)] + sys.path):
            spec.loader.exec_module(cls.reference)
        cls.inputs = {
            "NORMALIZED_REQUEST": cls.execution["normalized_request"],
            "CLAUSE_AST": cls.execution["clause_ast"],
            "EVENT_FRAME": cls.execution["event_frame"],
        }
        cls.hashes = {k: cls.digest(v) for k, v in cls.inputs.items()}
        paths = {
            "ENTITY_ONTOLOGY": ROOT / "schema/entity-types.yml",
            "RELATION_ONTOLOGY": ROOT / "schema/relation-types.yml",
            "QUERY_IR_SCHEMA": ROOT / "phase9/clonorchis-sinensis/p9b1q/query-ir-schema-candidate.yml",
        }
        for kind, filename in (
            ("PREDICATE_TYPE_MAPPING", "fixtures/authority-predicate-type-mapping.json"),
            ("EVENT_RELATION_MAPPING", "fixtures/authority-event-relation-mapping.json"),
            ("SEMANTIC_ROLE_MAPPING", "fixtures/authority-semantic-role-mapping.json"),
            ("PROJECTION_RULE_SET", "queryir-projection-rule-set.yml"),
            ("CONSTRAINT_SET", "constraint-set-v0.1.yml"),
            ("CONSTRAINT_REGISTRY", "constraint-id-registry.yml"),
            ("CONSTRAINT_REGISTRY_SCHEMA", "constraint-id-registry-schema-candidate.yml"),
            ("CONSTRAINT_SET_SCHEMA", "constraint-set-schema-candidate.yml"),
            ("MINIMALITY_PROOF_SCHEMA", "minimality-proof-schema-candidate.yml"),
            ("TYPED_SOLUTION_CORE_SCHEMA", "typed-solution-core-schema-candidate.yml"),
            ("NEGATION_SURFACE_SCOPE_AUTHORITY", "negation-surface-scope-authority.yml"),
            ("STAGE_VALIDATOR_CONTRACT", "stage-semantic-validator-contract.yml"),
        ):
            paths[kind] = review / filename
        for kind, path in paths.items():
            raw = path.read_bytes()
            cls.inputs[kind] = yaml.safe_load(raw)
            cls.hashes[kind] = hashlib.sha256(raw).hexdigest()
        cls.inputs["NEGATION_SEMANTIC_AUTHORITY_EXECUTABLE"] = (review / "negation_semantic_authority.py").read_text()
        minimality = cls.emission["minimality_witness"]
        def persisted(relative):
            raw = (cls.proof_root / relative).read_bytes()
            value = json.loads(raw)
            if cls.encoded(value) != raw:
                raise AssertionError("noncanonical actual proof")
            return value
        cls.core = persisted("proof-objects/typed-solution-core/" + cls.emission["semantic_solution_core_sha256"] + ".json")
        cls.inputs.update({
            "TYPED_CONSTRAINT_RESULT": cls.typed,
            "QUERYIR_EMISSION_RECORD": cls.emission,
            "TYPED_SOLUTION": cls.core,
            "SEMANTIC_UNIVERSE": persisted(minimality["semantic_universe_path"]),
            "REMOVAL_PROBES": [persisted(w["removal_probe_path"]) for w in minimality["retained_object_witnesses"]],
        })
        chain = yaml.safe_load((review / "object-canonicalization-and-hash-chain.yml").read_text())
        for stage in ("S3_TYPED_SOLVER", "S4_QUERYIR_EMISSION"):
            required = set(cls.inputs["STAGE_VALIDATOR_CONTRACT"]["validators"][stage]["required_actual_inputs"])
            required.update(chain["object_chain"][stage]["actual_inputs"])
            if required - cls.inputs.keys():
                raise AssertionError(sorted(required - cls.inputs.keys()))

    @staticmethod
    def encoded(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    @classmethod
    def digest(cls, value):
        return hashlib.sha256(cls.encoded(value)).hexdigest()

    def s4(self, typed=None, inputs=None, root=None):
        with mock.patch.object(self.reference, "load_stage_result", side_effect=AssertionError("fixture fallback")):
            return self.reference.validate_s4(
                self.typed if typed is None else typed, self.query_ir,
                self.inputs if inputs is None else inputs,
                proof_root=self.proof_root if root is None else root,
            )

    def test_reference_s3_complete_production_chain(self):
        with mock.patch.object(self.reference, "load_stage_result", side_effect=AssertionError("fixture fallback")):
            self.assertEqual([], self.reference.validate_s3(
                self.typed, self.inputs, self.hashes, proof_root=self.proof_root))

    def test_reference_s4_complete_production_chain(self):
        self.assertEqual([], self.s4())
        self.assertEqual(self.encoded(self.emission["query_ir"]), self.encoded(self.query_ir))
        self.assertTrue(all(trap.call_count == 0 for trap in self.traps))

    def test_non_typed_sources_bind_actual_objects(self):
        kinds = set()
        for trace in self.emission["field_traces"]:
            for binding in trace["source_bindings"]:
                kind = binding["object_kind"]
                actual = self.core if kind == "TYPED_SOLUTION" else self.inputs[kind]
                self.assertEqual(self.digest(actual), binding["object_sha256"])
                for span in binding["source_spans"]:
                    self.assertLess(span["start_char"], span["end_char"])
                    self.assertEqual(span["text"], self.inputs["NORMALIZED_REQUEST"]["normalized_query_text"][span["start_char"]:span["end_char"]])
                kinds.add(kind)
        self.assertEqual({"NORMALIZED_REQUEST", "CLAUSE_AST", "EVENT_FRAME", "TYPED_SOLUTION", "EVENT_RELATION_MAPPING", "SEMANTIC_ROLE_MAPPING"}, kinds)
        self.assertEqual([], self.s4())

    def test_wrong_source_kind_hash_and_identifier_rejected(self):
        for field, value in (("object_kind", "UNKNOWN"), ("object_kind", "CLAUSE_AST"), ("object_sha256", "0" * 64), ("source_ids", ["EF999"]), ("source_ids", ["AFFIRMED"])):
            with self.subTest(field=field, value=value):
                typed = copy.deepcopy(self.typed)
                bindings = [b for t in typed["selected_solution"]["queryir_emission_record"]["field_traces"] for b in t["source_bindings"]]
                binding = next(b for b in bindings if b["object_kind"] == "TYPED_SOLUTION" and "EF001" in b["source_ids"])
                binding[field] = value
                errors = self.s4(typed)
                self.assertTrue(any(e["constraint_id"] == "CNS-EMIT-TRACE_VALUE_HASH" for e in errors), errors)

    def test_actual_typed_frame_id_resolves(self):
        self.assertIn("EF001", {e["frame_id"] for e in self.core["resolved_events"]})
        self.assertNotIn("EF999", self.encoded(self.core).decode())
        self.assertEqual([], self.s4())

    def test_event_projection_uses_only_retained_mentions(self):
        retained = {m["surface_mention_id"] for m in self.core["resolved_mentions"]}
        sources = {s for f in self.inputs["EVENT_FRAME"]["frames"] for slot in f["participant_slots"] for s in slot["source_ids"]}
        self.assertIn("U003", sources)
        self.assertNotIn("U003", retained)
        before = self.encoded(self.core)
        projected = self.reference.derive_queryir_projection(self.core, self.inputs)
        self.assertEqual(["M01"], projected["events"][0]["mention_ids"])
        self.assertEqual(self.query_ir, projected)
        self.assertEqual(before, self.encoded(self.core))

    def test_production_proof_context_never_falls_back(self):
        with tempfile.TemporaryDirectory(dir=self.proof_root) as missing:
            self.assertTrue(self.s4(root=Path(missing)))
            self.assertTrue(self.reference.validate_s3(self.typed, self.inputs, self.hashes, proof_root=Path(missing)))
        changed = copy.deepcopy(self.inputs)
        changed["EVENT_FRAME"]["frames"][0]["frame_id"] = "EF999"
        self.assertTrue(self.s4(inputs=changed))


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



class RefreshProducerConformanceTests(unittest.TestCase):
    """D5P oracles use persisted bytes and independent JSON/removal operations."""
    H = "phase9/clonorchis-sinensis/p9b1q-architecture-review/"
    fields = ("resolved_mentions", "resolved_events", "resolved_relations", "semantic_roles",
              "narrative_intents", "forbidden_relations", "resolved_references", "resolved_overrides")

    def setUp(self):
        import runpy
        self.producer = runpy.run_path(str(ROOT / self.H / "rebuild-reference-evidence.py"))
        self.core = json.loads((ROOT / self.H / "fixtures/typed-solution-exposure-positive.json").read_bytes())

    @staticmethod
    def independent_hash(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode("utf-8")).hexdigest()

    def simulation(self):
        temporary = tempfile.TemporaryDirectory(prefix="d5p-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"]).decode().split("\0")[:-1]
        frozen = {name: (ROOT / name).read_bytes() for name in paths}
        for name, raw in frozen.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        r3a = self.H + "fixtures/r3a-reference-override-positive.json"
        negative = self.H + "fixtures/stage-validator-negative-fixtures.yml"
        policy = {r3a: [f"/objects/minimality_probes/{i}/candidate_semantic_object_set_sha256" for i in range(3)],
                  negative: ["/base_objects/11/canonical_sha256"]}
        rules = [{"path": r3a, "pointer": pointer, "source_path": r3a,
                  "source_pointer": "/objects/typed_solution_core", "derivation": "REMOVAL_CANDIDATE_SHA256"}
                 for pointer in policy[r3a]]
        rules.append({"path": negative, "pointer": policy[negative][0],
                      "source_path": self.H + "fixtures/typed-solution-exposure-positive.json", "derivation": "RAW_SHA256"})
        return root, frozen, policy, rules

    def test_frozen_eight_collection_identity_and_solution(self):
        import runpy
        with mock.patch.object(sys, "path", [str(ROOT / self.H), *sys.path]):
            validator = runpy.run_path(str(ROOT / self.H / "reference-stage-semantic-validator.py"))
        expected = {k: self.core[k] for k in self.fields}
        self.assertEqual(expected, validator["semantic_object_set"](self.core))
        self.assertEqual(expected, self.producer["semantic_set"](self.core))
        self.assertEqual(self.independent_hash(expected), "44c949792c62a160683f36867132ef63d80664c385010a97f98a9406d7f8b2e1")
        refreshed = copy.deepcopy(self.core)
        self.producer["refresh_core"](refreshed)
        self.assertEqual(refreshed, self.core)
        self.assertEqual(refreshed["solution_id"], "SOL-44c949792c62a160683f3686")

    def test_nonempty_forbidden_relations_affect_identity(self):
        changed = copy.deepcopy(self.core)
        changed["forbidden_relations"] = [{"semantic_object_id": "PROHIBITION-ORACLE"}]
        actual = self.producer["semantic_set"](changed)
        self.assertEqual(self.independent_hash(actual), self.independent_hash({k: changed[k] for k in self.fields}))
        self.assertNotEqual(self.independent_hash(actual), self.core["semantic_object_set_sha256"])

    def test_missing_extra_and_mutated_identity_definition_rejected(self):
        for field in self.fields:
            core = copy.deepcopy(self.core)
            del core[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.producer["semantic_set"](core)
        for fields in (self.fields[:-1], self.fields + ("ninth",)):
            with self.subTest(definition=fields), self.assertRaises(ValueError):
                self.producer["semantic_set"](self.core, fields=fields)
        function = self.producer["semantic_set"]
        with mock.patch.dict(function.__globals__, SEMANTIC_COLLECTIONS=self.fields[:-1]):
            with self.assertRaises(ValueError):
                function(self.core)

    def test_narrow_r3a_replay_negative_semantics_and_idempotency(self):
        import yaml
        root, frozen, policy, rules = self.simulation()
        expected_hashes = ["556c2759109f06c8348da7960b421f96ad582d9a2762507cf3cfa794534c0b87",
                           "3cded18ddd46e9fca53056d377c401f7e140bc3c9827b94d199339a20ebf235b",
                           "d49a4c7aa749eb7a7cf5750792737a7a38513a895d0ba53da0b26ae241de0b66"]
        r3a, negative = policy
        before = json.loads(frozen[r3a])
        for i, probe in enumerate(before["objects"]["minimality_probes"]):
            candidate = copy.deepcopy(before["objects"]["typed_solution_core"])
            for operation in probe["operation"]:
                collection, index = operation["path"].split("/")[1:]
                self.assertEqual(operation["op"], "remove")
                del candidate[collection][int(index)]
            self.assertEqual(self.independent_hash({k: candidate[k] for k in self.fields}), expected_hashes[i])
        changed = self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
        self.assertEqual(changed, sorted(policy))
        after = json.loads((root / r3a).read_bytes())
        for i, probe in enumerate(after["objects"]["minimality_probes"]):
            self.assertEqual(probe["candidate_semantic_object_set_sha256"], expected_hashes[i])
            probe["candidate_semantic_object_set_sha256"] = before["objects"]["minimality_probes"][i]["candidate_semantic_object_set_sha256"]
        self.assertEqual(after, before)
        negative_before = yaml.safe_load(frozen[negative])
        negative_after = yaml.safe_load((root / negative).read_bytes())
        self.assertEqual(negative_after["cases"], negative_before["cases"])
        core_path = self.H + "fixtures/typed-solution-exposure-positive.json"
        self.assertEqual(negative_after["base_objects"][11]["canonical_sha256"], hashlib.sha256(frozen[core_path]).hexdigest())
        negative_after["base_objects"][11]["canonical_sha256"] = negative_before["base_objects"][11]["canonical_sha256"]
        self.assertEqual(negative_after, negative_before)
        self.assertEqual(self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules), [])
        for name in frozen.keys() - policy.keys():
            self.assertEqual((root / name).read_bytes(), frozen[name])

    def test_narrow_attacks_validate_whole_plan_before_any_write(self):
        for attack in ("path", "pointer", "semantic_and_hash", "authority", "schema", "wrong_derived_hash", "semantic_pointer"):
            with self.subTest(attack=attack):
                root, frozen, policy, rules = self.simulation()
                options = {}
                if attack == "path":
                    rules[-1]["path"] = self.H + "fixtures/normalized-request-exposure-positive.json"
                elif attack == "pointer":
                    rules[-1]["pointer"] = "/base_objects/0/canonical_sha256"
                elif attack == "semantic_and_hash":
                    name = rules[0]["path"]
                    candidate = json.loads(frozen[name])
                    candidate["objects"]["typed_solution_core"]["resolved_mentions"][0]["entity_id"] = "tampered"
                    core = candidate["objects"]["typed_solution_core"]
                    core["semantic_object_set_sha256"] = self.independent_hash({k: core[k] for k in self.fields})
                    core["solution_id"] = "SOL-" + core["semantic_object_set_sha256"][:24]
                    (root / name).write_text(json.dumps(candidate))
                elif attack in ("authority", "schema"):
                    name = self.H + ("constraint-set-v0.1.yml" if attack == "authority" else "typed-solution-core-schema-candidate.yml")
                    (root / name).write_bytes(frozen[name] + b"\n# drift\n")
                elif attack == "wrong_derived_hash":
                    rules[-1]["expected_value"] = "0" * 64
                else:
                    name = rules[0]["path"]
                    pointer = "/objects/minimality_probes/0/expected_constraint_id"
                    policy[name].append(pointer)
                    rules.append({"path": name, "pointer": pointer, "source_path": name, "derivation": "RAW_SHA256"})
                actual_before = {n: (root / n).read_bytes() for n in frozen}
                with self.assertRaises(ValueError):
                    self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules, **options)
                self.assertEqual(actual_before, {n: (root / n).read_bytes() for n in frozen})

    def test_narrow_prospective_patch_and_protected_output_rejection(self):
        root, frozen, policy, rules = self.simulation()
        with self.assertRaises(ValueError):
            self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules,
                                           prospective_bytes={rules[0]["path"]: b"{}"})
        policy[self.H + "constraint-set-v0.1.yml"] = ["/sha256"]
        with self.assertRaises(ValueError):
            self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
        self.assertEqual(frozen, {n: (root / n).read_bytes() for n in frozen})

    def test_narrow_determinism_without_network_retrieval_or_model(self):
        import socket
        hashes = []
        for _ in range(3):
            root, frozen, policy, rules = self.simulation()
            with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")) as connect, \
                 mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")) as connection, \
                 mock.patch("scripts.p9b1q_scoped_query_ir.execute_query_ir", side_effect=AssertionError("retrieval")) as retrieval:
                changed = self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
                self.assertEqual(connect.call_count + connection.call_count + retrieval.call_count, 0)
            digest = hashlib.sha256()
            for name in changed:
                digest.update(name.encode() + b"\0" + (root / name).read_bytes())
            hashes.append(digest.hexdigest())
        self.assertEqual(len(set(hashes)), 1)

    def test_snapshot_completeness_attacks_fail_before_output_writes(self):
        import yaml
        attacks = ("authority_omitted", "schema_omitted", "ordinary_omitted", "missing_root",
                   "extra_root", "file_symlink", "directory_symlink", "alias", "absolute",
                   "traversal", "hardlink")
        for attack in attacks:
            with self.subTest(attack=attack):
                root, frozen, policy, rules = self.simulation()
                ordinary = "scripts/p9b1q_scoped_query_ir.py"
                if attack in ("authority_omitted", "schema_omitted"):
                    name = self.H + ("constraint-set-v0.1.yml" if attack == "authority_omitted"
                                     else "typed-solution-core-schema-candidate.yml")
                    changed = yaml.safe_load(frozen[name])
                    if attack == "schema_omitted":
                        changed["properties"]["resolved_mentions"]["maxItems"] = 1
                    else:
                        changed[next(iter(changed))] = "TAMPERED_AUTHORITY"
                    (root / name).write_text(yaml.safe_dump(changed))
                    del frozen[name]
                elif attack == "ordinary_omitted":
                    del frozen[ordinary]
                elif attack == "missing_root":
                    (root / ordinary).unlink()
                elif attack == "extra_root":
                    (root / "unlisted.txt").write_text("extra")
                elif attack == "file_symlink":
                    (root / ordinary).unlink()
                    (root / ordinary).symlink_to(root / "tests/test_p9b1q_scoped_query_ir.py")
                elif attack == "directory_symlink":
                    (root / "scripts").rename(root / "moved-scripts")
                    (root / "scripts").symlink_to(root / "moved-scripts", target_is_directory=True)
                elif attack in ("alias", "absolute", "traversal"):
                    bad = {"alias": "scripts/./p9b1q_scoped_query_ir.py",
                           "absolute": str(root / ordinary),
                           "traversal": "scripts/../scripts/p9b1q_scoped_query_ir.py"}[attack]
                    frozen[bad] = frozen.pop(ordinary)
                else:
                    (root / ordinary).unlink()
                    os.link(root / "tests/test_p9b1q_scoped_query_ir.py", root / ordinary)
                before = {n: (root / n).read_bytes() for n in policy}
                with mock.patch.object(Path, "write_bytes", side_effect=AssertionError("OUTPUT_WRITE")) as write:
                    with self.assertRaises(ValueError):
                        self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
                    self.assertEqual(write.call_count, 0)
                self.assertEqual(before, {n: (root / n).read_bytes() for n in policy})

    def test_snapshot_path_set_rechecked_after_rule_evaluation(self):
        root, frozen, policy, rules = self.simulation()
        before = {n: (root / n).read_bytes() for n in policy}
        function = self.producer["narrow_refresh"]
        original = function.__globals__["sha_bytes"]
        def change_inventory(raw):
            (root / "appeared-during-validation.txt").write_text("injected")
            return original(raw)
        with mock.patch.dict(function.__globals__, sha_bytes=change_inventory), \
             mock.patch.object(Path, "write_bytes", side_effect=AssertionError("OUTPUT_WRITE")) as write:
            with self.assertRaisesRegex(ValueError, "INCOMPLETE_FROZEN_SNAPSHOT"):
                function(root, frozen_bytes=frozen, field_policy=policy, rules=rules)
            self.assertEqual(write.call_count, 0)
        self.assertEqual(before, {n: (root / n).read_bytes() for n in policy})

    def test_complete_snapshot_positive_control_matches_enumerated_root(self):
        root, frozen, policy, rules = self.simulation()
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        self.assertEqual(actual, set(frozen))
        changed = self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
        self.assertEqual(changed, sorted(policy))
        self.assertEqual(self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules), [])


    def test_source_authority_rejects_wrong_paths_roles_and_overrides_before_write(self):
        attacks = ("wrong_path", "matching_expected", "unknown_role", "override_catalog",
                   "validator_claims_script", "script_claims_validator", "wrong_role")
        for attack in attacks:
            with self.subTest(attack=attack):
                root, frozen, policy, rules = self.simulation()
                script = "scripts/p9b1q_scoped_query_ir.py"
                validator = self.H + "reference-stage-semantic-validator.py"
                if attack in ("validator_claims_script", "wrong_role"):
                    name = self.H + "fixtures/normalized-request-exposure-positive.json"
                    pointer = "/producer/executable_sha256"
                    policy[name] = [pointer]
                    rules.append({"path": name, "pointer": pointer, "derivation": "RAW_SHA256",
                                  "source_role": "REFERENCE_STAGE_VALIDATOR_EXECUTABLE", "source_path": script})
                    if attack == "wrong_role":
                        rules[-1].pop("source_path")
                        rules[-1]["source_role"] = "PRODUCTION_SCOPED_QUERY_IR_EXECUTABLE"
                elif attack == "script_claims_validator":
                    name = self.H + "design-manifest.yml"
                    pointer = "/protected_files/scripts~1p9b1q_scoped_query_ir.py"
                    policy[name] = [pointer]
                    rules.append({"path": name, "pointer": pointer, "derivation": "RAW_SHA256",
                                  "source_role": "PRODUCTION_SCOPED_QUERY_IR_EXECUTABLE", "source_path": validator})
                elif attack == "unknown_role":
                    rules[-1]["source_role"] = "UNKNOWN"
                elif attack == "override_catalog":
                    rules[-1]["role_catalog"] = {"REFERENCE_STAGE_VALIDATOR_EXECUTABLE": script}
                else:
                    rules[-1]["source_path"] = script
                    if attack == "matching_expected":
                        rules[-1]["expected_value"] = hashlib.sha256(frozen[script]).hexdigest()
                before = {n: (root / n).read_bytes() for n in policy}
                with mock.patch.object(Path, "write_bytes", side_effect=AssertionError("OUTPUT_WRITE")) as write:
                    with self.assertRaises(ValueError):
                        self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
                    self.assertEqual(write.call_count, 0)
                self.assertEqual(before, {n: (root / n).read_bytes() for n in policy})

    def test_target_record_reference_is_frozen_and_safe(self):
        import yaml
        for attack in ("changed_sibling", "synchronized_sibling", "missing_source", "unsafe_source"):
            with self.subTest(attack=attack):
                root, frozen, policy, rules = self.simulation()
                name = rules[-1]["path"]
                obj = yaml.safe_load(frozen[name])
                obj["base_objects"][11]["path"] = "scripts/p9b1q_scoped_query_ir.py"
                if attack == "synchronized_sibling":
                    obj["base_objects"][11]["canonical_sha256"] = hashlib.sha256(frozen["scripts/p9b1q_scoped_query_ir.py"]).hexdigest()
                elif attack == "missing_source":
                    obj["base_objects"][11]["path"] = "fixtures/absent-source.json"
                elif attack == "unsafe_source":
                    obj["base_objects"][11]["path"] = "../escape.json"
                raw = yaml.safe_dump(obj,sort_keys=False).encode()
                (root / name).write_bytes(raw)
                if attack in ("missing_source", "unsafe_source"):
                    frozen[name] = raw
                with mock.patch.object(Path, "write_bytes", side_effect=AssertionError("OUTPUT_WRITE")) as write:
                    with self.assertRaises(ValueError):
                        self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
                    self.assertEqual(write.call_count, 0)

    def test_r3a_source_core_and_operation_are_not_caller_authority(self):
        for attack in ("file", "core_pointer", "operation", "generic_algorithm"):
            with self.subTest(attack=attack):
                root, frozen, policy, rules = self.simulation()
                rule = rules[2]
                if attack == "file":
                    rule["source_path"] = self.H + "fixtures/typed-solution-exposure-positive.json"
                elif attack == "core_pointer":
                    rule["source_pointer"] = "/objects/query_ir"
                elif attack == "operation":
                    rule["operation"] = [{"op": "remove", "path": "/resolved_mentions/0"}]
                else:
                    rule["derivation"] = "RAW_SHA256"
                with mock.patch.object(Path, "write_bytes", side_effect=AssertionError("OUTPUT_WRITE")) as write:
                    with self.assertRaises(ValueError):
                        self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
                    self.assertEqual(write.call_count, 0)

    def test_known_source_classes_derive_from_actual_frozen_objects(self):
        import yaml
        root, frozen, policy, rules = self.simulation()
        normalized = self.H + "fixtures/normalized-request-exposure-positive.json"
        stage = self.H + "fixtures/stage-validation-s0-positive.json"
        manifest = self.H + "design-manifest.yml"
        validator = self.H + "reference-stage-semantic-validator.py"
        script = "scripts/p9b1q_scoped_query_ir.py"
        policy[normalized] = ["/producer/executable_sha256"]
        policy[stage] = ["/actual_input_objects/0/canonical_sha256", "/actual_input_objects/1/canonical_sha256",
                         "/actual_input_objects/1/byte_length", "/result_sha256"]
        policy[manifest] = ["/protected_files/scripts~1p9b1q_scoped_query_ir.py"]
        rules.extend([
            {"path": normalized, "pointer": policy[normalized][0], "derivation": "RAW_SHA256",
             "source_role": "REFERENCE_STAGE_VALIDATOR_EXECUTABLE"},
            {"path": stage, "pointer": policy[stage][0], "derivation": "CANONICAL_SHA256"},
            {"path": stage, "pointer": policy[stage][1], "derivation": "RAW_SHA256"},
            {"path": stage, "pointer": policy[stage][2], "derivation": "BYTE_LENGTH"},
            {"path": stage, "pointer": policy[stage][3], "derivation": "SELF_SHA256"},
            {"path": manifest, "pointer": policy[manifest][0], "derivation": "RAW_SHA256",
             "source_role": "PRODUCTION_SCOPED_QUERY_IR_EXECUTABLE"},
        ])
        self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
        n = json.loads((root / normalized).read_bytes())
        v = json.loads((root / stage).read_bytes())
        m = yaml.safe_load((root / manifest).read_bytes())
        self.assertEqual(n["producer"]["executable_sha256"], hashlib.sha256(frozen[validator]).hexdigest())
        self.assertEqual(m["protected_files"][script], hashlib.sha256(frozen[script]).hexdigest())
        self.assertEqual(v["actual_input_objects"][1]["canonical_sha256"], hashlib.sha256(frozen[validator]).hexdigest())
        self.assertEqual(v["actual_input_objects"][1]["byte_length"], len(frozen[validator]))
        request_path = v["actual_input_objects"][0]["content_path"]
        self.assertEqual(v["actual_input_objects"][0]["canonical_sha256"], self.independent_hash(json.loads(frozen[request_path])))
        self_hash = v.pop("result_sha256")
        self.assertEqual(self_hash, self.independent_hash(v))
        self.assertEqual(self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules), [])


    def test_real_stale_surface_sources_include_prefixed_and_fixed_roles(self):
        import yaml
        validator = self.H + "reference-stage-semantic-validator.py"
        rows = [
            ("normalized-request-exposure-positive.json", "/producer/executable_sha256", validator),
            ("minimality-removal-probe-M01.json", "/validator_executable_sha256", validator),
            ("minimality-removal-probe-M01.json", "/validator_configuration_sha256", self.H + "stage-semantic-validator-contract.yml"),
            ("reference-validator-execution-summary.json", "/executable_sha256", validator),
            ("typed-result-exposure-positive.json", "/solver/executable_sha256", validator),
            ("stage-validation-s0-positive.json", "/validator/executable_sha256", validator),
            ("execution-binding-sidecar-positive.json", "/actual_objects/29/canonical_sha256", validator),
            ("object-store-index-positive.json", "/objects/29/canonical_sha256", validator),
        ]
        for filename, pointer, source in rows:
            with self.subTest(target=filename, pointer=pointer):
                root, frozen, _, _ = self.simulation()
                name = self.H + "fixtures/" + filename
                before = json.loads(frozen[name])
                # No caller source path, pointer or role establishes authority.
                rule = {"path": name, "pointer": pointer, "derivation": "RAW_SHA256"}
                self.producer["narrow_refresh"](root, frozen_bytes=frozen,
                    field_policy={name: [pointer]}, rules=[rule])
                after = json.loads((root / name).read_bytes())
                parts = pointer.strip("/").split("/")
                old, new = before, after
                for part in parts[:-1]:
                    old = old[int(part)] if isinstance(old, list) else old[part]
                    new = new[int(part)] if isinstance(new, list) else new[part]
                self.assertEqual(new[parts[-1]], hashlib.sha256(frozen[source]).hexdigest())
                new[parts[-1]] = old[parts[-1]]
                self.assertEqual(after, before)
                self.assertEqual([], self.producer["narrow_refresh"](root, frozen_bytes=frozen,
                    field_policy={name: [pointer]}, rules=[rule]))

    def test_corr3_source_assertions_cannot_create_authority(self):
        cases = ("prefixed_path", "configuration_path", "summary_role", "solver_role",
                 "arbitrary_target", "catalog", "wrong_role_matching_hash", "wrong_path_matching_hash")
        for attack in cases:
            with self.subTest(attack=attack):
                root, frozen, policy, rules = self.simulation()
                name = self.H + "fixtures/minimality-removal-probe-M01.json"
                pointer = "/validator_executable_sha256"
                rule = {"path": name, "pointer": pointer, "derivation": "RAW_SHA256"}
                script = "scripts/p9b1q_scoped_query_ir.py"
                if attack in ("prefixed_path", "wrong_path_matching_hash"):
                    rule["source_path"] = script
                elif attack == "configuration_path":
                    rule["pointer"] = "/validator_configuration_sha256"
                    rule["source_path"] = self.H + "reference-stage-semantic-validator.py"
                elif attack in ("summary_role", "wrong_role_matching_hash"):
                    rule.update(path=self.H + "fixtures/reference-validator-execution-summary.json",
                                pointer="/executable_sha256", source_role="PRODUCTION_SCOPED_QUERY_IR_EXECUTABLE")
                elif attack == "solver_role":
                    rule.update(path=self.H + "fixtures/typed-result-exposure-positive.json",
                                pointer="/solver/executable_sha256", source_role="PRODUCTION_SCOPED_QUERY_IR_EXECUTABLE")
                elif attack == "arbitrary_target":
                    rule.update(pointer="/validator_contract_sha256", source_role="REFERENCE_STAGE_VALIDATOR_EXECUTABLE")
                else:
                    rule["role_catalog"] = {"REFERENCE_STAGE_VALIDATOR_EXECUTABLE": script}
                if attack.endswith("matching_hash"):
                    rule["expected_value"] = hashlib.sha256(frozen[script]).hexdigest()
                policy.setdefault(rule["path"], []).append(rule["pointer"])
                rules.append(rule)
                with mock.patch.object(Path, "write_bytes", side_effect=AssertionError("OUTPUT_WRITE")) as write:
                    with self.assertRaises(ValueError):
                        self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
                    self.assertEqual(0, write.call_count)

    def test_write_phase_and_final_boundary_drift_roll_back_transaction(self):
        for attack in ("authority", "schema", "second_target", "extra", "symlink", "final"):
            with self.subTest(attack=attack):
                root, frozen, policy, rules = self.simulation()
                first, second = sorted(policy)
                protected = self.H + ("typed-solution-core-schema-candidate.yml" if attack == "schema"
                                      else "constraint-set-v0.1.yml")
                original = os.write
                events = []
                drifted = [False]
                external = b"externally changed bytes\n"
                def observed_write(fd, raw):
                    target = Path(os.readlink(f"/proc/self/fd/{fd}"))
                    relative = target.relative_to(root).as_posix()
                    rollback = raw == frozen[relative]
                    events.append((relative, rollback, drifted[0]))
                    count = original(fd, raw)
                    trigger = second if attack == "final" else first
                    if not rollback and relative == trigger and not drifted[0]:
                        drifted[0] = True
                        if attack == "extra":
                            (root / "extra-during-write").write_bytes(external)
                        elif attack == "symlink":
                            (root / protected).unlink()
                            (root / protected).symlink_to(root / "scripts/p9b1q_scoped_query_ir.py")
                        else:
                            (root / (second if attack == "second_target" else protected)).write_bytes(external)
                    return count
                with mock.patch.object(os, "write", observed_write):
                    with self.assertRaisesRegex(ValueError, "REFRESH_TRANSACTION_FAIL_CLOSED"):
                        self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
                self.assertTrue(drifted[0])
                self.assertEqual([], [e for e in events if e[2] and not e[1]])
                written = {n for n, rollback, _ in events if not rollback}
                self.assertEqual({first, second} if attack == "final" else {first}, written)
                self.assertEqual(written, {n for n, rollback, _ in events if rollback})
                for name in written:
                    self.assertEqual(frozen[name], (root / name).read_bytes())
                if attack == "second_target":
                    self.assertEqual(external, (root / second).read_bytes())
                elif attack == "extra":
                    self.assertEqual(external, (root / "extra-during-write").read_bytes())
                elif attack == "symlink":
                    self.assertTrue((root / protected).is_symlink())
                else:
                    self.assertEqual(external, (root / protected).read_bytes())
                for name in frozen.keys() - written - {protected, second}:
                    self.assertEqual(frozen[name], (root / name).read_bytes())

    def test_rollback_rejects_replaced_output_path_without_touching_referent(self):
        root, frozen, policy, rules = self.simulation()
        first = sorted(policy)[0]
        protected = "scripts/p9b1q_scoped_query_ir.py"
        original = os.write
        calls = []
        pinned = []
        def replace_written_output(fd, raw):
            count = original(fd, raw)
            if not calls:
                target = root / first
                calls.append(target)
                pinned.append(os.dup(fd))
                self.addCleanup(os.close, pinned[0])
                target.unlink()
                target.symlink_to(root / protected)
            return count
        with mock.patch.object(os, "write", replace_written_output):
            with self.assertRaisesRegex(ValueError, "REFRESH_TRANSACTION_FAIL_CLOSED"):
                self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
        self.assertEqual([root / first], calls)
        self.assertEqual(frozen[protected], (root / protected).read_bytes())
        self.assertTrue((root / first).is_symlink())
        self.assertEqual(frozen[first], os.pread(pinned[0], len(frozen[first]) + 1, 0))

    def test_pinned_original_objects_survive_directory_and_path_identity_attacks(self):
        import shutil
        for attack in ("parent_after_first", "parent_before_first", "parent_after_final",
                       "deep_ancestor", "root", "file_replacement", "file_symlink",
                       "parent_symlink", "unlink", "rename"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory(prefix="d5p-moved-") as temporary:
                root, frozen, policy, rules = self.simulation()
                first, second = sorted(policy)
                original_write, original_open = os.write, os.open
                identities = {(os.stat(root / n).st_dev, os.stat(root / n).st_ino): n for n in policy}
                moved = Path(temporary) / "original"
                duplicates, events, external_before = {}, [], {}
                injected = [False]
                def inject():
                    injected[0] = True
                    target = root / first
                    if attack in ("file_replacement", "file_symlink", "unlink", "rename"):
                        raw = target.read_bytes()
                        if attack == "unlink":
                            target.unlink()
                        else:
                            target.rename(moved)
                            if attack == "file_replacement":
                                target.write_bytes(raw)
                                external_before[target] = raw
                            elif attack == "file_symlink":
                                target.symlink_to(root / "scripts/p9b1q_scoped_query_ir.py")
                    else:
                        directory = (root if attack == "root" else root / "phase9"
                                     if attack == "deep_ancestor" else target.parent)
                        directory.rename(moved)
                        if attack == "parent_symlink":
                            directory.symlink_to(moved, target_is_directory=True)
                        else:
                            shutil.copytree(moved, directory)
                            external_before.update({p: p.read_bytes() for p in directory.rglob("*") if p.is_file()})
                def observe_open(target, flags, *args, **kwargs):
                    fd = original_open(target, flags, *args, **kwargs)
                    info = os.fstat(fd)
                    name = identities.get((info.st_dev, info.st_ino))
                    if name and flags & os.O_RDWR and name not in duplicates:
                        duplicates[name] = os.dup(fd)
                        if attack == "parent_before_first" and len(duplicates) == len(policy):
                            inject()
                    return fd
                def observe_write(fd, raw):
                    info = os.fstat(fd)
                    name = identities[(info.st_dev, info.st_ino)]
                    rollback = bytes(raw) == frozen[name]
                    events.append((name, rollback, injected[0]))
                    count = original_write(fd, raw)
                    if not injected[0] and not rollback:
                        if attack != "parent_after_final" or name == second:
                            inject()
                    return count
                try:
                    with mock.patch.object(os, "open", observe_open), mock.patch.object(os, "write", observe_write):
                        with self.assertRaisesRegex(ValueError, "REFRESH_TRANSACTION_FAIL_CLOSED"):
                            self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
                    self.assertTrue(injected[0])
                    self.assertEqual([], [e for e in events if e[2] and not e[1]])
                    written = {n for n, rollback, _ in events if not rollback}
                    expected = set() if attack == "parent_before_first" else set(policy) if attack == "parent_after_final" else {first}
                    self.assertEqual(expected, written)
                    for name in written:
                        fd = duplicates[name]
                        self.assertEqual(frozen[name], os.pread(fd, len(frozen[name]) + 1, 0))
                        self.assertEqual(len(frozen[name]), os.fstat(fd).st_size)
                    for path, raw in external_before.items():
                        self.assertEqual(raw, path.read_bytes(), str(path))
                    if attack.startswith("parent_") and attack != "parent_before_first":
                        self.assertEqual(frozen[first], (moved / Path(first).name).read_bytes())
                    if attack == "file_symlink":
                        self.assertTrue((root / first).is_symlink())
                        self.assertEqual(frozen["scripts/p9b1q_scoped_query_ir.py"],
                                         (root / "scripts/p9b1q_scoped_query_ir.py").read_bytes())
                finally:
                    for fd in duplicates.values():
                        os.close(fd)

    def test_pinned_rollback_failure_is_explicit_and_short_writes_are_completed(self):
        for fail_rollback in (False, True):
            with self.subTest(fail_rollback=fail_rollback):
                root, frozen, policy, rules = self.simulation()
                first = sorted(policy)[0]
                original = os.write
                injected = [False]
                def write(fd, raw):
                    if fail_rollback:
                        if injected[0]:
                            raise OSError("independent rollback I/O failure")
                        count = original(fd, raw)
                        injected[0] = True
                        (root / "extra-drift").write_bytes(b"external")
                        return count
                    return original(fd, raw[:max(1, len(raw) // 2)])
                with mock.patch.object(os, "write", write):
                    if fail_rollback:
                        with self.assertRaisesRegex(ValueError, "ROLLBACK_FAILED"):
                            self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
                    else:
                        changed = self.producer["narrow_refresh"](root, frozen_bytes=frozen, field_policy=policy, rules=rules)
                        self.assertEqual(sorted(policy), changed)
                        self.assertEqual([], self.producer["narrow_refresh"](
                            root, frozen_bytes=frozen, field_policy=policy, rules=rules))


if __name__ == "__main__":
    unittest.main()
