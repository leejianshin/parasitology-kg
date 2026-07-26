---
schema_version: "1.0"
id: stage.clonorchis_adult
entity_type: life_cycle_stage
name_zh: 华支睾吸虫成虫
name_en: Adult Clonorchis sinensis
scientific_name: null
aliases: []
one_health_domains:
  - human_health
  - animal_health
summary: 华支睾吸虫成虫是其生活史中的成体阶段，主要寄生于肝内小、中型胆管。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-008
relations:
  - predicate: parasitizes_site
    object: anatomy.intrahepatic_small_medium_bile_ducts
    statement_zh: 华支睾吸虫成虫主要寄生于肝内小、中型胆管。
    relation_status: reviewed
    evidence:
      - source_id: source.cdc_dpdx_clonorchiasis_2024
        locator: "Life Cycle"
        evidence_type: direct_statement
      - source_id: source.hong_kim_clonorchis_cholangiocarcinoma_review_2016
        locator: "PATHOGENESIS AND CARCINOGENESIS"
        evidence_type: direct_statement
    qualifiers:
      source_atom_id: W2-ATOM-008
      distribution: mainly
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 华支睾吸虫成虫

## 核心知识

本批次仅收录成虫的主要寄生部位。

## One Health联系

该部位关系适用于人类及相应哺乳动物终宿主体内的成虫阶段，但本批次未建立宿主角色边。

## 学习提示

“主要寄生于”是分布限定，不应写成排除所有异位情况的绝对判断。

## 证据边界

“次级胆管”暂保留为教学表达，本条采用公开权威来源支持的“肝内小、中型胆管”。
