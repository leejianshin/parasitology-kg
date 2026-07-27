#!/usr/bin/env python3
"""Validate the Phase 5 admission plan and implemented first batch."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "phase5" / "clonorchis-sinensis" / "admission-plan.yml"
LEDGER_PATH = (
    ROOT
    / "candidates"
    / "clonorchis-sinensis"
    / "phase4-approved-admission-ledger.yml"
)


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be a mapping")
    return data


def parse_front_matter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    marker = "\n---\n"
    if not text.startswith("---\n"):
        raise ValueError(f"{path} missing front matter")
    end = text.find(marker, 4)
    if end < 0:
        raise ValueError(f"{path} missing closing front matter")
    data = yaml.safe_load(text[4:end])
    if not isinstance(data, dict):
        raise ValueError(f"{path} front matter must be a mapping")
    return data


def fail(message: str) -> None:
    raise ValueError(message)


def main() -> int:
    try:
        plan = load_yaml(PLAN_PATH)
        ledger = load_yaml(LEDGER_PATH)
        ledger_ids = {
            item["atom_id"] for item in ledger["atomic_candidates"]
        }

        class_names = [
            "edge_ready",
            "qualifier_only",
            "narrative_only",
            "research_layer_retained",
        ]
        classified: list[str] = []
        for name in class_names:
            section = plan["classification"][name]
            atom_ids = section["atom_ids"]
            if section["count"] != len(atom_ids):
                fail(f"{name} count does not match atom_ids")
            classified.extend(atom_ids)

        counts = Counter(classified)
        duplicates = sorted(atom_id for atom_id, count in counts.items() if count != 1)
        if duplicates:
            fail(f"atoms classified more than once: {duplicates}")
        if set(classified) != ledger_ids:
            missing = sorted(ledger_ids - set(classified))
            extra = sorted(set(classified) - ledger_ids)
            fail(f"classification mismatch missing={missing} extra={extra}")
        if len(classified) != 39:
            fail(f"expected 39 classified atoms, found {len(classified)}")

        batch_1 = next(
            batch for batch in plan["batches"] if batch["batch_id"] == "P5-B1"
        )
        expected_review_status = batch_1["formal_review_status"]
        if batch_1["status"] != "APPROVED":
            fail("P5-B1 must be APPROVED")
        if plan["approval_gate"]["batch_1_teacher_review"] != "APPROVED":
            fail("P5-B1 teacher approval is not recorded")
        if plan["approval_gate"]["batch_2_and_3_write"] != "NOT_AUTHORIZED":
            fail("later batches must remain unauthorized")
        expected_entities = set(batch_1["entity_ids"])
        documents: dict[str, dict[str, Any]] = {}
        implemented_atoms: list[str] = []

        for path in sorted((ROOT / "knowledge").rglob("*.md")):
            if path.name == "README.md":
                continue
            metadata = parse_front_matter(path)
            admission = metadata.get("admission")
            if (
                not isinstance(admission, dict)
                or admission.get("batch_id") != "P5-B1"
            ):
                # Later reviewed batches are validated by their own admission
                # checks. They must not change the frozen P5-B1 inventory.
                continue
            entity_id = metadata["id"]
            if entity_id in documents:
                fail(f"duplicate formal entity: {entity_id}")
            documents[entity_id] = metadata

            if metadata["review_status"] != expected_review_status:
                fail(
                    f"{entity_id} must have review_status "
                    f"{expected_review_status}"
                )
            review = metadata["review"]
            if review.get("reviewed_by") != "subject_teacher":
                fail(f"{entity_id} missing subject_teacher review")
            if not review.get("last_reviewed"):
                fail(f"{entity_id} missing last_reviewed")

            for relation in metadata["relations"]:
                if relation["relation_status"] != expected_review_status:
                    fail(
                        f"{entity_id} relation must have status "
                        f"{expected_review_status}"
                    )
                source_atom_id = relation["qualifiers"].get("source_atom_id")
                if not source_atom_id:
                    fail(f"{entity_id} relation missing source_atom_id")
                implemented_atoms.append(source_atom_id)

        if set(documents) != expected_entities:
            missing = sorted(expected_entities - set(documents))
            extra = sorted(set(documents) - expected_entities)
            fail(f"P5-B1 entity mismatch missing={missing} extra={extra}")

        expected_atoms = set(batch_1["edge_atom_ids"])
        if set(implemented_atoms) != expected_atoms:
            missing = sorted(expected_atoms - set(implemented_atoms))
            extra = sorted(set(implemented_atoms) - expected_atoms)
            fail(f"P5-B1 relation mismatch missing={missing} extra={extra}")
        duplicate_relations = sorted(
            atom_id for atom_id, count in Counter(implemented_atoms).items() if count != 1
        )
        if duplicate_relations:
            fail(f"P5-B1 atoms implemented more than once: {duplicate_relations}")

        print(
            "PHASE5_ADMISSION_VALIDATION=PASS "
            f"classified={len(classified)} "
            f"entities={len(documents)} "
            f"relations={len(implemented_atoms)}"
        )
        return 0
    except (KeyError, StopIteration, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"PHASE5_ADMISSION_VALIDATION=FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
