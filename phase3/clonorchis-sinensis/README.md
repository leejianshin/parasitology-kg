# Phase 3：华支睾吸虫双路候选提取

状态：`PAUSED_SOURCE_REPAIR`  
待冻结来源集：`clonorchis_sinensis_pilot_v1_1`  
唯一私有语料包：`clonorchis_phase3_private_pack_v1_1`  
Phase 2批准记录：PR #3，合并提交
`e659ae53f9187c353a2a215f0c4a1bd06dae29c5`

## 目标

路线A和路线B使用同一组物理文件、相同来源范围、相同字段与相同准入规则，
分别生成候选语料。
本阶段只发现事实、遗漏、冲突和Schema问题，不把候选写入正式知识目录。

## 两条路线

| 路线 | 执行环境 | 隔离要求 | 输出 |
|---|---|---|---|
| A | 新建的专用NotebookLM/Gemini Notebook | 只导入私有包，不复用202来源Notebook或v1–v3答案 | `route-a-notebook-candidates.yml` |
| B | 新的干净上下文 | 只读取同一私有包，不读取`candidates/`、`reviews/`及路线A输出 | `route-b-independent-candidates.yml` |

当前对话已经读取并审计过Notebook v1–v3，不能再冒充路线B的干净上下文。
因此路线B必须使用独立的新对话或其他未见候选答案的执行环境。

## 固定执行顺序

1. PR #4合并前不运行任一路线。
2. 两条路线分别核对相同`pack_id`和E01–E04的文件名、Drive ID与范围。
3. 任一必需证据文件不可访问或身份不一致，输出`SOURCE_MANIFEST_FAIL`并停止。
4. 待补第4版和Phase 4权威来源不属于本阶段硬门，不因其缺失而停止。
5. 按`candidate-template.yml`生成原子命题。
6. 分别输出缺失项、来源冲突和Schema适配问题。
7. 两份结果均完成后才进入Phase 4对照；不得边看另一条路线边补写。

## 私有包证据范围

| evidence_id | 文件 | 提取范围 | 角色 |
|---|---|---|
| `E01` | `E01_10e_printed_92-97_scope_93-97.pdf` | 印刷页93–97；92仅作边界见证 | 当前课程核心事实 |
| `E02` | `E02_courseware_04_FULL_scope_pdf22-71.pdf` | PDF页序22–71 | 教学表达与One Health情境 |
| `E03` | `E03_syllabus_clinical_relevant.md` | 完整派生文件 | 教学边界 |
| `E04` | `E04_qbank_clonorchis_direct_dedup.txt` | 53条去重行；使用复合定位 | 考核线索 |

第4版教材已纠正为印刷页128–133，但在补齐页图前只放在
`02_SUPPLEMENTAL_PENDING`；CDC、WHO、IARC清单放在
`03_PHASE4_AUTHORITY`。两类文件均不得参与Phase 3抽取或来源硬门。

私有包：
`https://drive.google.com/drive/folders/10dZDxrgI0oZhhGhrWq6swSJvO-KrNvXh`

## 本阶段交付物

- 路线A候选；
- 路线B候选；
- 每条路线自己的缺失项和Schema问题；
- 执行日志与来源清单；
- Phase 4对照前的完整性检查。
