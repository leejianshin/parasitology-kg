# 项目状态

最后更新：2026-07-25

## 当前状态

| 阶段 | 名称 | 状态 | 当前目标 |
|---|---|---|---|
| Phase 0 | 治理框架冻结 | REVIEW | 审阅并确认目标、边界和工作流 |
| Phase 1 | Schema与编辑规范 | NOT_STARTED | 等待Phase 0批准 |
| Phase 2 | 华支睾吸虫来源集冻结 | NOT_STARTED | 等待Schema冻结 |
| Phase 3 | 双路候选提取 | NOT_STARTED | 等待来源集冻结 |
| Phase 4 | 对照与教师审核 | NOT_STARTED | 等待候选提取 |
| Phase 5 | 知识子图入库 | NOT_STARTED | 等待教师批准 |
| Phase 6 | 学生RAG验收 | NOT_STARTED | 等待子图完成 |
| Phase 7 | 发布与扩展 | NOT_STARTED | 等待RAG验收 |

## 当前决策

- GitHub作为知识图谱的版本控制和发布平台；
- 结构化Markdown拟作为权威主数据；
- CSV、JSON或图数据库文件作为派生数据；
- One Health作为知识关系的总体组织框架；
- 华支睾吸虫作为首个端到端试点；
- NotebookLM/Gemini提取和独立文件提取构成两条候选语料路线；
- 教师审核是正式入库的必要条件；
- 网站与大规模自动化推迟到试点验收之后。

## Phase 0待确认事项

1. 项目正式定位是否准确；
2. One Health四个组织维度是否合适；
3. 七阶段工作流是否需要合并或拆分；
4. 华支睾吸虫试点的完成标准是否充分；
5. 是否批准进入Phase 1：Schema与编辑规范。

## 下一动作

Phase 0框架批准后，起草：

- 实体类型表；
- 关系类型表；
- 来源登记规则；
- 结构化Markdown模板；
- 最小自动校验规则。
