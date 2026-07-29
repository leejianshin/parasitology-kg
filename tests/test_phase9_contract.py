from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate_phase9_contract import (
    ALLOWED_RUNTIME_INPUTS,
    AUDIT_PATH,
    BUNDLE_MANIFEST_PATH,
    PLAN_PATH,
    RELEASE_PATH,
    RESPONSE_PATH,
    REVIEW_PATH,
    ROOT,
    RUNTIME_PATH,
    canonical_sha256,
    load_yaml,
    validate_audit_instance,
    validate_contract_data,
    validate_response_instance,
    verify_runtime_bundle,
)


class Phase9ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = load_yaml(RUNTIME_PATH)
        self.response = load_yaml(RESPONSE_PATH)
        self.audit = load_yaml(AUDIT_PATH)
        self.review = load_yaml(REVIEW_PATH)
        self.release = load_yaml(RELEASE_PATH)
        self.plan = load_yaml(PLAN_PATH)
        fixture_dir = ROOT / "tests" / "fixtures" / "phase9"
        self.answer_response = load_yaml(
            fixture_dir / "response-answer-valid.yml"
        )
        self.abstain_response = load_yaml(
            fixture_dir / "response-abstain-valid.yml"
        )
        self.answer_audit = load_yaml(
            fixture_dir / "audit-answer-valid.yml"
        )
        self.unverified_audit = load_yaml(
            fixture_dir / "audit-unverified-valid.yml"
        )

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

    def test_runtime_bundle_contract_hash_cannot_drift(self) -> None:
        self.runtime = copy.deepcopy(self.runtime)
        self.runtime["authority"]["runtime_bundle_manifest"][
            "bundle_sha256"
        ] = "0" * 64
        with self.assertRaisesRegex(ValueError, "trust root"):
            self.validate()

    def test_runtime_bundle_file_content_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary) / "repo"
            temp_root.mkdir()
            paths = [*ALLOWED_RUNTIME_INPUTS]
            paths.append(
                str(BUNDLE_MANIFEST_PATH.relative_to(ROOT))
            )
            for relative_path in paths:
                source = ROOT / relative_path
                target = temp_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            tampered = temp_root / ALLOWED_RUNTIME_INPUTS[2]
            tampered.write_bytes(tampered.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                verify_runtime_bundle(
                    temp_root, verify_source_commit=False
                )

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

    def test_invalid_json_schema_definition_is_rejected(self) -> None:
        self.response = copy.deepcopy(self.response)
        self.response["properties"]["answer_text"]["type"] = (
            "not-a-json-schema-type"
        )
        with self.assertRaisesRegex(ValueError, "schema is invalid"):
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

    def test_complete_acceptance_case_content_cannot_drift(self) -> None:
        self.plan = copy.deepcopy(self.plan)
        self.plan["case_migrations"][0]["source_case_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "complete source case"):
            self.validate()

    def test_f03_adjudication_must_continue_to_block_release(self) -> None:
        self.plan = copy.deepcopy(self.plan)
        self.plan["adjudication_cases"]["release_effect"] = "IGNORE"
        with self.assertRaisesRegex(ValueError, "adjudication-case"):
            self.validate()

    def test_review_completion_enum_is_executable(self) -> None:
        self.review = copy.deepcopy(self.review)
        self.review["review_intake_contract"][
            "completion_status_enum"
        ].remove("PROVISIONAL")
        with self.assertRaisesRegex(ValueError, "completion status enum"):
            self.validate()

    def test_valid_answer_and_abstention_responses_pass(self) -> None:
        validate_response_instance(self.answer_response, ROOT)
        validate_response_instance(self.abstain_response, ROOT)

    def test_unknown_response_claim_is_rejected(self) -> None:
        response = copy.deepcopy(self.answer_response)
        response["material_claims"][0]["claim_id"] = "PCMS-999"
        response["citations"][0]["claim_id"] = "PCMS-999"
        with self.assertRaisesRegex(ValueError, "unknown claim"):
            validate_response_instance(response, ROOT)

    def test_unknown_response_entity_is_rejected(self) -> None:
        response = copy.deepcopy(self.answer_response)
        response["material_claims"][0]["entity_ids"] = [
            "entity.unknown"
        ]
        with self.assertRaisesRegex(ValueError, "entity IDs"):
            validate_response_instance(response, ROOT)

    def test_unregistered_response_source_is_rejected(self) -> None:
        response = copy.deepcopy(self.answer_response)
        response["citations"][0]["source_id"] = "source.unregistered"
        with self.assertRaisesRegex(ValueError, "unregistered source"):
            validate_response_instance(response, ROOT)

    def test_wrong_response_locator_is_rejected(self) -> None:
        response = copy.deepcopy(self.answer_response)
        response["citations"][0]["locator"] = "invented locator"
        with self.assertRaisesRegex(ValueError, "locator does not support"):
            validate_response_instance(response, ROOT)

    def test_citation_to_nonmaterial_claim_is_rejected(self) -> None:
        response = copy.deepcopy(self.answer_response)
        response["citations"][0]["claim_id"] = "PCMS-030"
        with self.assertRaisesRegex(ValueError, "material claim"):
            validate_response_instance(response, ROOT)

    def test_material_claim_without_citation_is_rejected(self) -> None:
        response = copy.deepcopy(self.answer_response)
        response["citations"] = []
        with self.assertRaisesRegex(
            ValueError, "schema validation failed|lack"
        ):
            validate_response_instance(response, ROOT)

    def test_required_qualifier_omission_is_rejected(self) -> None:
        response = copy.deepcopy(self.answer_response)
        response["material_claims"][0] = {
            "claim_id": "PCMS-029",
            "sentence_indexes": [0],
            "entity_ids": [
                "disease.clonorchiasis",
                "diagnostic.duodenal_fluid_egg_microscopy",
            ],
            "qualifiers": {},
        }
        response["citations"][0] = {
            "citation_id": "CIT-001",
            "claim_id": "PCMS-029",
            "source_id": "source.pmph_human_parasitology_10e_2024",
            "source_label": "人体寄生虫学",
            "locator": "印刷页96【实验诊断】",
            "visible_to_student": True,
        }
        with self.assertRaisesRegex(ValueError, "required qualifiers"):
            validate_response_instance(response, ROOT)

    def test_empty_answer_is_rejected_by_executed_schema(self) -> None:
        response = copy.deepcopy(self.answer_response)
        response["answer_text"] = ""
        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            validate_response_instance(response, ROOT)

    def test_partial_cannot_report_fail_closed(self) -> None:
        response = copy.deepcopy(self.answer_response)
        response["disposition"] = "PARTIAL"
        response["coverage_gaps"] = [
            {
                "gap_code": "PARTIALLY_COVERED",
                "description": "fixture gap",
            }
        ]
        response["validation"] = {
            "result": "FAIL_CLOSED",
            "checked_contract_id": "clonorchis_p9a_controlled_rag_v1",
            "hard_fail_codes": ["NO_SAFE_ADMITTED_ANSWER"],
        }
        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            validate_response_instance(response, ROOT)

    def test_valid_answer_and_unverified_audits_pass(self) -> None:
        validate_audit_instance(
            self.answer_audit, ROOT, response=self.answer_response
        )
        validate_audit_instance(self.unverified_audit, ROOT)

    def test_unverified_authority_cannot_log_answer(self) -> None:
        audit = copy.deepcopy(self.answer_audit)
        audit["knowledge_authority"]["hash_verified"] = False
        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            validate_audit_instance(audit, ROOT)

    def test_answer_audit_cannot_have_zero_visible_citations(self) -> None:
        audit = copy.deepcopy(self.answer_audit)
        audit["output_validation"][
            "student_visible_citation_count"
        ] = 0
        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            validate_audit_instance(audit, ROOT)

    def test_audit_cannot_admit_unknown_claim(self) -> None:
        audit = copy.deepcopy(self.answer_audit)
        audit["retrieval"]["candidate_claim_ids"] = ["PCMS-999"]
        audit["retrieval"]["admitted_claim_ids"] = ["PCMS-999"]
        audit["decision"]["material_claim_ids"] = ["PCMS-999"]
        with self.assertRaisesRegex(ValueError, "unknown claim"):
            validate_audit_instance(audit, ROOT)

    def test_audit_material_claim_must_be_admitted(self) -> None:
        audit = copy.deepcopy(self.answer_audit)
        audit["retrieval"]["admitted_claim_ids"] = []
        with self.assertRaisesRegex(ValueError, "not admitted"):
            validate_audit_instance(audit, ROOT)

    def test_audit_response_hash_must_match(self) -> None:
        audit = copy.deepcopy(self.answer_audit)
        audit["response_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "response hash"):
            validate_audit_instance(
                audit, ROOT, response=self.answer_response
            )

    def test_fixture_response_hash_is_canonical(self) -> None:
        self.assertEqual(
            canonical_sha256(self.answer_response),
            self.answer_audit["response_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
