---
schema_version: "1.1"
id: stage.clonorchis_sporocyst
entity_type: life_cycle_stage
name_zh: 华支睾吸虫胞蚴
name_en: Clonorchis sinensis sporocyst
scientific_name: null
aliases: []
one_health_domains: [animal_health]
summary: 胞蚴是华支睾吸虫在适宜淡水螺宿主体内的发育阶段。
review_status: reviewed
admission:
  batch_id: P7-PCMS
  source_ledger: phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml
  atom_ids: [PCMS-016]
relations:
  - predicate: develops_into
    object: stage.clonorchis_redia
    statement_zh: 华支睾吸虫胞蚴在适宜螺宿主体内发育为雷蚴。
    relation_status: reviewed
    evidence:
      - {source_id: source.pmph_human_parasitology_10e_2024, locator: "印刷页94–95【生活史】", evidence_type: direct_statement}
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Life Cycle", evidence_type: direct_statement}
    qualifiers: {source_atom_id: PCMS-016, condition: within_suitable_snail_host}
review: {extracted_by: pcms_formal_admission, reviewed_by: course_lead, last_reviewed: "2026-07-27"}
---

# 华支睾吸虫胞蚴

## 核心知识

胞蚴在适宜淡水螺宿主体内继续发育为雷蚴。

## One Health联系

该阶段位于淡水螺所承担的第一中间宿主环节。

## 学习提示

胞蚴与雷蚴是相邻而不同的发育阶段。

## 证据边界

本最低集不写入未单独核查的代数和繁殖数量。
