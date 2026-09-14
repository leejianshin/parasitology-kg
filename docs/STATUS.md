# 项目当前状态

```text
LAST_UPDATED=
2026-09-14

CURRENT_PUBLIC_DOCUMENTATION_HEAD=
RESOLVE_FROM_CURRENT_AGENT_P9_B2_BRANCH_HEAD

FROZEN_EVALUATION_SNAPSHOT_V1=
d77a76e6219482e1933e6377dfbad2151c829bef
```

`CURRENT_PUBLIC_DOCUMENTATION_HEAD`是当前`agent/p9-b2`分支的文档版本，应以
`git rev-parse HEAD`解析。它可以随仅文档提交前进。

`FROZEN_EVALUATION_SNAPSHOT_V1`是冻结系统的评估目标，固定为
`d77a76e6219482e1933e6377dfbad2151c829bef`。文档提交不得解释为新的系统版本；
今后所有P10评估均使用这一固定`SYSTEM_COMMIT`。

## 当前阶段

| 研究单元 | 当前状态 | 含义 |
|---|---|---|
| P9-A | `FROZEN` | 运行、证据、回答与审计合同已冻结 |
| P9-B1 / P9-B1Q | `FROZEN_RESEARCH_PROTOTYPE` | 检索与Scoped QueryIR组件已冻结为研究原型 |
| P9-B2 | `FROZEN_RESEARCH_PROTOTYPE` | 可信检索编排组件已冻结为研究原型 |
| P9工程 | `FROZEN` | 不再继续调优或重新开启既有验证 |
| P10 | `NOT_STARTED` | 尚未设计或执行P10基准测试 |
| P10授权 | `NOT_YET_AUTHORIZED` | 仅在公共文档收口通过后方可另行授权 |

当前研究阶段为`P9_PUBLIC_DOCUMENTATION_CLOSURE`。下一项合格工作是
`P10_SCIENTIFIC_EVALUATION_PROTOCOL`，前提是本次文档收口通过。

## 冻结状态与主张边界

- P9-B1Q和P9-B2均为冻结研究原型。
- D5状态为`CLOSED_NO_FURTHER_MAPPING_REQUIRED`。
- R10状态为`CONSUMED_FINAL`，不得重新开启。
- R11-V2只作为`HISTORICAL_FINAL_VALIDATION_EVIDENCE`，不得重新执行。
- POST-R10 S1修正已经实现、审计并发布。
- `FINAL_ENGINEERING_ACCEPTANCE=NOT_ESTABLISHED`。

“最终工程验收未建立”表示系统停留在冻结研究原型阶段，不表示项目失败。不得据此
声称生产就绪、临床可靠、已完成最终生产验证或已证明对全部寄生虫学可靠。

## 历史与归档状态

早期逐轮施工、秘密held-out测试、失败结果、R10/R11证据和POST-R10修正均保留为
`HISTORICAL ENGINEERING RECORD`或`HISTORICAL VALIDATION EVIDENCE`。这些材料不被
删除、重建或追溯性改写，也不因POST-R10修正而转化为最终工程验收。

主要入口：

- [Phase 9架构与历史工程记录](../phase9/clonorchis-sinensis/README.md)
- [冻结研究快照](../phase9/clonorchis-sinensis/RESEARCH-SNAPSHOT.md)
- [P9-B1Q设计、合同与历史验证记录](../phase9/clonorchis-sinensis/p9b1q/README.md)
- [P9-B1本地验收记录](../phase9/clonorchis-sinensis/p9b1-local-acceptance.yml)

历史证据只用于追溯，不得被重新解释为当前待办、待揭盲状态或新的系统评估。
