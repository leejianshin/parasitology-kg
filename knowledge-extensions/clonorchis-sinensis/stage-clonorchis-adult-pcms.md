---
schema_version: "1.0"
extension_id: extension.clonorchis_pcms_adult
extends_entity: stage.clonorchis_adult
review_status: reviewed
admission:
  batch_id: P7-PCMS
  source_ledger: phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml
  atom_ids: [PCMS-001, PCMS-002, PCMS-026]
relations:
  - predicate: pathogenic_stage_for
    object: disease.clonorchiasis
    statement_zh: 华支睾吸虫成虫是华支睾吸虫病的主要致病阶段。
    relation_status: reviewed
    evidence:
      - {source_id: source.pmph_human_parasitology_10e_2024, locator: "印刷页94–95【形态】【致病】", evidence_type: direct_statement}
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Life Cycle; Clinical Presentation", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-026
      role: major_pathogenic_stage
      unique_pathogenic_factor: false
review: {reviewed_by: course_lead, last_reviewed: "2026-07-27", collaborative_review: chen_haiying_pending}
---

# 华支睾吸虫成虫 PCMS扩展

## 结构化叙述

- `PCMS-001`：成虫背腹扁平，呈狭长或披针形。
- `PCMS-002`：成虫大小约为`10–25 mm × 3–5 mm`。

成虫是华支睾吸虫病的主要致病阶段，但“主要”不表示成虫是疾病过程中唯一的致病因素。

## 证据边界

本扩展不改写Phase 5已经冻结的成虫寄生部位关系。
