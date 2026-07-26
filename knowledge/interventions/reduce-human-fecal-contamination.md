---
schema_version: "1.0"
id: intervention.reduce_human_fecal_contamination
entity_type: intervention
name_zh: 减少人粪便污染淡水环境
name_en: Reduce human fecal contamination of freshwater
scientific_name: null
aliases: []
one_health_domains:
  - human_health
  - environmental_health
  - cross_sector_governance
summary: 减少人粪便污染淡水环境可针对虫卵进入中间宿主水域的传播环节。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-027
relations:
  - predicate: targets
    object: environment.freshwater_environment
    statement_zh: 减少人粪便污染淡水环境可针对虫卵进入中间宿主水域的传播环节。
    relation_status: reviewed
    evidence:
      - source_id: source.who_clonorchiasis_qa_2025
        locator: "How can clonorchiasis be prevented?，网页第116–117行"
        evidence_type: supported_inference
      - source_id: source.who_foodborne_trematode_fact_sheet
        locator: "One Health approach"
        evidence_type: supported_inference
    qualifiers:
      source_atom_id: W2-ATOM-027
      mechanism: interrupt_egg_entry_to_intermediate_host_waters
      evidence_scope: mechanism_and_recommendation
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 减少人粪便污染淡水环境

## 核心知识

该干预针对人源虫卵进入淡水传播环境的环节。

## One Health联系

该关系把人类排泄物管理与淡水生态传播条件连接起来。

## 学习提示

“针对传播环节”不等于已经量化感染率下降。

## 证据边界

本条是机制与推荐层表达，不声称其单独干预效果或适用于固定措施组合。
