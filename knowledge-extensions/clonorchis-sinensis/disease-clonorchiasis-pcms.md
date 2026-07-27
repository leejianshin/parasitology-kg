---
schema_version: "1.0"
extension_id: extension.clonorchis_pcms_disease
extends_entity: disease.clonorchiasis
review_status: reviewed
admission:
  batch_id: P7-PCMS
  source_ledger: phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml
  atom_ids: [PCMS-028, PCMS-029, PCMS-030, PCMS-031, PCMS-032, PCMS-036]
relations:
  - predicate: diagnosed_by
    object: diagnostic.stool_egg_microscopy
    statement_zh: 粪便标本中检出华支睾吸虫卵可用于确证华支睾吸虫病。
    relation_status: reviewed
    evidence:
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Laboratory Diagnosis", evidence_type: direct_statement}
      - {source_id: source.who_community_diagnosis_clonorchiasis, locator: "Clonorchiasis，网页第88–91行", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-028
      role: parasitological_confirmation
  - predicate: diagnosed_by
    object: diagnostic.duodenal_fluid_egg_microscopy
    statement_zh: 在中国第10版教材及WS 309—2009语境下，十二指肠液中检出华支睾吸虫卵可作为病原学确证证据之一。
    relation_status: reviewed
    evidence:
      - {source_id: source.pmph_human_parasitology_10e_2024, locator: "印刷页96【实验诊断】", evidence_type: direct_statement}
      - {source_id: source.nhc_ws309_2009, locator: "诊断标准及附录；2016-12-28转为推荐性", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-029
      role: parasitological_confirmation
      jurisdiction: China
      routine_first_choice: false
      operational_note: complex_sampling
  - predicate: treated_by
    object: treatment.praziquantel
    statement_zh: WHO当前推荐吡喹酮治疗华支睾吸虫病。
    relation_status: reviewed
    evidence:
      - {source_id: source.who_community_diagnosis_clonorchiasis, locator: "Clonorchiasis，网页第92行", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-030
      authority: WHO
      recommendation_role: recommended
      as_of: "2026-07-27"
  - predicate: treated_by
    object: treatment.albendazole
    statement_zh: 美国CDC临床页面将阿苯达唑列为华支睾吸虫病的替代药物。
    relation_status: reviewed
    evidence:
      - {source_id: source.cdc_clinical_overview_clonorchis_2024, locator: "Treatment and recovery", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-031
      authority: US_CDC
      recommendation_role: alternative
      jurisdiction: US_clinical_reference
      as_of: "2026-07-27"
  - predicate: classified_as
    object: hazard.iarc_group_1_carcinogenic_to_humans
    statement_zh: IARC将华支睾吸虫感染列为1类致癌物，即Group 1致癌危害分类。
    relation_status: reviewed
    evidence:
      - {source_id: source.iarc_clonorchis_group1, locator: "Clonorchis sinensis (infection with), Group 1, Volumes 61 and 100B", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-032
      classified_agent: infection_with_clonorchis_sinensis
      hazard_not_individual_probability: true
      individual_cancer_certainty: false
  - predicate: controlled_by
    object: intervention.one_health_integrated_control
    statement_zh: WHO建议以连接人类、动物和环境的综合方法防控食源性吸虫病。
    relation_status: reviewed
    evidence:
      - {source_id: source.who_foodborne_trematode_fact_sheet, locator: "Treatment, prevention and control; One Health approach", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-036
      evidence_scope: recommendation_not_local_effect
      universal_elimination_claim: false
review: {reviewed_by: course_lead, last_reviewed: "2026-07-27", collaborative_review: chen_haiying_pending}
---

# 华支睾吸虫病 PCMS关系扩展

本扩展为既有`disease.clonorchiasis`增加确证方法、治疗地位、IARC危害分类和One Health综合防控关系。

## 证据边界

十二指肠液检卵不写成所有患者常规首选；阿苯达唑不写成WHO当前推荐；Group 1不写成个体必然患癌；综合防控建议不写成所有地区已经证实的消除效果；三苯双脒不在本批次。
