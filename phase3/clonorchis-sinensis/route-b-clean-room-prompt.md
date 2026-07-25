# 路线B：独立文件提取任务

## 隔离前提

本任务必须在没有读取以下内容的新上下文中执行：

- `candidates/`
- `reviews/`
- 路线A输出
- 本项目既往Notebook/Gemini候选答案

允许读取的只有：

- `sources/registry.yml`
- `schema/`
- `docs/PROJECT_SCOPE.md`
- `docs/EDITORIAL_GUIDE.md`
- `docs/NOTEBOOK_EXTRACTION_BOUNDARY.md`
- 本目录的`extraction-contract.yml`与`candidate-template.yml`
- 9个冻结原始来源及其限定范围

## 执行指令

从9个冻结来源中独立抽取华支睾吸虫候选命题。先核对来源清单；任一必需来源
不可访问或范围不一致时，输出`SOURCE_MANIFEST_FAIL`并停止。

通过后严格按`candidate-template.yml`生成结果，执行与路线A相同的十项规则：

1. 一个命题只含一个主关系；
2. 不预设数量，不为填满类别而补写；
3. 证据角色必须适配命题类型；
4. 每条命题必须有稳定定位；
5. 来源质控与医学命题分开；
6. 感染阶段、致病阶段、诊断依据、辅助线索分别表达；
7. 相关性、危险增加、机制和必然因果分别表达；
8. One Health联系必须有来源，不拼装闭环；
9. 题库只作考核线索，复合定位由程序生成；
10. 只输出候选，不写入正式知识目录。

保存为：

`phase3/clonorchis-sinensis/route-b-independent-candidates.yml`

完成前不得读取路线A结果。两条路线的比较只在Phase 4开始。
