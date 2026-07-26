# 华支睾吸虫 Phase 4 最终裁决与公开收口

状态：`ADJUDICATION_COMPLETE_ADMISSION_PREPARED`

裁决日期：2026-07-26

正式知识图谱写入：`NOT_AUTHORIZED`

## 结论

Phase 3 双路候选已经完成独立抽取、盲对照和教师裁决。Phase 4 将教师批准的
14 组修订命题拆为 28 条原子候选，并将 5 条外部证据按批准层级拆为 11 条
原子候选，合计 39 条。它们已完成来源映射、证据层级、限制条件和现有 Schema
适配评估，但仍只是准入准备材料，不是正式知识关系。

公开候选账本见
[`phase4-approved-admission-ledger.yml`](../../candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml)，
逐项 Schema 适配结论见
[`phase4-schema-fit-gap.yml`](phase4-schema-fit-gap.yml)。

## 裁决范围

| 项目 | 数量 | 处理结果 |
|---|---:|---|
| 教师批准修订组 | 14 | 拆为 28 条原子候选 |
| 外部证据组 | 5 | 按批准层级拆为 11 条原子候选 |
| 原子候选总数 | 39 | 全部为 `PREPARED_NOT_ADMITTED` |
| HOLD | 3 | 与候选物理隔离 |
| 教学、课程和题库元数据边界 | 10 | 零条转为医学事实 |
| 正式知识写入 | 0 | 未授权 |

## 三项 HOLD

1. `W2-CONFLICT-001`：受生鱼污染的厨具或手能否传播华支睾吸虫；
2. `W2-RB020-B`：胰管异位成虫与具体胰腺炎性病变之间的直接因果；
3. `W2-CONFLICT-002`：醋、酒及来源条件不一致的物种特异性灭活参数。

HOLD 只用于保留冲突和证据缺口，不得进入正式准入候选，也不得被改写为确定性
医学事实。

## 外部证据层级

- `W2-EXT-001`：公共卫生候选；
- `W2-EXT-002`：通用食品安全补充层，不作为华支睾吸虫物种专门灭活规则；
- `W2-EXT-003`：One Health 推荐候选，不外推固定措施组合的普遍效果；
- `W2-EXT-004`、`W2-EXT-005`：地区研究证据层，保留地区、时期、研究设计和结局限制。

## 元数据边界

教学表达、课程目标与题库考核内容只用于说明教学重点、课程边界和易错点。
本轮没有复制教材、课件或题库原文，也没有把这些材料转为医学事实。公开文件只
保留候选 ID、裁决类别和边界说明。

## 来源登记

本轮复用 3 个已登记公共来源：

- `source.who_foodborne_trematode_fact_sheet`；
- `source.cdc_dpdx_clonorchiasis_2024`；
- `source.cdc_clinical_overview_clonorchis_2024`。

新增 8 个公开来源元数据：WHO 华支睾吸虫问答、WHO 社区诊断建议、FAO/APFIC
区域研讨会报告，以及 5 篇同行评议研究或综述。来源登记只保存公开书目信息、
稳定 URL、定位和限制，不保存私有审查文件或受版权保护全文。

## Schema 适配

| 分类 | 数量 | 含义 |
|---|---:|---|
| `direct_relation_candidate` | 16 | 现有实体与关系类型可承载，仍需独立正式准入 |
| `qualifier_or_narrative` | 11 | 应作为限定或叙述，不单独建边 |
| `requires_schema_extension` | 5 | 需要独立 Schema PR |
| `supplemental_only` | 2 | 仅保留在通用食品安全补充层 |
| `research_layer_only` | 5 | 仅保留在带研究情境的证据层 |

本 PR 不修改 `schema/relation-types.yml`。拟议的诊断线索、病理发生部位、并发症
关联、非因果关联和情境化干预效果关系，必须在独立 PR 中评估后才能进入受控词表。

## 阶段门

- PR #4 已合并，Phase 3 已完成；
- Phase 4 已完成教师裁决和正式准入准备；
- Phase 5 尚未开始；
- 正式知识图谱写入仍未授权；
- `knowledge/` 在本次公开收口中保持零改动。
