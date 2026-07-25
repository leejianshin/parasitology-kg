# 正式知识目录

此目录只保存按照当前Schema编写的结构化Markdown实体。

规则：

- AI或NotebookLM原始输出不得直接放入本目录；
- 每个实体一个文件；
- 每条关系至少绑定一项来源和定位；
- 关系目标必须是已存在或同一变更中新增的实体；
- 只有`reviewed`实体可以进入面向学生发布的RAG版本；
- `README.md`不作为实体参与校验。

建议按实体类型分目录，例如：

```text
knowledge/
├── parasites/
├── life-cycle-stages/
├── hosts/
├── diseases/
├── environments/
├── behaviors/
├── diagnostics/
├── treatments/
└── interventions/
```
