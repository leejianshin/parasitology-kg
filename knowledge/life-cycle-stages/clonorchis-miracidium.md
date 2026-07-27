---
schema_version: "1.1"
id: stage.clonorchis_miracidium
entity_type: life_cycle_stage
name_zh: 华支睾吸虫毛蚴
name_en: Clonorchis sinensis miracidium
scientific_name: null
aliases: []
one_health_domains: [animal_health]
summary: 毛蚴是华支睾吸虫在适宜淡水螺宿主体内继续发育的幼虫阶段。
review_status: reviewed
admission:
  batch_id: P7-PCMS
  source_ledger: phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml
  atom_ids: [PCMS-015]
relations:
  - predicate: develops_into
    object: stage.clonorchis_sporocyst
    statement_zh: 华支睾吸虫毛蚴在适宜螺宿主体内发育为胞蚴。
    relation_status: reviewed
    evidence:
      - {source_id: source.pmph_human_parasitology_10e_2024, locator: "印刷页94–95【生活史】", evidence_type: direct_statement}
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Life Cycle", evidence_type: direct_statement}
    qualifiers: {source_atom_id: PCMS-015, condition: within_suitable_snail_host}
review: {extracted_by: pcms_formal_admission, reviewed_by: course_lead, last_reviewed: "2026-07-27"}
---

# 华支睾吸虫毛蚴

## 核心知识

毛蚴在适宜淡水螺宿主体内继续发育为胞蚴。

## One Health联系

该阶段属于动物宿主体内的生活史环节。

## 学习提示

毛蚴不是本最低集中对人的感染阶段。

## 证据边界

本条只表达阶段顺序和螺宿主条件，不扩展未登记的时间或数量参数。
