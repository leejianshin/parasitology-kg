# Schema说明

## 1. 设计目标

第一版Schema只覆盖华支睾吸虫试点及近期人体寄生虫学扩展所需的通用结构。它不是完整本体，也不追求一次性穷尽所有寄生虫学概念。

Schema需要同时满足：

- Markdown正文可以直接供学生阅读和语义RAG；
- YAML front matter可以被程序稳定解析；
- 实体和关系采用受控词表；
- 关键关系在关系级别绑定证据；
- 教师审核状态明确；
- 派生三元组可以重新生成，不需要人工双份维护。

## 2. 权威文件

| 文件 | 作用 |
|---|---|
| `entity-types.yml` | 实体类型、ID前缀和One Health领域 |
| `relation-types.yml` | 受控关系、方向、允许的主客体类型 |
| `source-types.yml` | 来源类型、来源角色和证据类型 |
| `templates/entity-template.md` | 单个实体的结构化Markdown模板 |
| `sources/registry.yml` | 实际使用来源的登记表 |

当前受控关系目录版本为`relation-types.yml@1.1`。

## 3. 实体ID

实体ID采用：

```text
<类型前缀>.<ASCII小写snake_case名称>
```

示例：

```text
parasite.clonorchis_sinensis
stage.metacercaria
host.human
disease.clonorchiasis
environment.freshwater_aquaculture_water
```

规则：

- ID一经发布原则上不改变；
- 中文名、英文名、拉丁名和旧称作为标签或别名，不进入ID；
- 同一实体不能因来源或语言不同重复建档；
- 分类学修订通过别名、状态和变更记录处理。

## 4. 关系方向

仓库只保存`relation-types.yml`规定的规范方向。例如：

```text
parasite.clonorchis_sinensis
  --has_second_intermediate_host-->
host.freshwater_fish
```

不再手工保存相反方向的第二条边。查询系统可以根据`inverse_label_zh`显示“淡水鱼是华支睾吸虫的第二中间宿主”。

这样可以避免一条事实被维护两次后出现来源或状态不一致。

## 5. 关系级证据

来源不能只挂在整篇文档末尾。每条正式关系至少包含一项证据：

```yaml
relations:
  - predicate: has_second_intermediate_host
    object: host.freshwater_fish
    statement_zh: 华支睾吸虫以淡水鱼作为第二中间宿主。
    relation_status: reviewed
    evidence:
      - source_id: source.example_textbook
        locator: "第5章，第120页"
        evidence_type: direct_statement
    qualifiers: {}
```

`locator`必须尽量定位到页码、幻灯片、章节、表格或稳定网页段落。

## 6. One Health领域

实体可以归入一个或多个领域：

- `human_health`
- `animal_health`
- `environmental_health`
- `cross_sector_governance`

这些领域用于组织和筛选，不代替实体关系。不能仅因两个实体都带有One Health标签，就推断二者存在传播或因果关系。

## 7. 审核状态

实体和关系分别记录状态：

- `draft`：正在整理，尚未核对完成；
- `in_review`：已提交教师或维护者审核；
- `reviewed`：来源和教学口径已经批准；
- `disputed`：存在未解决冲突；
- `deprecated`：不再采用，但为保留历史而存在。

只有`reviewed`内容可以进入正式学生RAG发布版本。

## 8. 正文结构

每个正式实体文件至少包含：

- `## 核心知识`
- `## One Health联系`
- `## 学习提示`
- `## 证据边界`

不同实体可以增加形态、生活史、致病、诊断和防控等小节，但不能删除上述四个基础部分。

正文应使用完整、自足的句子，减少“它”“上述”等脱离上下文后无法理解的指代，以便RAG切分后仍然保持语义完整。

## 9. 诊断、病理与疾病关联边界

`relation-types.yml@1.1`增加4个受控关系：

- `has_diagnostic_clue`：疾病指向暴露行为、临床表现或辅助检查，仅表示诊断线索；
- `occurs_in`：病理过程指向发生部位；
- `has_complication`：疾病指向来源明确识别的并发症疾病；
- `epidemiologically_associated_with`：表达疾病之间的人群层面非因果关联。

这些关系不能互相替代：

- 诊断线索不得写成`diagnosed_by`所表达的诊断方法，更不得省略“不能单独确诊”等证据边界；
- 并发症关系不表示每名患者都会发生，也不自动证明直接因果；
- 流行病学关联不得改写为`causes`；
- “主要发生于”“少见”“特定地区”等内容必须保存在关系限定中。

情境化干预效果关系暂未进入受控词表。患病率、感染强度、知识、态度和自报行为等
研究结局需要独立的研究证据模型，并需要对地区、时期、人群、结局和研究设计实施
结构化校验；在该模型建立前只保留在研究证据层。
