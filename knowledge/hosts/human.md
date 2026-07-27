---
schema_version: "1.1"
id: host.human
entity_type: host
name_zh: 人
name_en: Human
scientific_name: Homo sapiens
aliases: [人类]
one_health_domains: [human_health, environmental_health]
summary: 人可作为华支睾吸虫终宿主；感染者可经粪便排出虫卵。
review_status: reviewed
admission:
  batch_id: P7-PCMS
  source_ledger: phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml
  atom_ids: [PCMS-022, PCMS-033]
relations:
  - predicate: sheds_stage
    object: stage.clonorchis_egg
    statement_zh: 华支睾吸虫感染者可经粪便排出虫卵。
    relation_status: reviewed
    evidence:
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Life Cycle", evidence_type: direct_statement}
      - {source_id: source.who_clonorchiasis_qa_2025, locator: "网页第83–117行", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-033
      host_status: infected
      route: feces
review: {extracted_by: pcms_formal_admission, reviewed_by: course_lead, last_reviewed: "2026-07-27"}
---

# 人

## 核心知识

人可作为华支睾吸虫的终宿主。感染者可经粪便排出虫卵。

## One Health联系

感染者排出的虫卵在粪便进入淡水环境时连接人类感染与环境传播环节。

## 学习提示

终宿主角色与“感染阶段”不是同一概念：宿主是人，进入人体的阶段是囊蚴。

## 证据边界

排卵关系不表示所有感染者在任何一次标本检查中都能检出虫卵。
