from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class RelationSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entity_catalog = yaml.safe_load(
            (ROOT / "schema" / "entity-types.yml").read_text(encoding="utf-8")
        )
        cls.relation_catalog = yaml.safe_load(
            (ROOT / "schema" / "relation-types.yml").read_text(encoding="utf-8")
        )
        cls.decision = yaml.safe_load(
            (
                ROOT
                / "reviews"
                / "clonorchis-sinensis"
                / "phase4-schema-extension-decision.yml"
            ).read_text(encoding="utf-8")
        )

    def test_relation_catalog_structure(self) -> None:
        entity_types = set(self.entity_catalog["entity_types"])
        relations = self.relation_catalog["relations"]
        self.assertEqual(self.relation_catalog["schema_version"], "1.2")
        self.assertTrue(relations)

        required = {
            "label_zh",
            "inverse_label_zh",
            "subject_types",
            "object_types",
            "description",
        }
        for relation_name, relation in relations.items():
            with self.subTest(relation=relation_name):
                self.assertEqual(required, set(relation))
                self.assertTrue(relation["label_zh"])
                self.assertTrue(relation["inverse_label_zh"])
                self.assertTrue(relation["description"])
                self.assertTrue(set(relation["subject_types"]) <= entity_types)
                self.assertTrue(set(relation["object_types"]) <= entity_types)

    def test_four_admitted_relations_have_canonical_directions(self) -> None:
        relations = self.relation_catalog["relations"]
        expected = {
            "has_diagnostic_clue": (
                ["disease"],
                ["behavior", "clinical_manifestation", "diagnostic_method"],
            ),
            "occurs_in": (["pathological_process"], ["anatomical_site"]),
            "has_complication": (["disease"], ["disease"]),
            "epidemiologically_associated_with": (["disease"], ["disease"]),
        }

        for name, (subjects, objects) in expected.items():
            with self.subTest(relation=name):
                self.assertIn(name, relations)
                self.assertEqual(relations[name]["subject_types"], subjects)
                self.assertEqual(relations[name]["object_types"], objects)

    def test_overbroad_or_deferred_names_are_not_controlled_relations(self) -> None:
        relations = self.relation_catalog["relations"]
        excluded = {
            "serves_as_diagnostic_clue",
            "associated_with_complication",
            "associated_with",
            "showed_effect_in_context",
        }
        self.assertTrue(excluded.isdisjoint(relations))

    def test_pcms_schema_extensions_have_strict_directions(self) -> None:
        relations = self.relation_catalog["relations"]
        expected = {
            "pathogenic_stage_for": (
                ["life_cycle_stage"],
                ["disease"],
            ),
            "classified_as": (
                ["disease"],
                ["hazard_classification"],
            ),
            "sheds_stage": (
                ["host"],
                ["life_cycle_stage"],
            ),
            "present_in_environment": (
                ["life_cycle_stage"],
                ["environment"],
            ),
        }
        self.assertIn(
            "hazard_classification",
            self.entity_catalog["entity_types"],
        )
        for name, (subjects, objects) in expected.items():
            with self.subTest(relation=name):
                self.assertEqual(relations[name]["subject_types"], subjects)
                self.assertEqual(relations[name]["object_types"], objects)

    def test_five_requests_are_decided_once(self) -> None:
        decisions = self.decision["decisions"]
        request_names = [item["request_relation"] for item in decisions]
        self.assertEqual(len(request_names), 5)
        self.assertEqual(len(request_names), len(set(request_names)))
        self.assertEqual(
            {item["decision"] for item in decisions},
            {"APPROVE", "APPROVE_WITH_REVISION", "DEFER"},
        )
        self.assertEqual(
            sum(item["decision"] != "DEFER" for item in decisions),
            self.decision["scope"]["admitted_relation_classes"],
        )
        self.assertEqual(
            sum(item["decision"] == "DEFER" for item in decisions),
            self.decision["scope"]["deferred_relation_classes"],
        )

    def test_phase5_and_knowledge_write_remain_blocked(self) -> None:
        self.assertEqual(
            self.decision["scope"]["formal_knowledge_graph_admission"],
            "NOT_AUTHORIZED",
        )
        self.assertEqual(self.decision["scope"]["knowledge_files_changed"], 0)
        self.assertTrue(
            self.decision["phase_gate"]["phase5_formal_admission"].startswith(
                "BLOCKED_"
            )
        )


if __name__ == "__main__":
    unittest.main()
