# parasitology-kg

面向人体寄生虫学学习的、以全健康（One Health）为总体框架、支持检索增强生成（RAG）的开放知识图谱。

## 项目目标

本项目把经过来源登记和人工审核的人体寄生虫学知识组织为可阅读、可追溯、可计算的关系网络，帮助学生在教材和课堂学习之外，使用 AI 工具获得可靠的补充支撑。

知识图谱重点连接：

- 寄生虫及其发育阶段；
- 人、动物宿主、媒介和中间宿主；
- 生态环境、生产生活方式与暴露行为；
- 感染、疾病、诊断、治疗和防控；
- 人类健康、动物健康与环境健康之间的相互关系。

## 项目边界

- 本项目是学习辅助资源，不替代教材、课堂教学、临床指南或专业诊疗。
- 原始教材、课件和受版权保护的全文不存入公开仓库；仓库只保存经审核的知识表达、必要的短引文和可追溯来源信息。
- AI 或 NotebookLM 生成的提取结果属于候选语料，未经人工审核不得进入正式知识层。
- 关键事实和关系必须能够追溯到登记来源；无法确认的内容应明确标记，不以流畅表述代替证据。

## 数据路线

项目拟采用“结构化 Markdown 为权威主数据，CSV/JSON 等图数据由其生成”的路线：

- Markdown 正文服务于学生阅读和语义 RAG；
- 结构化元数据服务于实体识别、关系抽取和图查询；
- 派生数据服务于不同 AI 工具和图数据库；
- 所有正式内容通过 Git 版本控制和审阅流程进入主分支。

## 当前阶段

Phase 0治理框架、Phase 1 Schema与编辑规范、Phase 2来源集冻结和Phase 3双路
候选提取已经完成；Phase 2/3修订由PR #4合并。Phase 4已经完成双路对照、教师
裁决和39条原子候选的正式准入准备。Phase 5已完成39条候选的四类重分；第一批
10条关系和14个实体已经学科教师批准为`reviewed`并进入正式知识层，其派生图
已通过确定性重建与入库验收并由PR #8合并。Phase 6固定问题集、回答合同和教师
评分门槛正在审阅；第二、三批仍未授权，面向学生的RAG尚未发布。

首个试点为：

> 以华支睾吸虫为中心，构建覆盖“寄生虫—人—动物—环境—行为—疾病—诊疗—防控”的 One Health 知识子图，并验证其对学生 RAG 学习的支撑能力。

详细文件：

- [项目范围与原则](docs/PROJECT_SCOPE.md)
- [系统工作流与阶段目标](docs/WORKFLOW.md)
- [Schema说明](schema/README.md)
- [编辑与审核规范](docs/EDITORIAL_GUIDE.md)
- [华支睾吸虫试点来源冻结记录](sources/clonorchis-sinensis-pilot.md)
- [第10版教材华支睾吸虫专节页码核验](reviews/clonorchis-sinensis/pmph-10e-page-scope-verification.md)
- [Phase 3华支睾吸虫双路候选提取](phase3/clonorchis-sinensis/README.md)
- [Phase 4最终裁决与公开收口](reviews/clonorchis-sinensis/phase4-final-adjudication.md)
- [Phase 4批准候选账本](candidates/clonorchis-sinensis/phase4-approved-admission-ledger.yml)
- [Phase 4 Schema适配缺口](reviews/clonorchis-sinensis/phase4-schema-fit-gap.yml)
- [Phase 5正式准入方案](phase5/clonorchis-sinensis/README.md)
- [Phase 5第一批派生图入库验收](reviews/clonorchis-sinensis/phase5-batch1-intake-validation.md)
- [Phase 6学生RAG验收协议](phase6/clonorchis-sinensis/README.md)
- [NotebookLM/Gemini候选语料v1审计](reviews/clonorchis-sinensis/notebooklm-gemini-v1-audit.md)
- [NotebookLM/Gemini原子命题v2](candidates/clonorchis-sinensis/notebooklm-gemini-v2.md)
- [NotebookLM/Gemini原子命题v2审计](reviews/clonorchis-sinensis/notebooklm-gemini-v2-audit.md)
- [Notebook候选提取边界](docs/NOTEBOOK_EXTRACTION_BOUNDARY.md)
- [NotebookLM/Gemini标准化重跑v3](candidates/clonorchis-sinensis/notebooklm-gemini-v3.md)
- [NotebookLM/Gemini标准化重跑v3审计](reviews/clonorchis-sinensis/notebooklm-gemini-v3-audit.md)
- [项目状态](docs/STATUS.md)

## 历史说明

仓库早期的 `triples.csv` 是 2025 年的概念验证数据，仅包含少量无来源三元组，现保存在 `archive/poc-2025/`，不作为正式知识数据使用。
