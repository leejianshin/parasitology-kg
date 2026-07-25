# NotebookLM/Gemini华支睾吸虫标准化重跑v3

候选编号：`candidate.clonorchis_notebooklm_gemini_v3`  
接收日期：2026-07-25  
状态：`raw_candidate_compact`  
来源：用户按《知识图谱候选语料提取与证据边界》从Notebook重新生成  
说明：本文件保留来源、命题、声明状态和自检结论；证据短句仅作内部核对，
不是正式知识或可独立证明事实的来源。

## A. Notebook声明的来源

| source_candidate_id | Notebook显示的完整标题 | 类型 | 声明角色 | 当前外部解析状态 |
|---|---|---|---|---|
| SRC_001 | `人体寄生虫学(第五版).pdf` | textbook | core_fact | Notebook可见；当前Drive未解析 |
| SRC_002 | `人体寄生虫学 第4版 (吴忠道).pdf` | textbook | core_fact | Drive已解析：`gdrive:1NRvl19gksINWrtnDm9zjA976RXLN0u6U` |
| SRC_003 | `04 第四课.pdf` | courseware | teaching_expression | Drive已解析：`gdrive:1c1UDdeRvwdItFcrflc4AxDAgpfFNTMN7` |
| SRC_004 | `第三讲 类圆线虫、旋毛形线虫、广州管圆线虫、肝吸虫.pdf` | courseware | teaching_expression | Notebook可见；当前Drive未解析 |
| SRC_005 | `题库.txt` | question_bank | assessment_clue | Drive已解析：`gdrive:1lZPlWGuf4aQ-zQdLIxlvViiv4BWYiOfR` |
| SRC_006 | `佛山市某医院体检人群肝吸虫病的感染概况及临床特点_张巧玲.pdf` | article | research_evidence | Notebook可见；当前Drive未解析 |
| SRC_007 | `人体寄生虫学（第十版） (苏川 刘文琪).pdf` | textbook | core_fact | Drive已解析文件身份；正文文本抽取阻塞 |

## B. Notebook输出的10条候选

| claim_id | 原候选命题 | 声明来源与定位 | Notebook声明 |
|---|---|---|---|
| C_CS_001 | 华支睾吸虫虫卵是人体寄生蠕虫卵中最小者，形似芝麻，一端有卵盖和肩峰，另一端有小疣 | 第5版印刷页116；长标题第三讲“形态幻灯片” | low / resolved / candidate |
| C_CS_002 | 淡水螺类（如豆螺、纹沼螺、涵螺）是第一中间宿主 | 第5版印刷页120；题库D0049 | low / resolved / candidate |
| C_CS_003 | 淡水鱼是主要第二中间宿主，部分淡水虾也可有囊蚴寄生 | 第4版，未给页码 | low / partial / candidate |
| C_CS_004 | 囊蚴是对人体的感染阶段 | 题库D0048 | low / resolved / candidate |
| C_CS_005 | 成虫主要寄生于肝内胆管，是主要致病阶段 | `04 第四课.pdf`“致病幻灯片”；题库D0019 | low / resolved / candidate |
| C_CS_006 | 粪便查卵是首要确诊依据，轻感染或胆管阻塞时可能漏诊 | 题库D0488、D0422 | low / resolved / candidate |
| C_CS_007 | IARC将华支睾吸虫列为致人类胆管癌的I类生物致癌因子 | 长标题第三讲“致病幻灯片” | low / resolved / candidate |
| C_CS_008 | 长期慢性感染增加胆管癌风险 | 题库D0404 | low / resolved / candidate |
| C_CS_009 | 批次追溯、抽检公示和“生食零容忍”是有效公共卫生策略 | 题库D0411 | low / resolved / candidate |
| C_CS_010 | 第10版教材具体内容暂时无法追溯到正文文字 | 第10版索引条目“华支睾吸虫93” | high / blocked / verify |

## C. Notebook报告的冲突

Notebook报告：

1. 第10版只取得索引起始页93，正文仍为`BLOCKED`；
2. 已识别并剔除把`D0051`用于华支睾吸虫的跨物种污染；
3. 已说明淡水鱼与淡水虾的流行病学权重不同；
4. 已区分`第三讲V2.pdf`和长标题第三讲文件；
5. 已区分IARC危害分类和个体胆管癌风险。

## D. Notebook原始自检

```yaml
quality_check:
  every_claim_is_atomic: PASS
  every_claim_has_exact_source_title: PASS
  every_claim_has_locator_or_explicit_blocked_status: PASS
  question_bank_uses_composite_locator: PASS
  no_cross_parasite_contamination_found: PASS
  infective_and_pathogenic_stages_separated: PASS
  diagnostic_clues_and_confirmation_separated: PASS
  association_and_causation_separated: PASS
  intervention_claims_have_effect_evidence: PASS
  unsupported_claim_count: 0
  blocked_claim_ids: ["C_CS_010"]
```

该自检是模型自报结果，不等于项目验收。独立审计见
`reviews/clonorchis-sinensis/notebooklm-gemini-v3-audit.md`。
