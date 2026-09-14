# parasitology-kg

## 项目定位

本仓库是一个可信知识图谱—检索增强生成（KG-RAG）方法研究原型，当前科学范围
严格限定于华支睾吸虫（*Clonorchis sinensis*）及华支睾吸虫病知识域。它研究如何
把可追溯的权威知识组织为结构化知识图谱，并通过有作用域的查询解释和语义约束，
生成证据边界内的回答或在证据不足时拒答。

华支睾吸虫是本方法的验证试验域，不代表全部人体寄生虫学，也不能据此推断系统在
其他虫种、临床场景或一般医学任务中的性能。

## 为什么选择华支睾吸虫知识域

该知识域包含实体、虫期、宿主、解剖部位、事件、条件、诊断证据角色以及否定和
作用域等多类结构化交互，适合检验知识进入、查询解释、确定性检索和证据约束能否
保持一致。

## 方法概览

权威知识经过登记和审核后进入结构化知识图谱；用户问题被解释为带作用域的
QueryIR；确定性检索只在冻结知识边界内工作；语义约束核查实体、关系、证据角色、
否定和范围；最终只允许形成证据绑定的回答，覆盖或证据不足时关闭式拒答。

## 当前研究状态

**P9 engineering is frozen.**

```text
FROZEN_EVALUATION_SNAPSHOT_V1=
d77a76e6219482e1933e6377dfbad2151c829bef

SYSTEM_STATE=
FROZEN_RESEARCH_PROTOTYPE

FINAL_ENGINEERING_ACCEPTANCE=
NOT_ESTABLISHED
```

该快照是今后所有P10评估使用的系统提交。后续仅文档提交可以推进GitHub前台版本，
但不构成新的系统版本，也不得替换上述评估目标。

本系统不得描述为生产就绪、已经临床验证或对一般寄生虫学可靠。当前工作仅为公共
文档收口；文档收口通过后，下一项可进入的科学工作是P10科学评估方案设计，而非
继续调优P9。

## 导航

- [当前权威状态](docs/STATUS.md)
- [冻结研究快照](phase9/clonorchis-sinensis/RESEARCH-SNAPSHOT.md)
- [Phase 9架构与历史入口](phase9/clonorchis-sinensis/README.md)
- [项目范围与原则](docs/PROJECT_SCOPE.md)
- [系统工作流与阶段目标](docs/WORKFLOW.md)
- [Schema说明](schema/README.md)
- [编辑与审核规范](docs/EDITORIAL_GUIDE.md)
- [华支睾吸虫试点来源冻结记录](sources/clonorchis-sinensis-pilot.md)
- [Phase 7 PCMS正式准入](phase7/clonorchis-sinensis/pilot-content-minimum-set-admission.yml)
- [P9-B1Q Scoped QueryIR](phase9/clonorchis-sinensis/p9b1q/README.md)

历史失败、盲测与修正记录保留在各阶段文档和治理证据中，作为可追溯的历史工程与
验证证据；它们不构成最终工程验收。
