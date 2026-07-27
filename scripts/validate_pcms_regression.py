#!/usr/bin/env python3
"""Validate PCMS claim coverage and fixed regression contracts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    from .build_pcms_graph import ROOT, build_pcms_graph
except ImportError:
    from build_pcms_graph import ROOT, build_pcms_graph


SUITE_PATH = (
    ROOT
    / "phase7"
    / "clonorchis-sinensis"
    / "pilot-content-minimum-set-regression.yml"
)
DEFAULT_REPORT = (
    ROOT
    / "phase7"
    / "clonorchis-sinensis"
    / "pilot-content-minimum-set-regression-report.yml"
)
NARRATIVE_IDS = {f"PCMS-{index:03d}" for index in range(1, 7)}
REQUIRED_BOUNDARY_TOKENS = {
    "PCMS-029": {"routine_first_choice": False},
    "PCMS-030": {
        "authority": "WHO",
        "recommendation_role": "recommended",
    },
    "PCMS-031": {
        "authority": "US_CDC",
        "recommendation_role": "alternative",
    },
    "PCMS-032": {
        "hazard_not_individual_probability": True,
        "individual_cancer_certainty": False,
    },
    "PCMS-035": {"direct_human_infectivity": False},
    "PCMS-036": {"universal_elimination_claim": False},
}


def load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def evaluate(root: Path = ROOT) -> dict[str, Any]:
    suite = load(
        root
        / "phase7"
        / "clonorchis-sinensis"
        / "pilot-content-minimum-set-regression.yml"
    )
    _nodes, edges, canonical_hash, _details = build_pcms_graph(root)
    edge_by_atom = {
        edge["qualifiers"]["source_atom_id"]: edge for edge in edges
    }
    supporting_narrative_ids = {
        atom_id
        for edge in edges
        for atom_id in edge["qualifiers"].get(
            "supporting_narrative_atom_ids", []
        )
    }
    available_claims = (
        set(edge_by_atom) | NARRATIVE_IDS | supporting_narrative_ids
    )

    failures: list[str] = []
    for atom_id, expected in REQUIRED_BOUNDARY_TOKENS.items():
        edge = edge_by_atom.get(atom_id)
        if edge is None:
            failures.append(f"{atom_id}: missing edge")
            continue
        for key, value in expected.items():
            if edge["qualifiers"].get(key) != value:
                failures.append(
                    f"{atom_id}: qualifier {key} expected {value!r}"
                )

    case_results: list[dict[str, Any]] = []
    for case in suite["test_cases"]:
        required = set(case["required_claim_ids"])
        missing = sorted(required - available_claims)
        result = "PASS" if not missing else "FAIL"
        if missing:
            failures.append(f"{case['case_id']}: missing {missing}")
        case_results.append(
            {
                "case_id": case["case_id"],
                "expected_disposition": case["expected_disposition"],
                "result": result,
                "required_claim_ids": case["required_claim_ids"],
                "missing_claim_ids": missing,
            }
        )

    excluded_text = "\n".join(
        edge["statement_zh"] for edge in edges
    )
    if "三苯双脒" in excluded_text:
        failures.append("excluded treatment tribendimidine entered graph")

    return {
        "report_version": "1.0",
        "suite_id": suite["suite_id"],
        "status": "PASS" if not failures else "FAIL",
        "canonical_graph_sha256": canonical_hash,
        "counts": {
            "cases": len(case_results),
            "passed": sum(item["result"] == "PASS" for item in case_results),
            "failed": sum(item["result"] == "FAIL" for item in case_results),
        },
        "case_results": case_results,
        "boundary_checks": {
            "required_qualifiers": (
                "PASS" if not any("qualifier" in item for item in failures) else "FAIL"
            ),
            "tribendimidine_excluded": (
                "PASS"
                if "excluded treatment tribendimidine entered graph" not in failures
                else "FAIL"
            ),
            "student_release_authorized": False,
            "student_roster_included": False,
            "raw_score_data_included": False,
        },
        "failures": failures,
        "interpretation_boundary": (
            "本报告验证正式图的命题覆盖、关系限定和固定测试契约，不替代尚未开始的"
            "学生试用，也不把结构回归通过解释为教学效果已经得到证明。"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = evaluate(args.root.resolve())
        content = yaml.safe_dump(
            report, allow_unicode=True, sort_keys=False
        ).encode("utf-8")
        report_path = args.report.resolve()
        if args.write:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_bytes(content)
            action = "WRITE"
        else:
            if not report_path.exists() or report_path.read_bytes() != content:
                raise ValueError("PCMS regression report is missing or stale")
            action = "CHECK"
        print(
            f"PCMS_REGRESSION_{action}={report['status']} "
            f"cases={report['counts']['cases']} "
            f"passed={report['counts']['passed']} "
            f"failed={report['counts']['failed']}"
        )
        return 0 if report["status"] == "PASS" else 1
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"PCMS_REGRESSION=FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
