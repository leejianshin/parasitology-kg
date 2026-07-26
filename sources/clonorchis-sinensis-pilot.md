# 华支睾吸虫试点来源冻结与修复记录

历史冻结版本：`clonorchis_sinensis_pilot_v1`（已由勘误继替）  
合并前继替版本：`clonorchis_sinensis_pilot_v1_1`（未进入主分支）  
当前修订版本：`clonorchis_sinensis_pilot_v1_2`  
登记日期：2026-07-25  
修复日期：2026-07-26  
审核状态：`frozen_in_pr`

## 选择结论

Phase 3不再要求Notebook与独立提取器分别拼装9个来源。两条路线只读取同一个
私有Drive语料包的4个证据文件，分别承担事实、课堂、大纲和考核角色。第4版
教材在补齐页图前转为待核补充，CDC、WHO和IARC资料转到Phase 4作权威复核。
来源之间不互相替代。

| source_id | 核心角色 | 冻结范围 | 可直接承担 | 不得单独承担 |
|---|---|---|---|---|
| `source.pmph_human_parasitology_10e_2024` | 核心事实 | 医学蠕虫学—吸虫—华支睾吸虫 | 基础形态、生活史、宿主、致病、诊断、治疗、流行与防治 | 地方最新数据、政策成效、未核对页码的逐字引文 |
| `source.courseware_lesson_04_2025` | 教学表达 | E02-v3完整派生文件；TE-001～TE-003 | 学习目标、教学重点、课堂讨论问题 | 医学事实、诊疗建议、地方数字、干预效果 |
| `source.syllabus_clinical_medicine_integrated` | 课程边界 | 课程简介、课程目标、第十三章“医学蠕虫—吸虫” | 本科教学目标、能力要求、One Health教学定位 | 具体寄生虫事实、诊疗依据 |
| `source.question_bank_export_2026` | 考核与易错点 | 题干直接命中81行，按ID去重后53行 | 覆盖度、干扰项、病例迁移和错误模式 | 核心事实或更新结论的唯一证据 |

补充核查来源：

| source_id | 角色 | 已确认范围 | 使用限制 |
|---|---|---|---|
| `source.pmph_human_parasitology_8y_4e_2023` | 教材版本交叉核查 | 印刷页码128–133；第133页下一节页内开始 | `PENDING_PAGE_IMAGE_VERIFICATION`；Phase 3不得使用 |

权威核查来源：

| source_id | 主要核查任务 |
|---|---|
| `source.cdc_dpdx_clonorchiasis_2024` | 生活史、宿主、虫卵形态、寄生部位和病原学诊断限制 |
| `source.cdc_clinical_overview_clonorchis_2024` | 临床、影像辅助、治疗层级和食品安全边界 |
| `source.who_foodborne_trematode_fact_sheet` | 诊断、防治、预防性化疗和One Health框架 |
| `source.iarc_clonorchis_group1` | 华支睾吸虫感染的Group 1致癌危害分类 |

## Phase 3私有语料包

- pack_id：`clonorchis_phase3_private_pack_v1_2`
- Drive根目录：
  `https://drive.google.com/drive/folders/10dZDxrgI0oZhhGhrWq6swSJvO-KrNvXh`
- manifest文件ID：`1GIlXXid63SMXXW2APwonmxVrlK9T1W2n`
- 历史归档目录：`https://drive.google.com/drive/folders/1340Qs6fVx6svVBQoGsK3YrvpeRZ6GfYG`
- 证据文件数：4
- 路线要求：A、B均按精确文件名和Drive ID读取同一包；不得各自从大资料库
  检索或补齐来源。

包内目录：

| 目录 | 作用 | 是否为Phase 3证据 |
|---|---|---|
| `00_CONTROL` | manifest、共享协议、模板及路线入口Prompt | 否 |
| `01_EVIDENCE` | E01–E04 | 是 |
| `02_SUPPLEMENTAL_PENDING` | 第4版范围勘误与待补页图事项 | 否 |
| `03_PHASE4_AUTHORITY` | CDC、WHO、IARC核查清单 | 否 |

私有包保留受版权保护的页图、课件和题库切片；公开仓库只登记文件身份、范围、
Drive ID和校验摘要，不复制其正文。

## E02派生证据审计

- Phase 3唯一课件输入：`E02_courseware_clonorchis_teaching-expressions-v3.md`；
- 稳定定位：`TE-001`形态学习目标、`TE-002`生活史教学重点、`TE-003` One Health讨论题；
- 角色：`teaching_expression`，仅允许学习目标、教学重点和讨论题候选；
- 人工核验PDF与旧完整课件副本已移到包外历史目录，只作来源追溯，不进入Notebook或Phase 3硬门；
- E02不得单独证明医学事实、诊疗建议、地方流行数据或干预效果。

## 证据使用规则

1. `core_fact`关系优先由第10版教材直接支持，并补齐章节页码或PDF页序。
2. E02只记录课堂表达和教学情境；其内容不得单独升级为`core_fact`，也不得以课件与题库相互印证替代教材或权威来源。
3. 大纲只决定“教什么、教到什么程度”，不承担事实证明。
4. 题库只用于发现考点、干扰项和错误模式；答案必须回查教材或更新来源。
5. 相同陈述同时出现在课件和题库中，不视为两个独立来源。
6. 不把AI或NotebookLM生成内容登记为事实来源；它们只生成待核候选。
7. 题库去重ID不是全局唯一定位；引用时必须同时记录来源文件、来源工作表、
   文件内题号和去重ID。

## NotebookLM/Gemini候选样本

用户提供的NotebookLM/Gemini提取文本已作为候选样本保存于
`candidates/clonorchis-sinensis/notebooklm-gemini-v1.md`，其逐条审计见
`reviews/clonorchis-sinensis/notebooklm-gemini-v1-audit.md`。

该文本粘贴后只保留了`,,`等引用残迹，已经失去“陈述—原文件—页码”的映射，因此：

- 不能登记为`source`；
- 不能因语言流畅而视为已核事实；
- 不能与独立提取结果合并后形成“多数表决”；
- 必须重新导出NotebookLM逐条引用，或回到冻结原文件补齐定位。

用户随后提供的10条原子命题保存于
`candidates/clonorchis-sinensis/notebooklm-gemini-v2.md`，双轴审计见
`reviews/clonorchis-sinensis/notebooklm-gemini-v2-audit.md`。v2已具备
`claim_id`、来源名和题号，但仍发现：

- Gemini声明的第五版教材、两份第三讲文件和张巧玲论文未在当前Drive解析；
- 14个题库去重ID实际对应30行，不能只写`Dxxxx`；
- `D0051`实际属于卫氏并殖吸虫，构成实体错引；
- “内容正确性”和“来源可追溯性”必须分开判定；
- 具体治理工具不能仅凭题库答案升级为公共卫生事实。

用户按固定边界完成的标准化重跑保存于
`candidates/clonorchis-sinensis/notebooklm-gemini-v3.md`，独立验收见
`reviews/clonorchis-sinensis/notebooklm-gemini-v3-audit.md`。v3的固定字段、
来源清单和跨虫污染识别通过，但原子性、题库复合定位、证据角色和干预效果
自检未通过。结论为`FORMAT_PASS_EVIDENCE_FAIL`。

由此新增固定边界文件`docs/NOTEBOOK_EXTRACTION_BOUNDARY.md`。以后Notebook
自报PASS不再自动视为通过；题库定位由外部程序生成，Notebook-only来源不得
标为`resolved`。

## 第10版教材页码核验

用户于2026-07-25最初估计“华支睾吸虫专节应该在93～98页”。Notebook v3
随后从索引取得`Clonorchis sinensis/华支睾吸虫 93`。用户进一步提供覆盖
印刷页码92–97的连续页图：第93页出现“第二节｜华支睾吸虫”，第94–97页
连续覆盖形态、生活史、致病、临床、诊断、流行与防治，第97页以“（吴翔）”
署名收束。因此正式冻结为**印刷页码93–97**，原“93–98页”估计作废。

核验记录见
`reviews/clonorchis-sinensis/pmph-10e-page-scope-verification.md`。PDF页序未在
截图中显示，后续关系统一引用印刷页码，不得把二者混写。

## Phase 3前的待补证

| 优先级 | 待办 | 原因 | 处理门槛 |
|---|---|---|---|
| CLOSED | 核验第10版教材华支睾吸虫专节范围 | 连续页图确认印刷页码93–97，第97页署名收束 | 已完成；逐条关系仍须绑定具体页码 |
| P1 | 解析Gemini v2声明但当前Drive未找到的原文件 | 第五版教材、长标题第三讲文件和张巧玲论文仍无法回跳 | 若纳入正式来源集，须导出Notebook引用卡或提供原文件ID、准确文件名和页码；不阻塞共享核心来源的Phase 3提取 |
| P1 | 核对教学大纲学时口径 | 文件名与正文存在疑点 | 课程负责人确认后更新登记 |
| CLOSED | 生成题库Phase 3精简切片 | 宽关键词命中145行会混入只在选项出现的其他虫种 | 题干直接命中81行，按`dedup_id`去重后53行，保留复合定位 |
| P1 | 补齐第4版印刷页128–133页图 | OCR已纠正范围，但不足以承担引文或细数字 | 页图人工核验后发布新语料包版本 |

## 冻结边界

本次修复只冻结来源身份、角色、派生规则和提取范围，不把任何来源内容直接批准
为正式知识。`clonorchis_sinensis_pilot_v1_2`已在PR #4中冻结，但PR合并且
教师明确启动前，Phase 3只允许来源预检，不得运行候选抽取。
新增来源、替换文件或扩大范围必须发布新的`pack_id`并经过PR审阅。
