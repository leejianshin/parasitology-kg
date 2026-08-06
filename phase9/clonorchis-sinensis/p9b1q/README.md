# P9-B1Q：Scoped QueryIR设计原子

本目录只冻结P9-B1查询解释层的候选设计，不实现解析器、模型调用、检索改造、
响应生成或学生发布。

## 状态与基线

- 设计状态：`DESIGN_CANDIDATE_PENDING_INDEPENDENT_READ_ONLY_REVIEW`
- 实现基线：`accf29d144412b5634de17b77c53f153b8ac7f7d`
- 架构裁决：`ADAPT_EXECUTOR_REPLACE_QUERY_INTERPRETATION_LAYER`
- P9-A合同：保持冻结，不作修改
- P9-B2：未启动
- 模型调用、网络调用、推送和Pull Request：均未授权

R9独立盲测在该实现基线上取得Top12必需主张召回`24/24`，但完整QueryPlan仅
`9/24`。因此本设计停止继续增加词面规则，改为先冻结“原始查询如何被解释为带
作用域结构”的接口，再由确定性图执行器处理正式实体和关系。

## 本原子交付

1. `query-ir-schema-candidate.yml`：Scoped QueryIR的JSON Schema候选；
2. `query-ir-semantic-contract.yml`：分句、span、否定、极性、时间和关系激活语义；
3. `request-queryir-retrieval-audit-binding.yml`：实际对象与哈希的端到端绑定规则；
4. `ambiguity-fail-closed-rules.yml`：歧义分类及关闭式失败规则；
5. `r9-failure-coverage-matrix.yml`：R9聚合失败类型到新设计字段和验收断言的映射；
6. `r10-blind-test-design-contract.yml`：下一轮真正held-out的预冻结与验收合同。

## 核心边界

- QueryIR不得包含、预测或选择`claim_id`、来源、定位或最终答案；
- 每个语义对象必须回绑原始`query_text`的精确Unicode字符span；
- 正式实体、实体类型和关系谓词只能来自冻结本体；
- 标本代码只是查询解释词汇，不新增知识图谱实体或医学事实；
- `NEGATED`、`EXCLUDED`、`HYPOTHETICAL`不得激活肯定关系；
- 未解决的方法—标本—极性、否定、时间、指代或关系方向歧义必须停止检索；
- 检索候选只有获得`AFFIRMED`意图或合同允许的显式对照规则许可，才可进入后续
  material claim阶段；
- 本目录的候选设计通过独立只读复审之前，不得选择或实现Query Interpreter路线。

## 与P9-A的兼容方式

现有P9-A请求、响应和审计Schema不增加字段。本设计以私有绑定旁证记录串联
`request_sha256`、`query_ir_sha256`、`retrieval_result_sha256`和现有`audit_id`。
QueryIR歧义在当前合同下只能映射为`ABSTAIN + NO_SAFE_ADMITTED_ANSWER`；若未来希望
增加新的学生端状态或P9-A原因码，必须另行授权修改P9-A，不能在P9-B1Q中静默加入。
