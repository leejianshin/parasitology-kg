---
schema_version: "1.1"
id: stage.clonorchis_cercaria
entity_type: life_cycle_stage
name_zh: 华支睾吸虫尾蚴
name_en: Clonorchis sinensis cercaria
scientific_name: null
aliases: []
one_health_domains: [animal_health, environmental_health]
summary: 尾蚴离开适宜淡水螺后侵入淡水鱼，并在鱼体内形成囊蚴。
review_status: reviewed
admission:
  batch_id: P7-PCMS
  source_ledger: phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml
  atom_ids: [PCMS-018]
relations:
  - predicate: develops_into
    object: stage.clonorchis_metacercaria
    statement_zh: 华支睾吸虫尾蚴离开螺后侵入淡水鱼并形成囊蚴。
    relation_status: reviewed
    evidence:
      - {source_id: source.pmph_human_parasitology_10e_2024, locator: "印刷页94–95【生活史】", evidence_type: direct_statement}
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Life Cycle", evidence_type: direct_statement}
    qualifiers: {source_atom_id: PCMS-018, condition: within_freshwater_fish}
review: {extracted_by: pcms_formal_admission, reviewed_by: course_lead, last_reviewed: "2026-07-27"}
---

# 华支睾吸虫尾蚴

## 核心知识

尾蚴离开螺后侵入淡水鱼，并在鱼体内形成囊蚴。

## One Health联系

该阶段连接淡水螺和淡水鱼两个水生动物宿主环节。

## 学习提示

尾蚴不是本最低集中经口感染人的阶段；对人的感染阶段是囊蚴。

## 证据边界

本条不把所有淡水动物泛化为第二中间宿主。
