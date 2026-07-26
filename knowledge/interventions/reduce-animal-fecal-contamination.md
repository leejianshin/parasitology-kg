---
schema_version: "1.0"
id: intervention.reduce_animal_fecal_contamination
entity_type: intervention
name_zh: 减少动物粪便污染淡水环境
name_en: Reduce animal fecal contamination of freshwater
scientific_name: null
aliases: []
one_health_domains:
  - animal_health
  - environmental_health
  - cross_sector_governance
summary: 减少动物粪便污染淡水环境可针对虫卵进入中间宿主水域的传播环节。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-028
relations:
  - predicate: targets
    object: environment.freshwater_environment
    statement_zh: 减少动物粪便污染淡水环境可针对虫卵进入中间宿主水域的传播环节。
    relation_status: reviewed
    evidence:
      - source_id: source.who_clonorchiasis_qa_2025
        locator: "Are pets or livestock at risk of spreading clonorchiasis?，网页第94–96行"
        evidence_type: supported_inference
      - source_id: source.who_foodborne_trematode_fact_sheet
        locator: "One Health approach"
        evidence_type: supported_inference
    qualifiers:
      source_atom_id: W2-ATOM-028
      mechanism: interrupt_egg_entry_to_intermediate_host_waters
      evidence_scope: mechanism_and_recommendation
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 减少动物粪便污染淡水环境

## 核心知识

该干预针对动物源虫卵进入淡水传播环境的环节。

## One Health联系

该关系连接动物宿主管理与淡水环境治理，是本批次明确的动物—环境接口。

## 学习提示

动物来源需要与人来源分开建模，不能用笼统“粪便管理”掩盖作用对象。

## 证据边界

本条是机制与推荐层表达，不提供特定动物种类、设施方案或量化效果。
