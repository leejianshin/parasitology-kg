# NotebookLM/Gemini标准化重跑v3独立审计

审计日期：2026-07-25  
对象：`candidate.clonorchis_notebooklm_gemini_v3`  
结论：`FORMAT_PASS_EVIDENCE_FAIL`  

## 一、验收结论

v3证明固定模板能够显著改善输出结构，但尚不能把Notebook自检当作质量闸门。

| 维度 | 结果 | 说明 |
|---|---|---|
| 固定字段和来源清单 | PASS | 7份来源和10条命题均有稳定候选ID |
| 跨寄生虫污染发现 | PASS | 正确识别并剔除属于卫氏并殖吸虫的D0051 |
| 来源身份与访问层级 | PARTIAL | 3份来源仍为Notebook-only，未提供稳定外部定位 |
| 原子性 | FAIL | C003、C005、C006仍含多个可独立判断 |
| 题库复合定位 | FAIL | 字段名称齐全，但值填入了错误的列 |
| 证据角色约束 | FAIL | 多条医学事实和治理效果仍只由题库或课件承担 |
| 干预效果证据 | FAIL | C009用题库自身断言证明题库答案 |
| 自检真实性 | FAIL | 至少5个PASS与实际结果不符 |

因此，v3可以作为Phase 3路线A的**格式样本**，不能作为已通过的候选事实集。

## 二、来源解析结果

| 来源 | 独立结果 | 处置 |
|---|---|---|
| 第10版《人体寄生虫学》 | Drive文件身份已冻结；文本抽取仅见封面。Notebook索引提示印刷页93为专节起始页 | 把“93”升级为临时起始页；结束页仍未知，正文关系继续BLOCKED |
| 第4版《人体寄生虫学》（吴忠道、刘佩梅） | Drive可完整提取OCR；华支睾吸虫专节起于印刷页128，诊断内容见印刷页131 | 登记为补充核查来源，不替代第10版课程核心教材 |
| 第5版《人体寄生虫学》 | Notebook可见，当前Drive按完整题名未解析 | notebook_only；提供文件、稳定链接或Notebook来源卡后再冻结 |
| `04 第四课.pdf` | Drive已冻结，华支睾吸虫核心教学范围为PDF页序22–71 | 可作课堂表达；不能自动承担更新诊疗或干预效果 |
| 长标题第三讲文件 | Notebook可见，当前Drive未解析 | notebook_only；“形态幻灯片”“致病幻灯片”不是可接受的数字定位 |
| 张巧玲论文 | Notebook可见，按题名和作者未在Drive解析 | notebook_only；且论文引言不能替代IARC分类原始权威来源 |
| `题库.txt` | Drive已冻结并完成原行反查 | 只作assessment_clue，不能单独把题干答案升级为医学事实 |

## 三、题库复合定位仍然错误

Notebook虽然输出了四个字段，但把字段值错位。例如v3给D0048的定位是：

```text
source_file: 题库.txt
sheet_name: 26年秋第三次作业（中医班）
item_no_in_file: 1
dedup_id: D0048
```

原始汇总行的正确定位是：

```text
source_file: 26年秋第三次作业（中医班）.xls
sheet_name: 课程题库
item_no_in_file: 1
dedup_id: D0048
```

本次引用的其他题号也应按原始列重建：

| dedup_id | 正确来源文件 | 正确工作表 | 文件内题号 |
|---|---|---|---:|
| D0049 | `26年秋第三次作业（中医班）.xls` | `课程题库` | 2 |
| D0019 | `26年秋第三次作业（中医班）.xls` | `课程题库` | 5 |
| D0488 | `25年秋第三周作业.xls` | `25年秋第三周作业` | 33 |
| D0422 | `25年秋第四周作业.xls` | `25年秋第四周作业` | 23 |
| D0404 | `25年秋第四周作业.xls` | `25年秋第四周作业` | 20 |
| D0411 | `25年秋第四周作业.xls` | `25年秋第四周作业` | 21 |

“具有四个字段”不等于“定位正确”。以后应由程序从题库原行生成定位，
不再要求Notebook自行猜列。

## 四、逐条审计

| claim_id | 判定 | 主要问题 | 处置 |
|---|---|---|---|
| C_CS_001 | REVISE / PARTIAL | 形态特征可用；“人体蠕虫卵中最小者”只由无编号课件表述支持，是依赖比较范围的教学最高级 | 核心事实记录27–35 μm × 11–20 μm及形态；最高级仅作绑定教材的教学表述 |
| C_CS_002 | REVISE / PARTIAL | “适宜淡水螺”为第一中间宿主可用；具体中文名、种名和地域混在一条；第5版为Notebook-only，题库定位填错 | 拆分上位宿主关系与逐种宿主记录；补学名、地区和稳定来源 |
| C_CS_003 | REVISE / PARTIAL | 同一命题同时表达淡水鱼的主要地位和虾的有限记录，不满足原子性；第4版未给页码 | 拆为鱼和虾两条；鱼为主要第二宿主，虾需中国特定种及较低流行贡献限定 |
| C_CS_004 | CONTENT_PASS / EVIDENCE_ROLE_FAIL | 囊蚴为人类感染阶段正确，但唯一声明证据是题库 | 改由CDC/WHO或教材直接支持；题库仅保留为考点 |
| C_CS_005 | REVISE / PARTIAL | 把成虫寄生部位和“主要致病阶段”合并；后者未由证据短句直接支持；课件无数字页序，题库定位填错 | 拆为“成虫居小、中型胆管”和独立致病机制关系 |
| C_CS_006 | REVISE / EVIDENCE_ROLE_FAIL | 把诊断依据、轻感染敏感性和胆管阻塞合为一条；所引题库未支持“轻感染或胆管阻塞时漏诊”；未写虫卵物种鉴别限制 | 拆为常用病原学方法、低虫负荷敏感性、物种鉴别限制和十二指肠液取材四条 |
| C_CS_007 | CONTENT_PASS_AFTER_REWORD / SOURCE_FAIL | 正式评价对象应写“华支睾吸虫感染”，分类写IARC Group 1；不能只引用课件转述 | 改由IARC官方分类直接支持；说明Group 1是危害识别 |
| C_CS_008 | CONTENT_PASS / EVIDENCE_ROLE_FAIL | 题库选项“相关性受到重视”不能独立证明风险增加 | 改由IARC、WHO或CDC直接支持；题库只作考点 |
| C_CS_009 | REJECT | 题库题干、正确选项和解析是同一断言的循环证明；没有干预研究、政策评估或规范支持三项工具“有效” | 降为`intervention_hypothesis`，不得进入正式事实层 |
| C_CS_010 | MOVE_OUT_OF_CLAIMS | 这是来源抽取状态，不是寄生虫学命题；`statement_type: null`本身违反固定枚举 | 移入source_quality；索引只支持起始页93，不支持93–98完整范围 |

## 五、对Notebook自检的更正

```yaml
quality_check_independent:
  every_claim_is_atomic: FAIL
  every_claim_has_exact_source_title: PASS
  every_claim_has_stable_external_locator: FAIL
  every_claim_has_numeric_locator_or_explicit_blocked_status: FAIL
  question_bank_uses_composite_locator: FAIL
  no_cross_parasite_contamination_found: PASS
  infective_and_pathogenic_stages_separated: PARTIAL
  diagnostic_clues_and_confirmation_separated: NOT_APPLICABLE
  association_and_causation_separated: PASS
  intervention_claims_have_effect_evidence: FAIL
  source_quality_items_removed_from_claims: FAIL
  evidence_role_invalid_claim_ids:
    - C_CS_004
    - C_CS_006
    - C_CS_007
    - C_CS_008
    - C_CS_009
  non_atomic_claim_ids:
    - C_CS_003
    - C_CS_005
    - C_CS_006
  blocked_or_retrace_claim_ids:
    - C_CS_001
    - C_CS_002
    - C_CS_003
    - C_CS_005
    - C_CS_006
    - C_CS_007
    - C_CS_008
    - C_CS_009
    - C_CS_010
```

## 六、可进入下一轮的内容

v3中可保留的不是原始10条，而是以下经过重新绑定来源的方向：

1. 虫卵尺寸和形态；
2. 适宜淡水螺的第一中间宿主角色；
3. 淡水鱼的主要第二中间宿主角色；
4. 中国部分虾种的低权重补充宿主记录；
5. 囊蚴为终宿主感染阶段；
6. 成虫居肝内小、中型胆管；
7. 胆管病理改变；
8. 粪便虫卵显微检查及其敏感性、鉴别限制；
9. IARC Group 1危害分类；
10. 长期感染与胆管癌风险增加；
11. 综合One Health防控原则。

批次追溯、抽检公示和“生食零容忍”继续留在研究问题层，不进入事实层。
