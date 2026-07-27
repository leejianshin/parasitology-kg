---
schema_version: "1.1"
id: stage.clonorchis_metacercaria
entity_type: life_cycle_stage
name_zh: 华支睾吸虫囊蚴
name_en: Clonorchis sinensis metacercaria
scientific_name: null
aliases: []
one_health_domains: [human_health, animal_health]
summary: 囊蚴存在于适宜淡水鱼体内，是华支睾吸虫对人的感染阶段。
review_status: reviewed
admission:
  batch_id: P7-PCMS
  source_ledger: phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml
  atom_ids: [PCMS-019, PCMS-025]
relations:
  - predicate: develops_into
    object: stage.clonorchis_adult
    statement_zh: 终宿主摄入活囊蚴后，幼虫进入胆道并发育为成虫。
    relation_status: reviewed
    evidence:
      - {source_id: source.pmph_human_parasitology_10e_2024, locator: "印刷页94–95【生活史】", evidence_type: direct_statement}
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Life Cycle", evidence_type: direct_statement}
    qualifiers: {source_atom_id: PCMS-019, condition: after_ingestion_by_definitive_host}
  - predicate: infective_stage_for
    object: host.human
    statement_zh: 华支睾吸虫囊蚴是对人的感染阶段。
    relation_status: reviewed
    evidence:
      - {source_id: source.pmph_human_parasitology_10e_2024, locator: "印刷页94–95【生活史】", evidence_type: direct_statement}
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Life Cycle", evidence_type: direct_statement}
    qualifiers: {source_atom_id: PCMS-025, route: oral_ingestion}
review: {extracted_by: pcms_formal_admission, reviewed_by: course_lead, last_reviewed: "2026-07-27"}
---

# 华支睾吸虫囊蚴

## 核心知识

囊蚴是华支睾吸虫对人的感染阶段。终宿主摄入适宜淡水鱼中的活囊蚴后，幼虫进入胆道并发育为成虫。

## One Health联系

囊蚴把淡水鱼宿主与人或其他终宿主的摄食暴露连接起来。

## 学习提示

“感染阶段”回答寄生虫以哪个阶段进入宿主；“主要致病阶段”回答进入宿主后哪个阶段主要造成损伤。

## 证据边界

本最低集不提供未单独核查的食品加工灭活参数。
