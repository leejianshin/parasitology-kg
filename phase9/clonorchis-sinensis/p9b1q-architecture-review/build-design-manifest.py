#!/usr/bin/env python3
"""Build the raw-byte inventory for the R3-E governance candidate."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUTPUT = HERE / "design-manifest.yml"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


protected_paths = [
    "scripts/p9b1q_scoped_query_ir.py",
    "tests/test_p9b1q_scoped_query_ir.py",
    "phase9/clonorchis-sinensis/p9b1q/query-interpreter-config.yml",
    "phase9/clonorchis-sinensis/request-schema.yml",
    "phase9/clonorchis-sinensis/response-schema.yml",
    "phase9/clonorchis-sinensis/audit-log-schema.yml",
]
design = {
    path.name: sha(path)
    for path in sorted(HERE.iterdir())
    if path.is_file() and path != OUTPUT
}
fixtures = {
    f"fixtures/{path.name}": sha(path)
    for path in sorted((HERE / "fixtures").iterdir())
    if path.is_file()
}
protected = {path: sha(REPO / path) for path in protected_paths}
manifest = {
    "manifest_id": "P9B1Q-R3E-FAILURE-CODE-GOVERNANCE-DESIGN-MANIFEST-v1.0",
    "status": "R3E_LOCAL_CANDIDATE_PENDING_FINAL_RE_REVIEW",
    "integration_parent_commit": "9f79ebd48eadd48e53747eb3318f30f0ee97e1f9",
    "frozen_implementation_commit": "6ac0e4b2978e5fb41e7b90e27ced17826d35a394",
    "hash_algorithm": "SHA256_RAW_FILE_BYTES",
    "manifest_self_hash_excluded": True,
    "inventory_counts": {
        "design_files": len(design),
        "fixture_files": len(fixtures),
        "protected_files": len(protected),
    },
    "protected_files": protected,
    "design_files": design,
    "fixture_files": fixtures,
    "executable_evidence": {
        "path": "reference-stage-semantic-validator.py",
        "sha256": sha(HERE / "reference-stage-semantic-validator.py"),
        "configuration_path": "stage-semantic-validator-contract.yml",
        "configuration_sha256": sha(HERE / "stage-semantic-validator-contract.yml"),
        "summary_path": "fixtures/reference-validator-execution-summary.json",
        "summary_sha256": sha(HERE / "fixtures/reference-validator-execution-summary.json"),
        "required_result": "PASS",
        "positive_cases": 9,
        "integrated_r3b_positive_cases": 4,
        "minimality_cases": 8,
        "negative_cases": 49,
        "repeat_runs": 3,
    },
    "shared_negation_semantic_authority": {
        "data_path": "negation-surface-scope-authority.yml",
        "data_sha256": sha(HERE / "negation-surface-scope-authority.yml"),
        "implementation_path": "negation_semantic_authority.py",
        "implementation_sha256": sha(HERE / "negation_semantic_authority.py"),
        "standalone_cli_path": "negation-scope-authority-validator.py",
        "standalone_cli_is_authority": False,
        "authoritative_consumers": [
            "reference-stage-semantic-validator.py::validate_s1",
            "reference-stage-semantic-validator.py::validate_s3",
        ],
    },
    "schema_gate": {
        "runner": "strict-schema-gate.mjs",
        "runner_sha256": sha(HERE / "strict-schema-gate.mjs"),
        "dependency_lock": "package-lock.json",
        "dependency_lock_sha256": sha(HERE / "package-lock.json"),
        "engine": "AJV_8_17_1_DRAFT_2020_12_STRICT",
        "compiled_schema_count": 12,
        "positive_fixture_pair_count": 27,
    },
    "object_store_index_binding": {
        "index_path": "fixtures/object-store-index-positive.json",
        "sidecar_path": "fixtures/execution-binding-sidecar-positive.json",
        "non_sidecar_entry_contract": "EXACT_ONE_TO_ONE_WITH_SIDECAR_ACTUAL_OBJECTS",
        "bound_fields": ["path", "object_kind", "canonical_sha256"],
        "sidecar_entry_cardinality": 1,
        "constraint_id": "CNS-BIND-ACTUAL_OBJECT_HASH",
    },
    "failure_code_governance": {
        "canonical_authority": "constraint-id-registry.yml",
        "formal_gate": "reference-stage-semantic-validator.py::validate_failure_code_governance",
        "formal_emitter_paths": [
            "reference-stage-semantic-validator.py",
            "negation_semantic_authority.py",
        ],
        "registry_mapping_count": 46,
        "validator_constraint_mapping_count": 45,
        "required_mismatch_count": 0,
        "response_audit_regression_fixture": "NEG-S5-RESPONSE-AUDIT-HASH-MISMATCH",
    },
    "negative_fixture_mutation_isolation": {
        "model_path": "negative-fixture-semantic-mutation-model.yml",
        "semantic_mutation_target_cardinality": 1,
        "stage_fixture_count": 35,
        "r3a_fixture_count": 16,
        "r3b_fixture_count": 14,
        "total_fixture_count": 65,
        "derived_updates_runner_owned": True,
        "legacy_cases": [
            "NEG-S3-EMPTY-UNIQUE",
            "NEG-S4-INVALID-STATUS-WITH-TRACE",
            "NEG-S1-NONEXACT-ALIAS-SURFACE",
        ],
    },
    "boundaries": {
        "implementation_mutation": False,
        "p9a_contract_mutation": False,
        "model_or_network_use_at_runtime": False,
        "r11_frozen": False,
        "push_or_pr": False,
        "p9b2_started": False,
    },
}
OUTPUT.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
print(f"{OUTPUT.name} design={len(design)} fixtures={len(fixtures)} protected={len(protected)}")
