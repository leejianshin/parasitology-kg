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
review_status: in_review
admission:
  batch_id: P5-B1
  source_ledger: candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml
  atom_ids:
    - W2-ATOM-009
relations:
  - predicate: occurs_in
    object: anatomy.biliary_system
    statement_zh: 华支睾吸虫感染相关病理改变主要发生于胆道系统。
    relation_status: in_review
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
  reviewed_by: null
  last_reviewed: null
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
