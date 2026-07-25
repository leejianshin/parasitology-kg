# Phase 3：华支睾吸虫双路候选提取

状态：`IN_PROGRESS`  
冻结来源集：`clonorchis_sinensis_pilot_v1`  
Phase 2批准记录：PR #3，合并提交
`e659ae53f9187c353a2a215f0c4a1bd06dae29c5`

## 目标

路线A和路线B使用相同来源范围、相同字段与相同准入规则，分别生成候选语料。
本阶段只发现事实、遗漏、冲突和Schema问题，不把候选写入正式知识目录。

## 两条路线

| 路线 | 执行环境 | 隔离要求 | 输出 |
|---|---|---|---|
| A | NotebookLM/Gemini | 不调用冻结集以外的Notebook来源，不复用v1–v3答案 | `route-a-notebook-candidates.yml` |
| B | 新的干净上下文 | 不读取`candidates/`、`reviews/`及路线A输出 | `route-b-independent-candidates.yml` |

当前对话已经读取并审计过Notebook v1–v3，不能再冒充路线B的干净上下文。
因此路线B必须使用独立的新对话或其他未见候选答案的执行环境。

## 固定执行顺序

1. 两条路线分别核对9个冻结来源及限定范围。
2. 任一来源不可访问，输出`SOURCE_MANIFEST_FAIL`并停止事实提取。
3. 按`candidate-template.yml`生成原子命题。
4. 分别输出缺失项、来源冲突和Schema适配问题。
5. 两份结果均完成后才进入Phase 4对照；不得边看另一条路线边补写。

## 冻结来源范围

| source_id | 提取范围 | 角色 |
|---|---|---|
| `source.pmph_human_parasitology_10e_2024` | 印刷页93–97 | 当前课程核心事实 |
| `source.pmph_human_parasitology_8y_4e_2023` | 印刷页128–138 | 教材版本交叉核查 |
| `source.courseware_lesson_04_2025` | PDF页序22–89；72–89仅作背景 | 教学表达与One Health情境 |
| `source.syllabus_clinical_medicine_integrated` | 课程简介、目标、第十三章吸虫 | 教学边界 |
| `source.question_bank_export_2026` | 华支睾吸虫相关行；使用程序生成的复合定位 | 考核线索 |
| `source.cdc_dpdx_clonorchiasis_2024` | 冻结网页 | 生活史、宿主、形态、诊断核查 |
| `source.cdc_clinical_overview_clonorchis_2024` | 冻结网页 | 临床与治疗核查 |
| `source.who_foodborne_trematode_fact_sheet` | 冻结网页 | 防控与One Health核查 |
| `source.iarc_clonorchis_group1` | 冻结分类页 | 致癌危害分类核查 |

第五版教材、未解析的第三讲课件、张巧玲论文和Notebook中的其他来源均不属于
本轮冻结范围，即使Notebook能够访问，也不得用于两条路线。

## 本阶段交付物

- 路线A候选；
- 路线B候选；
- 每条路线自己的缺失项和Schema问题；
- 执行日志与来源清单；
- Phase 4对照前的完整性检查。
