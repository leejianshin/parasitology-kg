# 路线B：同包独立文件提取任务

## 隔离前提

本任务必须在没有读取以下内容的新上下文中执行：

- `candidates/`
- `reviews/`
- 路线A输出
- 本项目既往Notebook/Gemini候选答案

允许读取的只有：

- 私有Drive语料包`clonorchis_phase3_private_pack_v1_1`
- 包内`00_CONTROL`控制文件
- 包内`01_EVIDENCE`的4个证据文件
- 仓库的`schema/`、`docs/PROJECT_SCOPE.md`和`docs/EDITORIAL_GUIDE.md`

不得读取`02_SUPPLEMENTAL_PENDING`、`03_PHASE4_AUTHORITY`或包外原始来源。

## 执行指令

先读取Drive文件`CONTROL_source-pack-manifest-v1.1.md`
（ID `1GIlXXid63SMXXW2APwonmxVrlK9T1W2n`）。核对`pack_id`、4个证据文件的
精确文件名、Drive ID和限定范围；任一不一致时输出`SOURCE_MANIFEST_FAIL`
并停止。不得把故意延后的补充来源或Phase 4权威核查当成缺失来源。

通过后严格按包内共享协议和模板生成结果，执行与路线A相同的十项规则：

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
