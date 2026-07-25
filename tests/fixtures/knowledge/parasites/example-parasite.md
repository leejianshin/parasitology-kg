---
schema_version: "1.0"
id: parasite.example_parasite
entity_type: parasite
name_zh: 示例寄生虫
name_en: Example parasite
scientific_name: null
aliases: []
one_health_domains: [human_health, animal_health]
summary: 仅用于验证Schema的虚构寄生虫实体。
review_status: draft
relations:
  - predicate: infects
    object: host.example_host
    statement_zh: 示例寄生虫可以感染示例宿主。
    relation_status: draft
    evidence:
      - source_id: source.example
        locator: "fixture:1"
        evidence_type: direct_statement
    qualifiers: {}
review:
  extracted_by: validator_fixture
  reviewed_by: null
  last_reviewed: null
---

# 示例寄生虫

## 核心知识

本实体仅用于测试校验器。

## One Health联系

本实体不表达真实的One Health知识。

## 学习提示

本实体不是教学内容。

## 证据边界

本实体为虚构测试数据，不得进入正式知识库。
