---
schema_version: "1.0"
id: parasite.clonorchis_sinensis
entity_type: parasite
name_zh: 华支睾吸虫
name_en: Chinese liver fluke
scientific_name: Clonorchis sinensis
aliases:
  - 肝吸虫
one_health_domains:
  - human_health
  - animal_health
  - environmental_health
summary: 华支睾吸虫是一种食源性吸虫；人摄入含活囊蚴的生或未充分加热淡水鱼可获得感染。
review_status: in_review
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-005
relations:
  - predicate: transmitted_via
    object: behavior.raw_undercooked_freshwater_fish_consumption
    statement_zh: 华支睾吸虫可因摄入含活囊蚴的生或未充分加热淡水鱼而感染人。
    relation_status: in_review
    evidence:
      - source_id: source.who_foodborne_trematode_fact_sheet
        locator: "Transmission and burden"
        evidence_type: direct_statement
      - source_id: source.cdc_dpdx_clonorchiasis_2024
        locator: "Life Cycle"
        evidence_type: direct_statement
    qualifiers:
      source_atom_id: W2-ATOM-005
      region: endemic_area
      condition: live_metacercariae_in_raw_or_undercooked_freshwater_fish
review:
  extracted_by: phase5_structuring
  reviewed_by: null
  last_reviewed: null
---

# 华支睾吸虫

## 核心知识

本批次仅准入华支睾吸虫经含活囊蚴的生或未充分加热淡水鱼获得感染这一传播关系。

## One Health联系

该传播关系连接水生动物来源的食物暴露与人类感染。动物宿主及环境传播环节将在后续批次独立审查。

## 学习提示

需要同时保留“淡水鱼”“活囊蚴”和“生或未充分加热”三个限定，不能泛化为所有水产品。

## 证据边界

本条关系不涉及淡水虾的宿主权重，也不提供具体加热、腌制或冷冻参数。
