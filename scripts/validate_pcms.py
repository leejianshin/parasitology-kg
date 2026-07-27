#!/usr/bin/env python3
"""Validate the proposed Clonorchis pilot content minimum set."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = (
    ROOT
    / "phase7"
    / "clonorchis-sinensis"
    / "pilot-content-minimum-set-authority-review.yml"
)
SCHEMA_FIT = (
    ROOT
    / "reviews"
    / "clonorchis-sinensis"
    / "pilot-content-minimum-set-schema-fit.yml"
)
REGRESSION = (
    ROOT
    / "phase7"
    / "clonorchis-sinensis"
    / "pilot-content-minimum-set-regression.yml"
)


def load(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def validate() -> dict[str, int]:
    authority = load(AUTHORITY)
    schema_fit = load(SCHEMA_FIT)
    regression = load(REGRESSION)

    if authority["status"] != "APPROVED_FOR_FORMAL_ADMISSION_CONSTRUCTION":
        raise ValueError("authority review is not approved for construction")
    if authority["formal_knowledge_admission"] != "COMPLETED_PCMS_G01_G09":
        raise ValueError("formal admission is not recorded as completed")
    if authority["student_release"] != "NOT_AUTHORIZED":
        raise ValueError("student release cannot be authorized before term")
    if (
        schema_fit["implementation_gate"]["teacher_approval"]
        != "APPROVED_BY_COURSE_LEAD"
    ):
        raise ValueError("schema fit lacks course-lead approval")
    if regression["status"] != "EXECUTED_PASS":
        raise ValueError("regression suite status changed unexpectedly")
    if regression["execution_gate"]["regression_run"] != "PASS_16_OF_16":
        raise ValueError("regression execution did not pass")
    if (
        authority["teacher_adjudication"]["collaborative_review_status"]
        != "PENDING"
    ):
        raise ValueError("Chen Haiying collaborative review must remain pending")

    claim_ids: list[str] = []
    relation_claims = 0
    narrative_claims = 0
    for group in authority["candidate_groups"]:
        for claim in group["claims"]:
            claim_ids.append(claim["claim_id"])
            if "predicate" in claim:
                relation_claims += 1
            else:
                narrative_claims += 1
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("duplicate PCMS claim_id")
    if claim_ids != [f"PCMS-{index:03d}" for index in range(1, 37)]:
        raise ValueError("PCMS claim IDs must be continuous from 001 to 036")
    declared = authority["schema_fit_summary"]
    if declared["proposed_atomic_claims"] != len(claim_ids):
        raise ValueError("declared atomic claim count differs")
    if declared["proposed_relation_claims"] != relation_claims:
        raise ValueError("declared relation claim count differs")
    if declared["proposed_narrative_claims"] != narrative_claims:
        raise ValueError("declared narrative claim count differs")

    cases = regression["test_cases"]
    if len(cases) != regression["counts"]["total"]:
        raise ValueError("regression case count differs")
    dispositions = Counter(case["expected_disposition"] for case in cases)
    expected = {
        "ANSWER": regression["counts"]["answer"],
        "PARTIAL": regression["counts"]["partial"],
        "ABSTAIN": regression["counts"]["abstain"],
    }
    if dict(dispositions) != expected:
        raise ValueError(f"unexpected dispositions: {dict(dispositions)}")
    valid_claims = set(claim_ids) | {f"W2-ATOM-{index:03d}" for index in range(1, 40)}
    for case in cases:
        unknown = set(case["required_claim_ids"]) - valid_claims
        if unknown:
            raise ValueError(f"{case['case_id']} references unknown claims: {unknown}")
        if case["expected_disposition"] == "ABSTAIN":
            if case["required_claim_ids"] or not case.get("coverage_gap"):
                raise ValueError(f"{case['case_id']} has invalid ABSTAIN contract")
        if case["expected_disposition"] == "PARTIAL" and not case.get("coverage_gap"):
            raise ValueError(f"{case['case_id']} needs a coverage gap")

    return {
        "groups": len(authority["candidate_groups"]),
        "claims": len(claim_ids),
        "relation_claims": relation_claims,
        "narrative_claims": narrative_claims,
        "regression_cases": len(cases),
    }


def main() -> int:
    try:
        counts = validate()
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"PCMS_VALIDATION=FAIL {exc}")
        return 1
    print(
        "PCMS_VALIDATION=PASS "
        + " ".join(f"{key}={value}" for key, value in counts.items())
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
