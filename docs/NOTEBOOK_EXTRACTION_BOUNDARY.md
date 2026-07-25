# Notebook知识图谱候选提取边界

版本：`v1.1`  
修订日期：2026-07-25  
适用范围：华支睾吸虫试点及后续寄生虫Notebook候选提取

## 一、用途

Notebook可以使用比当前Drive更多的资料，但只能生成候选语料。新增资料必须先
交付可识别来源和稳定定位，经过登记与审核后才能支撑正式知识。

## 二、来源准入

每份Notebook来源除完整显示标题外，还必须声明：

```yaml
availability_class: drive|public_url|doi|notebook_only
stable_locator: null
```

- `drive`必须提供可核实Drive文件ID；
- `public_url`必须提供稳定页面URL；
- `doi`必须提供DOI；
- `notebook_only`只能作为来源候选，不能使`traceability_status`变成`resolved`。

相似文件、不同版次和相近课件不得相互替代。

## 三、命题准入

命题标为`candidate`必须同时满足：

1. 一个命题只含一个主关系；
2. 至少有一份`core_fact`、`research_evidence`或正式权威来源直接支持；
3. 有数字页码、PDF页序、幻灯片编号、章节条款或稳定网页锚点；
4. 来源角色能够证明该类型的结论；
5. 没有把来源状态、抽取失败或工作说明写成医学命题。

出现以下情况必须拆分：

- 同时出现“和、及、并、但”，且连接两个可独立判断；
- 同时包含宿主与感染阶段；
- 同时包含寄生部位与致病机制；
- 同时包含诊断方法与敏感性/鉴别限制；
- 同时包含干预措施与效果评价。

`statement_type`不得为`null`。来源质量问题必须进入`source_quality`，不能占用
`claim_id`。

## 四、证据角色硬限制

| 来源角色 | 可以证明 | 不能单独证明 |
|---|---|---|
| core_fact | 教材范围内的基础事实 | 最新指南、具体政策效果 |
| research_evidence | 研究设计实际观察到的结果 | 超出研究地区和人群的普遍结论 |
| teaching_expression | 课堂表达和教学重点 | 更新诊疗结论、流行数字、干预效果 |
| assessment_clue | 曾考什么、干扰项和易错点 | 医学事实、指南建议、治理效果 |
| intervention_hypothesis | 待验证措施 | “有效”“优于”“能够降低”等效果结论 |

题库的题干、答案、选项和解析属于同一考核来源，不能相互充当独立证据。
“题库说某措施有效”不构成干预效果证据。

## 五、定位硬限制

`traceability_status: resolved`要求：

- 教材/论文：数字印刷页码或PDF页序；
- 课件：数字幻灯片编号或PDF页序；
- 网页：完整稳定URL和访问日期；
- 题库：由原始数据生成的复合定位。

“形态幻灯片”“致病幻灯片”“文献引言区”“截图”等描述不能标为`resolved`。

题库复合定位的字段含义固定为：

```yaml
question_locator:
  source_file: "原始题目文件名，不是汇总文件题库.txt"
  sheet_name: "原始工作表名"
  item_no_in_file: "原始文件内题号"
  dedup_id: "Dxxxx"
```

题库定位由外部程序反查生成。Notebook只提供`dedup_id`时，应标记`partial`，
不得自行猜测其他字段。

## 六、自检不得自证

Notebook的自检只是一份待审声明。以下规则必须逐条计算：

- 任一命题含两个主关系，`every_claim_is_atomic`必须为`FAIL`；
- 任一Notebook-only来源被标为resolved，来源定位检查必须为`FAIL`；
- 任一题库字段值错位，复合定位检查必须为`FAIL`；
- 任一干预效果仅由题库、课件或干预假设支持，效果证据检查必须为`FAIL`；
- 任一`statement_type: null`，命题类型检查必须为`FAIL`；
- 某类命题未输出时，相关检查应为`NOT_APPLICABLE`，不得填`PASS`。

## 七、正式流转

Notebook输出按以下路径处理：

> Notebook候选 → 外部来源解析 → 题库程序反查 → 权威来源复核 →
> 独立文件提取对照 → 教师审核 → 正式知识层

Notebook自检全部PASS不自动触发入库，也不替代教师审核。
