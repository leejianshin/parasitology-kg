# 华支睾吸虫 Phase 6 RAG白名单语料包

> 本文件由正式`reviewed` Markdown确定性生成；原文件仍是权威主数据。

## 使用边界

- 只能依据本文件实际包含的内容回答；
- 未覆盖的问题应明确说明当前语料不足；
- 不得调用网页搜索、模型记忆或其他仓库文件补足缺口；
- 诊断线索、传播条件和防控建议不得扩大为确诊、必然感染或已证效果。

## 正式实体文档

---

## anatomy.biliary_system｜胆道系统

canonical_source_file: `knowledge/anatomy/biliary-system.md`

---
schema_version: "1.0"
id: anatomy.biliary_system
entity_type: anatomical_site
name_zh: 胆道系统
name_en: Biliary system
scientific_name: null
aliases: []
one_health_domains:
  - human_health
  - animal_health
summary: 胆道系统是华支睾吸虫感染相关病理改变的主要发生部位。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-009
relations: []
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 胆道系统

## 核心知识

该实体用于承载华支睾吸虫感染相关病理改变的解剖分布。

## One Health联系

胆道系统是连接寄生部位、病理过程与临床表现的共同解剖层。

## 学习提示

胆道系统是较宽的解剖概念，不应与“肝内小、中型胆管”混为同一粒度。

## 证据边界

本实体不自动继承具体病理改变或并发症。

---

## anatomy.intrahepatic_small_medium_bile_ducts｜肝内小、中型胆管

canonical_source_file: `knowledge/anatomy/intrahepatic-small-medium-bile-ducts.md`

---
schema_version: "1.0"
id: anatomy.intrahepatic_small_medium_bile_ducts
entity_type: anatomical_site
name_zh: 肝内小、中型胆管
name_en: Small and medium intrahepatic bile ducts
scientific_name: null
aliases: []
one_health_domains:
  - human_health
  - animal_health
summary: 肝内小、中型胆管是华支睾吸虫成虫的主要寄生部位。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-008
relations: []
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 肝内小、中型胆管

## 核心知识

该实体用于承载华支睾吸虫成虫主要寄生部位的解剖定位。

## One Health联系

同类胆道寄生部位可见于人及其他哺乳动物终宿主，但宿主范围须由独立关系表达。

## 学习提示

需要把解剖部位与病理过程分开建模。

## 证据边界

本实体本身不推断所有病变均局限于此，也不排除另行标注的异位情况。

---

## behavior.raw_undercooked_freshwater_fish_consumption｜生食或未充分加热淡水鱼

canonical_source_file: `knowledge/behaviors/raw-undercooked-freshwater-fish-consumption.md`

---
schema_version: "1.0"
id: behavior.raw_undercooked_freshwater_fish_consumption
entity_type: behavior
name_zh: 生食或未充分加热淡水鱼
name_en: Consumption of raw or undercooked freshwater fish
scientific_name: null
aliases:
  - 生食淡水鱼
one_health_domains:
  - human_health
  - animal_health
summary: 生食或未充分加热淡水鱼是一种与华支睾吸虫感染相关的食物暴露行为；传播成立还要求鱼体含有活囊蚴。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-001
    - W2-ATOM-005
relations: []
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 生食或未充分加热淡水鱼

## 核心知识

该实体表示可能使人摄入活囊蚴的食物暴露行为。

## One Health联系

这一行为连接淡水鱼中的寄生虫阶段与人类感染，是食源性传播链上的人类行为节点。

## 学习提示

不能把“淡水鱼”泛化为所有水产品，也不能忽略活囊蚴这一传播条件。

## 证据边界

本实体不表达所有生食者都会感染，也不表达淡水鱼与淡水虾具有相同证据权重。

---

## diagnostic.biliary_imaging｜胆道影像学检查

canonical_source_file: `knowledge/diagnostics/biliary-imaging.md`

---
schema_version: "1.0"
id: diagnostic.biliary_imaging
entity_type: diagnostic_method
name_zh: 胆道影像学检查
name_en: Biliary imaging
scientific_name: null
aliases:
  - 超声、CT或MRI
one_health_domains:
  - human_health
summary: 超声、CT或MRI可提供华支睾吸虫病的辅助诊断线索，但不能单独确诊。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-023
    - W2-ATOM-024
    - W2-ATOM-025
relations: []
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 胆道影像学检查

## 核心知识

超声、CT或MRI表现可作为华支睾吸虫病的辅助诊断线索。

## One Health联系

影像学属于人类临床诊断环节，不直接证明动物或环境传播状态。

## 学习提示

影像学线索应结合暴露史、临床和实验室证据综合判断。

## 证据边界

现有权威来源未给出各影像表现的特异度；影像不能单独确诊华支睾吸虫病。

---

## disease.clonorchiasis｜华支睾吸虫病

canonical_source_file: `knowledge/diseases/clonorchiasis.md`

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
review_status: reviewed
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
    relation_status: reviewed
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
    relation_status: reviewed
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
    relation_status: reviewed
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
    relation_status: reviewed
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
    relation_status: reviewed
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
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
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

---

## environment.freshwater_environment｜淡水环境

canonical_source_file: `knowledge/environments/freshwater-environment.md`

---
schema_version: "1.0"
id: environment.freshwater_environment
entity_type: environment
name_zh: 淡水环境
name_en: Freshwater environment
scientific_name: null
aliases:
  - 淡水水体
one_health_domains:
  - animal_health
  - environmental_health
summary: 淡水环境是华支睾吸虫虫卵接触中间宿主的传播环境，也是人和动物粪便污染干预的直接对象。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-027
    - W2-ATOM-028
relations: []
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 淡水环境

## 核心知识

该实体表示华支睾吸虫虫卵进入中间宿主水域所涉及的淡水传播环境。

## One Health联系

淡水环境承接人和动物粪便管理，并连接水生中间宿主，是One Health传播链的环境节点。

## 学习提示

环境节点只描述传播条件或干预对象，不能自动推出某地区存在流行。

## 证据边界

本实体未细分水体类型、地区、污染浓度或环境监测阈值。

---

## intervention.avoid_raw_undercooked_freshwater_fish｜避免食用生或未充分加热淡水鱼

canonical_source_file: `knowledge/interventions/avoid-raw-undercooked-freshwater-fish.md`

---
schema_version: "1.0"
id: intervention.avoid_raw_undercooked_freshwater_fish
entity_type: intervention
name_zh: 避免食用生或未充分加热淡水鱼
name_en: Avoid raw or undercooked freshwater fish
scientific_name: null
aliases: []
one_health_domains:
  - human_health
  - cross_sector_governance
summary: 避免食用生或未充分加热淡水鱼是预防华支睾吸虫感染的推荐措施。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-006
relations: []
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 避免食用生或未充分加热淡水鱼

## 核心知识

该干预直接针对人类的高风险食物暴露行为。

## One Health联系

该措施位于动物源性食品与人类健康的交界，但不替代环境卫生及传染源管理。

## 学习提示

“推荐措施”不等于已经量化其独立效果，更不等于单一措施可以消除传播。

## 证据边界

本实体未收录具体烹调温度、冷冻组合或腌制参数。

---

## intervention.improved_sanitation｜改善卫生设施

canonical_source_file: `knowledge/interventions/improved-sanitation.md`

---
schema_version: "1.0"
id: intervention.improved_sanitation
entity_type: intervention
name_zh: 改善卫生设施
name_en: Improved sanitation
scientific_name: null
aliases: []
one_health_domains:
  - human_health
  - animal_health
  - environmental_health
  - cross_sector_governance
summary: 改善卫生设施是减少粪便污染淡水环境、参与华支睾吸虫病防控的推荐措施。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-026
relations: []
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 改善卫生设施

## 核心知识

该干预用于减少人和动物粪便污染淡水环境的机会。

## One Health联系

卫生设施连接人类健康、动物健康、环境健康与治理，是跨部门防控环节。

## 学习提示

该措施是推荐方向，不应写成已证明在所有地区具有相同效果。

## 证据边界

本批次未给出设施类型、覆盖率、成本效益或独立干预效果。

---

## intervention.reduce_animal_fecal_contamination｜减少动物粪便污染淡水环境

canonical_source_file: `knowledge/interventions/reduce-animal-fecal-contamination.md`

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

---

## intervention.reduce_human_fecal_contamination｜减少人粪便污染淡水环境

canonical_source_file: `knowledge/interventions/reduce-human-fecal-contamination.md`

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

---

## manifestation.asymptomatic_light_infection｜轻虫负荷感染无明显症状

canonical_source_file: `knowledge/manifestations/asymptomatic-light-infection.md`

---
schema_version: "1.0"
id: manifestation.asymptomatic_light_infection
entity_type: clinical_manifestation
name_zh: 轻虫负荷感染无明显症状
name_en: No obvious symptoms in light infection
scientific_name: null
aliases:
  - 轻度感染无明显症状
one_health_domains:
  - human_health
summary: 华支睾吸虫轻虫负荷感染多数可无明显症状；这一频率判断不等于感染或病理改变不存在。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-022
relations: []
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 轻虫负荷感染无明显症状

## 核心知识

该实体表示轻虫负荷情境下多数感染者可无明显症状。

## One Health联系

无明显症状者仍可能处于传播系统中，因此临床感受不能替代病原学和公共卫生判断。

## 学习提示

需要保留“轻虫负荷”和“多数”两个限定，不能改写为所有感染均无症状。

## 证据边界

无明显症状不等于无病理改变，也不排除持续排卵。

---

## parasite.clonorchis_sinensis｜华支睾吸虫

canonical_source_file: `knowledge/parasites/clonorchis-sinensis.md`

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
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-005
relations:
  - predicate: transmitted_via
    object: behavior.raw_undercooked_freshwater_fish_consumption
    statement_zh: 华支睾吸虫可因摄入含活囊蚴的生或未充分加热淡水鱼而感染人。
    relation_status: reviewed
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
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
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

---

## pathology.clonorchis_related_biliary_pathology｜华支睾吸虫感染相关胆道病理改变

canonical_source_file: `knowledge/pathology/clonorchis-related-biliary-pathology.md`

---
schema_version: "1.0"
id: pathology.clonorchis_related_biliary_pathology
entity_type: pathological_process
name_zh: 华支睾吸虫感染相关胆道病理改变
name_en: Clonorchis-associated biliary pathological changes
scientific_name: null
aliases: []
one_health_domains:
  - human_health
  - animal_health
summary: 华支睾吸虫感染相关病理改变主要发生于胆道系统。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-009
relations:
  - predicate: occurs_in
    object: anatomy.biliary_system
    statement_zh: 华支睾吸虫感染相关病理改变主要发生于胆道系统。
    relation_status: reviewed
    evidence:
      - source_id: source.cdc_dpdx_clonorchiasis_2024
        locator: "Clinical Presentation"
        evidence_type: direct_statement
      - source_id: source.hong_kim_clonorchis_cholangiocarcinoma_review_2016
        locator: "PATHOGENESIS AND CARCINOGENESIS"
        evidence_type: direct_statement
    qualifiers:
      source_atom_id: W2-ATOM-009
      distribution: mainly
      ectopic_exclusion: false
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 华支睾吸虫感染相关胆道病理改变

## 核心知识

本批次只建立病理改变与胆道系统之间的主要发生部位关系。

## One Health联系

该病理节点可用于比较人和动物终宿主的胆道损伤，但本批次不作跨宿主外推。

## 学习提示

“病理改变主要发生于胆道系统”与“成虫主要寄生于肝内小、中型胆管”是两个不同判断。

## 证据边界

具体炎症、纤维化、并发症及其因果强度留待后续批次审查。

---

## stage.clonorchis_adult｜华支睾吸虫成虫

canonical_source_file: `knowledge/life-cycle-stages/clonorchis-adult.md`

---
schema_version: "1.0"
id: stage.clonorchis_adult
entity_type: life_cycle_stage
name_zh: 华支睾吸虫成虫
name_en: Adult Clonorchis sinensis
scientific_name: null
aliases: []
one_health_domains:
  - human_health
  - animal_health
summary: 华支睾吸虫成虫是其生活史中的成体阶段，主要寄生于肝内小、中型胆管。
review_status: reviewed
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-008
relations:
  - predicate: parasitizes_site
    object: anatomy.intrahepatic_small_medium_bile_ducts
    statement_zh: 华支睾吸虫成虫主要寄生于肝内小、中型胆管。
    relation_status: reviewed
    evidence:
      - source_id: source.cdc_dpdx_clonorchiasis_2024
        locator: "Life Cycle"
        evidence_type: direct_statement
      - source_id: source.hong_kim_clonorchis_cholangiocarcinoma_review_2016
        locator: "PATHOGENESIS AND CARCINOGENESIS"
        evidence_type: direct_statement
    qualifiers:
      source_atom_id: W2-ATOM-008
      distribution: mainly
review:
  extracted_by: phase5_structuring
  reviewed_by: subject_teacher
  last_reviewed: "2026-07-26"
---

# 华支睾吸虫成虫

## 核心知识

本批次仅收录成虫的主要寄生部位。

## One Health联系

该部位关系适用于人类及相应哺乳动物终宿主体内的成虫阶段，但本批次未建立宿主角色边。

## 学习提示

“主要寄生于”是分布限定，不应写成排除所有异位情况的绝对判断。

## 证据边界

“次级胆管”暂保留为教学表达，本条采用公开权威来源支持的“肝内小、中型胆管”。
