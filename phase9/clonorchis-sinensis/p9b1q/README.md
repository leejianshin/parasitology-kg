# P9-B1Q：Scoped QueryIR设计与本地实现

本目录冻结P9-B1查询解释层设计；本地确定性参考实现位于
`scripts/p9b1q_scoped_query_ir.py`，公开回归位于
`tests/test_p9b1q_scoped_query_ir.py`。不调用模型、网络或学生数据。

## 状态与基线

- 设计状态：`DESIGN_CANDIDATE_INDEPENDENT_REVIEW_PASS`
- 实现状态：`LOCAL_IMPLEMENTATION_PENDING_R10_BLIND_REVIEW`
- 实现基线：`accf29d144412b5634de17b77c53f153b8ac7f7d`
- 架构裁决：`ADAPT_EXECUTOR_REPLACE_QUERY_INTERPRETATION_LAYER`
- P9-A合同：保持冻结，不作修改
- P9-B2：未启动
- R10秘密套件：已由独立上下文预冻结并以公开承诺提交锁定；实现方不可读
- 模型调用、网络调用、推送和Pull Request：均未发生

R9独立盲测在该实现基线上取得Top12必需主张召回`24/24`，但完整QueryPlan仅
`9/24`。因此本设计停止继续增加词面规则，改为先冻结“原始查询如何被解释为带
作用域结构”的接口，再由确定性图执行器处理正式实体和关系。

## 本原子交付

1. `query-ir-schema-candidate.yml`：Scoped QueryIR的JSON Schema候选；
2. `query-ir-semantic-contract.yml`：分句、span、否定、极性、时间和关系激活语义；
3. `query-ir-semantic-validator-contract.yml`：跨字段、跨对象语义校验顺序与失败码；
4. `semantic-validation-result-schema-candidate.yml`：可执行的语义校验结果Schema；
5. `event-predicate-type-role-mapping.yml`：完整事件—谓词—方向—实体类型—角色映射；
6. `execution-binding-sidecar-schema-candidate.yml`：私有端到端绑定旁证Schema候选；
7. `request-queryir-retrieval-audit-binding.yml`：实际对象与组件产物的绑定规则；
8. `ambiguity-fail-closed-rules.yml`：歧义分类及关闭式失败规则；
9. `r9-failure-coverage-matrix.yml`：R9聚合失败类型到新设计字段和验收断言的映射；
10. `r10-blind-test-design-contract.yml`：下一轮真正held-out的预冻结与验收合同。
11. `query-interpreter-config.yml`：正式实体别名及通用语义解析配置；
12. `scripts/p9b1q_scoped_query_ir.py`：解释、语义校验、图执行、P9-A响应/审计及
    内容寻址sidecar绑定的确定性本地实现；
13. `tests/test_p9b1q_scoped_query_ir.py`：公开语义与端到端篡改负向回归。

## 核心边界

- QueryIR不得包含、预测或选择`claim_id`、来源、定位或最终答案；
- 每个语义对象必须回绑原始`query_text`的精确Unicode字符span；
- 正式实体、实体类型和关系谓词只能来自冻结本体；
- 标本代码只是查询解释词汇，不新增知识图谱实体或医学事实；
- `NEGATED`、`EXCLUDED`、`HYPOTHETICAL`不得激活肯定关系；
- 未解决的方法—标本—极性、否定、时间、指代或关系方向歧义必须停止检索；
- 语义依赖固定为有根、分层、无环图；角色和事件不能直接许可医学主张；
- `EVENT_DERIVED`关系和叙事意图只能从对应事件映射、参与实体及共享根确定性派生；
- 关系候选必须匹配正式定向的`AFFIRMED`关系意图；无谓词叙述候选必须匹配受控
  叙述意图及其必要锚定关系，才可进入后续material claim阶段；
- OR歧义必须以`ALT组+具体分支句`完整列出全部候选；OR、CONDITION、
  HYPOTHETICAL及未解决同指不得被静默物化为肯定事实；
- R10结果公布前不得依据秘密题目修改实现；失败套件揭盲后只能降级为公开回归。

## 与P9-A的兼容方式

现有P9-A请求、响应和审计Schema不增加字段。本设计以可执行私有sidecar Schema和
内容寻址对象串联实际请求、QueryIR、语义校验、检索结果、响应及审计，并绑定解释器、
语义校验器和图执行器的可执行产物、构建清单与配置哈希；同时绑定P9-A/P9-B1
Schema、正式运行证据包、投影、节点、边及本体文件的实际内容地址。
语义校验结果本身必须通过独立Schema，并与sidecar状态摘要、实际检索结果、P9-A
响应和审计对象逐项一致；摘要不构成独立权威。
语义校验结果中的失败码按冻结枚举序排列，R/N/F/E数组按数值后缀、后缀长度和
原始UTF-8字节依次升序排列；成员不变但顺序不同也不是同一确定性结果。
QueryIR歧义在当前合同下只能映射为`ABSTAIN + NO_SAFE_ADMITTED_ANSWER`；若未来希望
增加新的学生端状态或P9-A原因码，必须另行授权修改P9-A，不能在P9-B1Q中静默加入。
