---
schema_version: "1.1"
id: stage.clonorchis_egg
entity_type: life_cycle_stage
name_zh: 华支睾吸虫虫卵
name_en: Clonorchis sinensis egg
scientific_name: null
aliases: []
one_health_domains: [human_health, animal_health, environmental_health]
summary: 华支睾吸虫虫卵是可由感染终宿主排出、进入淡水生活史并用于病原学诊断的阶段。
review_status: reviewed
admission:
  batch_id: P7-PCMS
  source_ledger: phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml
  atom_ids: [PCMS-003, PCMS-004, PCMS-005, PCMS-006, PCMS-014, PCMS-027, PCMS-035]
relations:
  - predicate: develops_into
    object: stage.clonorchis_miracidium
    statement_zh: 华支睾吸虫虫卵被适宜螺宿主摄入后释放毛蚴。
    relation_status: reviewed
    evidence:
      - {source_id: source.pmph_human_parasitology_10e_2024, locator: "印刷页94–95【生活史】", evidence_type: direct_statement}
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Life Cycle", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-014
      condition: within_suitable_snail_host
  - predicate: diagnostic_stage_for
    object: host.human
    statement_zh: 华支睾吸虫虫卵是人慢性期病原学检查的诊断阶段。
    relation_status: reviewed
    evidence:
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Laboratory Diagnosis", evidence_type: direct_statement}
      - {source_id: source.who_community_diagnosis_clonorchiasis, locator: "Clonorchiasis，网页第88–91行", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-027
      host_phase: chronic
  - predicate: present_in_environment
    object: environment.freshwater_environment
    statement_zh: 随感染宿主粪便进入淡水环境的华支睾吸虫卵可进入其生活史。
    relation_status: reviewed
    evidence:
      - {source_id: source.cdc_dpdx_clonorchiasis_2024, locator: "Life Cycle", evidence_type: direct_statement}
      - {source_id: source.who_clonorchiasis_qa_2025, locator: "Are pets or livestock at risk of spreading clonorchiasis?", evidence_type: direct_statement}
    qualifiers:
      source_atom_id: PCMS-035
      condition: fecal_entry_into_freshwater
      direct_human_infectivity: false
review:
  extracted_by: pcms_formal_admission
  reviewed_by: course_lead
  last_reviewed: "2026-07-27"
---

# 华支睾吸虫虫卵

## 核心知识

### 形态

- `PCMS-003`：教学正文采用第10版教材的约`27–35 μm × 12–20 μm`；CDC形态页的宽度口径为`11–20 μm`，两者按来源分别保留。
- `PCMS-004`：虫卵较窄端有卵盖，卵盖周围可见肩峰样结构。
- `PCMS-005`：无盖端常可见小疣或小突起。
- `PCMS-006`：排出的虫卵内可见已发育的毛蚴。

虫卵可用于病原学诊断；进入淡水后仍须经适宜螺宿主等生活史环节，不能直接感染人。

## One Health联系

虫卵把感染的人或动物宿主与淡水环境连接起来，是人—动物—环境传播机制中的环境输入阶段。

## 学习提示

需要区分“环境中存在的虫卵”和“对人有感染性的囊蚴”。两者不能互换。

## 证据边界

“人体蠕虫卵中最小”没有作为跨物种绝对排序写入本最低集。虫卵与后睾吸虫属虫卵形态相近，显微镜下物种鉴别存在局限。
