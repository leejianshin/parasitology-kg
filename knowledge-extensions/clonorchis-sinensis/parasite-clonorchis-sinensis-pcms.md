---
schema_version: "1.0"
extension_id: extension.clonorchis_pcms_parasite
extends_entity: parasite.clonorchis_sinensis
review_status: reviewed
admission:
  batch_id: P7-PCMS
  source_ledger: phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml
  atom_ids: [PCMS-007, PCMS-008, PCMS-009, PCMS-010, PCMS-011, PCMS-012, PCMS-013, PCMS-020, PCMS-021, PCMS-022, PCMS-023, PCMS-024]
relations:
  - predicate: has_life_cycle_stage
    object: stage.clonorchis_egg
    statement_zh: 华支睾吸虫具有虫卵阶段。
    relation_status: reviewed
    evidence: &life_cycle_evidence
      - {source_id: source.pmph_human_parasitology_10e_2024, locator: "印刷页94–95【生活史】", evidence_type: direct_statement}
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Life Cycle", evidence_type: direct_statement}
    qualifiers: {source_atom_id: PCMS-007}
  - predicate: has_life_cycle_stage
    object: stage.clonorchis_miracidium
    statement_zh: 华支睾吸虫具有毛蚴阶段。
    relation_status: reviewed
    evidence: *life_cycle_evidence
    qualifiers: {source_atom_id: PCMS-008}
  - predicate: has_life_cycle_stage
    object: stage.clonorchis_sporocyst
    statement_zh: 华支睾吸虫具有胞蚴阶段。
    relation_status: reviewed
    evidence: *life_cycle_evidence
    qualifiers: {source_atom_id: PCMS-009}
  - predicate: has_life_cycle_stage
    object: stage.clonorchis_redia
    statement_zh: 华支睾吸虫具有雷蚴阶段。
    relation_status: reviewed
    evidence: *life_cycle_evidence
    qualifiers: {source_atom_id: PCMS-010}
  - predicate: has_life_cycle_stage
    object: stage.clonorchis_cercaria
    statement_zh: 华支睾吸虫具有尾蚴阶段。
    relation_status: reviewed
    evidence: *life_cycle_evidence
    qualifiers: {source_atom_id: PCMS-011}
  - predicate: has_life_cycle_stage
    object: stage.clonorchis_metacercaria
    statement_zh: 华支睾吸虫具有囊蚴阶段。
    relation_status: reviewed
    evidence: *life_cycle_evidence
    qualifiers: {source_atom_id: PCMS-012}
  - predicate: has_life_cycle_stage
    object: stage.clonorchis_adult
    statement_zh: 华支睾吸虫具有成虫阶段。
    relation_status: reviewed
    evidence: *life_cycle_evidence
    qualifiers: {source_atom_id: PCMS-013}
  - predicate: has_first_intermediate_host
    object: host.freshwater_snails_suitable_for_clonorchis
    statement_zh: 适宜淡水螺类是华支睾吸虫的第一中间宿主。
    relation_status: reviewed
    evidence:
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Hosts", evidence_type: direct_statement}
    qualifiers: {source_atom_id: PCMS-020, suitability_required: true}
  - predicate: has_second_intermediate_host
    object: host.freshwater_fish
    statement_zh: 淡水鱼是华支睾吸虫的第二中间宿主，许多已知宿主属于鲤科。
    relation_status: reviewed
    evidence:
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Hosts", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-021
      common_family: Cyprinidae
      freshwater_shrimp_equal_weight: false
  - predicate: has_definitive_host
    object: host.human
    statement_zh: 人是华支睾吸虫的终宿主。
    relation_status: reviewed
    evidence:
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Hosts", evidence_type: direct_statement}
    qualifiers: {source_atom_id: PCMS-022}
  - predicate: has_definitive_host
    object: host.piscivorous_mammals
    statement_zh: 犬科、猫科、猪、鼬科及其他食鱼哺乳动物可作为华支睾吸虫终宿主。
    relation_status: reviewed
    evidence:
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Hosts", evidence_type: direct_statement}
    qualifiers: {source_atom_id: PCMS-023, host_class_scope: piscivorous_mammals}
  - predicate: has_reservoir_host
    object: host.domestic_dogs_cats_pigs
    statement_zh: 犬、猫和猪可作为华支睾吸虫保虫宿主。
    relation_status: reviewed
    evidence:
      - {source_id: source.who_clonorchiasis_qa_2025, locator: "Are pets or livestock at risk of spreading clonorchiasis?", evidence_type: direct_statement}
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Hosts", evidence_type: direct_statement}
    qualifiers: {source_atom_id: PCMS-024}
review: {reviewed_by: course_lead, last_reviewed: "2026-07-27", collaborative_review: chen_haiying_pending}
---

# 华支睾吸虫 PCMS关系扩展

本扩展为既有`parasite.clonorchis_sinensis`增加生活史阶段和宿主角色。它不改写Phase 5冻结实体，也不创建第二个华支睾吸虫实体。

## 证据边界

淡水鱼与淡水虾不等权处理；部分中国淡水虾种的次要、地区限定宿主关系不进入本最低集。
