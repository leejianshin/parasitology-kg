from scripts.validate_pcms import validate
from scripts.build_pcms_graph import build_pcms_graph, render_artifacts
from scripts.validate_pcms_regression import evaluate

import yaml


def test_pcms_review_bundle_is_internally_consistent() -> None:
    counts = validate()
    assert counts == {
        "groups": 9,
        "claims": 36,
        "relation_claims": 30,
        "narrative_claims": 6,
        "regression_cases": 16,
    }


def test_pcms_aggregate_preserves_base_and_adds_minimum_set() -> None:
    nodes, edges, _canonical_hash, details = build_pcms_graph()
    assert len(nodes) == 31
    assert len(edges) == 40
    assert details == {
        "base_nodes": 14,
        "base_edges": 10,
        "pcms_nodes": 17,
        "pcms_edges": 30,
        "extension_documents": 3,
        "narrative_claims": 6,
    }
    relation_ids = {
        edge["qualifiers"]["source_atom_id"]
        for edge in edges
        if edge["qualifiers"]["source_atom_id"].startswith("PCMS-")
    }
    assert relation_ids == {
        f"PCMS-{index:03d}" for index in range(7, 37)
    }


def test_pcms_release_boundary_excludes_private_class_data() -> None:
    manifest = yaml.safe_load(render_artifacts()["manifest.yml"])
    assert manifest["release_boundary"] == {
        "student_release_authorized": False,
        "student_roster_included": False,
        "raw_score_data_included": False,
        "collaborative_review": "CHEN_HAIYING_PENDING",
    }


def test_pcms_regression_contract_passes() -> None:
    report = evaluate()
    assert report["status"] == "PASS"
    assert report["counts"] == {"cases": 16, "passed": 16, "failed": 0}
