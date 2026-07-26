---
schema_version: "1.0"
id: disease.clonorchiasis
entity_type: disease
name_zh: 华支睾吸虫病
name_en: Clonorchiasis
scientific_name: null
aliases:
  - 肝吸虫病
one_health_domains:
  - human_health
  - environmental_health
  - cross_sector_governance
summary: 华支睾吸虫病是华支睾吸虫感染所致疾病；本批次收录其暴露史和影像学线索、轻虫负荷时的临床频率边界及基础防控措施。
review_status: in_review
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-001
    - W2-ATOM-006
    - W2-ATOM-022
    - W2-ATOM-023
    - W2-ATOM-026
relations:
  - predicate: has_diagnostic_clue
    object: behavior.raw_undercooked_freshwater_fish_consumption
    statement_zh: 在流行地区，生食或未充分加热淡水鱼的经历可作为华支睾吸虫病的流行病学线索。
    relation_status: in_review
    evidence:
      - source_id: source.who_community_diagnosis_clonorchiasis
        locator: "Clonorchiasis，网页第82–94行"
        evidence_type: direct_statement
      - source_id: source.cdc_dpdx_clonorchiasis_2024
        locator: "Clinical Presentation"
        evidence_type: direct_statement
    qualifiers:
      source_atom_id: W2-ATOM-001
      region: endemic_area
      role: epidemiological_clue
      confirmation_status: not_confirmatory
  - predicate: controlled_by
    object: intervention.avoid_raw_undercooked_freshwater_fish
    statement_zh: 避免食用生或未充分加热的淡水鱼是预防华支睾吸虫感染的推荐措施。
    relation_status: in_review
    evidence:
      - source_id: source.who_clonorchiasis_qa_2025
        locator: "How can clonorchiasis be prevented?，网页第116–117行"
        evidence_type: direct_statement
      - source_id: source.cdc_clinical_overview_clonorchis_2024
        locator: "Prevention"
        evidence_type: direct_statement
    qualifiers:
      source_atom_id: W2-ATOM-006
      evidence_scope: recommendation_not_quantified_effect
  - predicate: manifests_as
    object: manifestation.asymptomatic_light_infection
    statement_zh: 华支睾吸虫轻虫负荷感染多数可无明显症状。
    relation_status: in_review
    evidence:
      - source_id: source.who_foodborne_trematode_fact_sheet
        locator: "Symptoms"
        evidence_type: direct_statement
      - source_id: source.cdc_dpdx_clonorchiasis_2024
        locator: "Clinical Presentation"
        evidence_type: direct_statement
    qualifiers:
      source_atom_id: W2-ATOM-022
      worm_burden: light
      frequency: most
  - predicate: has_diagnostic_clue
    object: diagnostic.biliary_imaging
    statement_zh: 超声、CT或MRI表现可作为华支睾吸虫病的辅助诊断线索。
    relation_status: in_review
    evidence:
      - source_id: source.who_foodborne_trematode_fact_sheet
        locator: "Diagnosis"
        evidence_type: direct_statement
      - source_id: source.cdc_clinical_overview_clonorchis_2024
        locator: "Diagnosis"
        evidence_type: direct_statement
    qualifiers:
      source_atom_id: W2-ATOM-023
      role: auxiliary
      confirmation_limit: cannot_confirm_alone
      supporting_narrative_atom_ids:
        - W2-ATOM-024
        - W2-ATOM-025
  - predicate: controlled_by
    object: intervention.improved_sanitation
    statement_zh: 改善卫生设施是减少粪便污染淡水环境的推荐防控措施。
    relation_status: in_review
    evidence:
      - source_id: source.who_clonorchiasis_qa_2025
        locator: "How can clonorchiasis be prevented?，网页第116–117行"
        evidence_type: direct_statement
      - source_id: source.who_foodborne_trematode_fact_sheet
        locator: "Treatment, prevention and control"
        evidence_type: direct_statement
    qualifiers:
      source_atom_id: W2-ATOM-026
      evidence_scope: recommendation_not_quantified_effect
review:
  extracted_by: phase5_structuring
  reviewed_by: null
  last_reviewed: null
---

# 华支睾吸虫病

## 核心知识

本批次收录两类诊断线索、轻虫负荷感染的临床频率边界，以及两项基础防控建议。暴露史与影像学均不能单独承担确诊含义。

## One Health联系

避免高风险食物暴露作用于人类行为，改善卫生设施作用于人和动物粪便进入淡水环境的传播环节。

## 学习提示

需要区分“诊断线索”和“确诊证据”。无明显症状也不等于没有感染或没有病理改变。

## 证据边界

本批次没有准入并发症因果、胆石形成机制、治疗方案或地区干预效果。影像学线索须结合暴露史、临床和实验室证据综合判断。
