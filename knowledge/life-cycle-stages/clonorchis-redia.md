---
schema_version: "1.1"
id: stage.clonorchis_redia
entity_type: life_cycle_stage
name_zh: 华支睾吸虫雷蚴
name_en: Clonorchis sinensis redia
scientific_name: null
aliases: []
one_health_domains: [animal_health]
summary: 雷蚴是华支睾吸虫在适宜淡水螺宿主体内发育并产生尾蚴的阶段。
review_status: reviewed
admission:
  batch_id: P7-PCMS
  source_ledger: phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml
  atom_ids: [PCMS-017]
relations:
  - predicate: develops_into
    object: stage.clonorchis_cercaria
    statement_zh: 华支睾吸虫雷蚴在适宜螺宿主体内发育为尾蚴。
    relation_status: reviewed
    evidence:
      - {source_id: source.pmph_human_parasitology_10e_2024, locator: "印刷页94–95【生活史】", evidence_type: direct_statement}
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Life Cycle", evidence_type: direct_statement}
    qualifiers: {source_atom_id: PCMS-017, condition: within_suitable_snail_host}
review: {extracted_by: pcms_formal_admission, reviewed_by: course_lead, last_reviewed: "2026-07-27"}
---

# 华支睾吸虫雷蚴

## 核心知识

雷蚴在适宜淡水螺宿主体内发育为尾蚴。

## One Health联系

该阶段仍位于淡水螺所承担的第一中间宿主环节。

## 学习提示

尾蚴离开螺以后才进入下一宿主环节。

## 证据边界

本最低集不扩展雷蚴的繁殖代数。
