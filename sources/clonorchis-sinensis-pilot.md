# 华支睾吸虫试点来源冻结记录

冻结候选版本：`clonorchis_sinensis_pilot_v1`  
登记日期：2026-07-25  
审核状态：`in_review`

## 选择结论

本试点采用四类Drive核心来源，分别承担事实、课堂、大纲和考核角色；另登记CDC、WHO和IARC资料作为权威核查来源。来源之间不互相替代：教材决定本科核心事实口径；课件体现教学顺序与本地情境；大纲限定学生应达到的范围；题库只反映考核线索和易错点；权威网页用于发现过时、过度概括或临床边界问题。

| source_id | 核心角色 | 冻结范围 | 可直接承担 | 不得单独承担 |
|---|---|---|---|---|
| `source.pmph_human_parasitology_10e_2024` | 核心事实 | 医学蠕虫学—吸虫—华支睾吸虫 | 基础形态、生活史、宿主、致病、诊断、治疗、流行与防治 | 地方最新数据、政策成效、未核对页码的逐字引文 |
| `source.courseware_lesson_04_2025` | 教学重点、One Health情境 | PDF页序22–89 | 教学顺序、案例、易错点、本地问题线索 | 未给出处的地方数字、历史事实、治理效果 |
| `source.syllabus_clinical_medicine_integrated` | 课程边界 | 课程简介、课程目标、第十三章“医学蠕虫—吸虫” | 本科教学目标、能力要求、One Health教学定位 | 具体寄生虫事实、诊疗依据 |
| `source.question_bank_export_2026` | 考核与易错点 | 关键词命中145行、92个唯一题号 | 覆盖度、干扰项、病例迁移和错误模式 | 核心事实或更新结论的唯一证据 |

补充核查来源：

| source_id | 角色 | 已确认范围 | 使用限制 |
|---|---|---|---|
| `source.pmph_human_parasitology_8y_4e_2023` | 教材版本交叉核查 | 印刷页码128–138，华支睾吸虫专节 | 八年制教材，不替代第10版课程核心口径；OCR需回看页图 |

权威核查来源：

| source_id | 主要核查任务 |
|---|---|
| `source.cdc_dpdx_clonorchiasis_2024` | 生活史、宿主、虫卵形态、寄生部位和病原学诊断限制 |
| `source.cdc_clinical_overview_clonorchis_2024` | 临床、影像辅助、治疗层级和食品安全边界 |
| `source.who_foodborne_trematode_fact_sheet` | 诊断、防治、预防性化疗和One Health框架 |
| `source.iarc_clonorchis_group1` | 华支睾吸虫感染的Group 1致癌危害分类 |

## 课件页序审计

- PDF页序22–24：华支睾吸虫专节与学习目标；
- PDF页序25–39：形态和生活史；
- PDF页序40–61：致病、临床、诊断、病例与阶段小结；
- PDF页序62–71：流行、防治与小结；
- PDF页序72–89：历史、地方文化、翻转课堂与测验；
- PDF页序90：布氏姜片吸虫专节开始。

页序均指PDF文件页序，不等同于课件内部幻灯片编号或印刷页码。

## 证据使用规则

1. `core_fact`关系优先由第10版教材直接支持，并补齐章节页码或PDF页序。
2. 课件可补充课堂表达和教学情境，但其地方数字、历史叙述和治理结论默认记为`background_only`。
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

## 第10版教材临时定位

用户于2026-07-25最初估计“华支睾吸虫专节应该在93～98页”。Notebook v3
随后从索引取得`Clonorchis sinensis/华支睾吸虫 93`，因此现把**印刷页码93**
登记为`provisional_start_page_only`。该索引只能支持专节起始页，不能证明
结束页为98，也不能支撑任何正文关系；仍需显示专节标题、起止页码的页图。

## Phase 3前的待补证

| 优先级 | 待办 | 原因 | 处理门槛 |
|---|---|---|---|
| P0 | 核验第10版教材印刷页93起始及专节结束页 | Notebook索引已提示起始页93，但正文与结束页仍不可见 | 取得显示专节标题与起止页码的页图或PDF局部后，方可把教材关系标为`reviewed` |
| P0 | 解析Gemini v2声明但当前Drive未找到的原文件 | 第五版教材、两份第三讲文件和张巧玲论文仍无法回跳 | 导出Notebook引用卡或提供原文件ID、准确文件名和页码 |
| P1 | 核对教学大纲学时口径 | 文件名与正文存在疑点 | 课程负责人确认后更新登记 |
| P1 | 对题库92个唯一题号去重并标记错误/过时项 | 已确认v2引用的14个ID对应30行，且D0051错引 | Phase 3只抽取具有复合定位且通过核对的考核线索 |

## 冻结边界

本次只冻结来源身份、角色和提取范围，不把任何来源内容直接批准为正式知识。新增来源或扩大范围必须修改`sources/registry.yml`并经过PR审阅。
