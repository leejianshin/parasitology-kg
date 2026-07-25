---
schema_version: "1.0"
id: parasite.example_entity
entity_type: parasite
name_zh: 示例实体
name_en: Example entity
scientific_name: null
aliases: []
one_health_domains:
  - human_health
summary: 用一至三句话说明该实体的身份及其在人体寄生虫学中的位置。
review_status: draft
relations:
  - predicate: infects
    object: host.example_host
    statement_zh: 示例实体可以感染示例宿主。
    relation_status: draft
    evidence:
      - source_id: source.example
        locator: "示例页码或章节"
        evidence_type: direct_statement
    qualifiers: {}
review:
  extracted_by: null
  reviewed_by: null
  last_reviewed: null
---

# 示例实体

## 核心知识

使用完整、自足的句子说明该实体最重要的知识。不要依赖“它”“上述内容”等离开本段后无法理解的指代。

可以按实体需要增加三级标题，例如：

### 形态

### 生活史

### 致病与临床

### 诊断、治疗与防控

## One Health联系

说明该实体与人类健康、动物健康、环境健康或跨部门治理之间有来源支持的联系。区分传播机制、生态关联和治理措施，不把关联自动写成因果。

## 学习提示

记录适合学生理解的鉴别点、常见混淆和易错边界。没有学情或题库依据时，不得伪装成“学生普遍易错”，可以写成“需要区分”。

## 证据边界

说明现有来源能够证明什么、不能证明什么，以及是否存在版本差异、分类学变化或尚未解决的争议。
