---
schema_version: "1.1"
id: host.domestic_dogs_cats_pigs
entity_type: host
name_zh: 家养犬、猫和猪
name_en: Domestic dogs, cats, and pigs
scientific_name: null
aliases: [犬猫猪]
one_health_domains: [animal_health, human_health, environmental_health]
summary: 感染的家养犬、猫和猪可作为华支睾吸虫保虫宿主，并可经粪便排出虫卵。
review_status: reviewed
admission:
  batch_id: P7-PCMS
  source_ledger: phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml
  atom_ids: [PCMS-024, PCMS-034]
relations:
  - predicate: sheds_stage
    object: stage.clonorchis_egg
    statement_zh: 感染的犬、猫和猪可经粪便排出华支睾吸虫卵。
    relation_status: reviewed
    evidence:
      - {source_id: source.who_clonorchiasis_qa_2025, locator: "Are pets or livestock at risk of spreading clonorchiasis?", evidence_type: direct_statement}
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Hosts; Life Cycle", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-034
      host_status: infected
      route: feces
review: {extracted_by: pcms_formal_admission, reviewed_by: course_lead, last_reviewed: "2026-07-27"}
---

# 家养犬、猫和猪

## 核心知识

犬、猫和猪可作为华支睾吸虫保虫宿主。感染动物可经粪便排出虫卵。

## One Health联系

动物保虫宿主及其粪便把动物健康、环境污染和人群暴露风险连接起来。

## 学习提示

保虫宿主关系说明其可维持自然传播，不表示每只犬、猫或猪均已感染。

## 证据边界

本最低集不提供特定地区动物感染率，也不把兽医措施写成已在所有地区证实有效。
