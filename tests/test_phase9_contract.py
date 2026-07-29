from __future__ import annotations

import copy
import unittest

from scripts.validate_phase9_contract import (
    AUDIT_PATH,
    PLAN_PATH,
    RELEASE_PATH,
    RESPONSE_PATH,
    REVIEW_PATH,
    ROOT,
    RUNTIME_PATH,
    load_yaml,
    validate_contract_data,
)


class Phase9ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = load_yaml(RUNTIME_PATH)
        self.response = load_yaml(RESPONSE_PATH)
        self.audit = load_yaml(AUDIT_PATH)
        self.review = load_yaml(REVIEW_PATH)
        self.release = load_yaml(RELEASE_PATH)
        self.plan = load_yaml(PLAN_PATH)

    def validate(self) -> dict[str, int]:
        return validate_contract_data(
            self.runtime,
            self.response,
            self.audit,
            self.review,
            self.release,
            self.plan,
            ROOT,
        )

    def test_frozen_p9a_contract_is_valid(self) -> None:
        self.assertEqual(
            self.validate(),
            {
                "entities": 31,
                "relation_claims": 40,
                "narrative_claims": 6,
                "acceptance_cases": 16,
                "review_records": 2,
            },
        )

    def test_external_web_cannot_be_removed_from_prohibited_inputs(
        self,
    ) -> None:
        self.runtime = copy.deepcopy(self.runtime)
        self.runtime["authority"]["prohibited_runtime_inputs"].remove(
            "external_web"
        )
        with self.assertRaisesRegex(ValueError, "prohibited-input boundary"):
            self.validate()

    def test_backend_trace_cannot_replace_student_visible_sources(
        self,
    ) -> None:
        self.runtime = copy.deepcopy(self.runtime)
        self.runtime["student_visible_provenance"][
            "backend_trace_is_not_sufficient"
        ] = False
        with self.assertRaisesRegex(ValueError, "Backend trace|backend trace"):
            self.validate()

    def test_response_schema_cannot_hide_citations(self) -> None:
        self.response = copy.deepcopy(self.response)
        citation = self.response["properties"]["citations"]["items"]
        citation["properties"]["visible_to_student"] = {"type": "boolean"}
        with self.assertRaisesRegex(ValueError, "hidden citations"):
            self.validate()

    def test_required_medical_qualifier_cannot_be_removed(self) -> None:
        self.runtime = copy.deepcopy(self.runtime)
        controls = self.runtime["required_qualifier_controls"]
        controls[0]["required"].pop("routine_first_choice")
        with self.assertRaisesRegex(ValueError, "qualifier control set|changed"):
            self.validate()

    def test_incomplete_review_cannot_be_aggregated(self) -> None:
        self.review = copy.deepcopy(self.review)
        incomplete = next(
            item
            for item in self.review["review_records"]
            if item["reviewer_id"] == "P6-INDEPENDENT-R03"
        )
        incomplete["quantitative_aggregation"] = "AUTHORIZED"
        with self.assertRaisesRegex(ValueError, "aggregation rule changed"):
            self.validate()

    def test_critical_disagreement_cannot_be_averaged_away(self) -> None:
        self.review = copy.deepcopy(self.review)
        self.review["review_intake_contract"][
            "unresolved_critical_disagreement"
        ]["release_effect"] = "IGNORE"
        with self.assertRaisesRegex(ValueError, "must block release"):
            self.validate()

    def test_student_release_cannot_be_authorized_in_p9a(self) -> None:
        self.release = copy.deepcopy(self.release)
        self.release["not_authorized"]["student_release"] = False
        with self.assertRaisesRegex(ValueError, "student_release"):
            self.validate()

    def test_case_disposition_cannot_drift_from_pcms(self) -> None:
        self.plan = copy.deepcopy(self.plan)
        self.plan["case_migrations"][0]["expected_disposition"] = "ABSTAIN"
        with self.assertRaisesRegex(ValueError, "differs from PCMS"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
