# 路线A：NotebookLM/Gemini私有语料包提取Prompt

## 使用前设置

新建一个专用Notebook。只添加Drive私有语料包
`clonorchis_phase3_private_pack_v1_1`中的文件，不复用当前含202个来源的Notebook。

私有语料包根目录：
`https://drive.google.com/drive/folders/10dZDxrgI0oZhhGhrWq6swSJvO-KrNvXh`

先添加`00_CONTROL`中的清单、协议、模板和本Prompt，再添加`01_EVIDENCE`
中的4个证据文件。不要添加`02_SUPPLEMENTAL_PENDING`或
`03_PHASE4_AUTHORITY`中的文件。

## Prompt

你正在执行华支睾吸虫知识图谱Phase 3路线A候选提取。

本次不是总结教材，不是生成教学文章，也不是回答医学问题。你只能从
`pack_id: clonorchis_phase3_private_pack_v1_1`的4个证据文件及限定范围中
抽取可追溯的原子命题。不得复用任何既往候选、自检结论或对话答案。

先读取`CONTROL_source-pack-manifest-v1.1.md`、
`CONTROL_extraction-protocol-v1.1.md`和
`CONTROL_candidate-template-v1.1.md`。首先核对`pack_id`及4个证据文件的
精确文件名、Drive ID和限定范围。只要有一项不一致，就输出：

```yaml
source_manifest:
  status: FAIL
```

随后列出不一致项并停止，不得继续抽取事实。不得因为第4版页图或Phase 4权威
核查来源未加入而失败，因为它们不属于Phase 3硬门。

全部通过后，严格按照包内模板与共享协议输出。包内协议优先于本文件的简写。

1. 每条命题只有一个主语—关系—宾语判断；出现两个独立判断必须拆分。
2. 不预设需要多少条；无直接证据的类别可以为空，不为完整性而补写。
3. E01可以支撑其页内直接陈述的核心事实；E02只记录教学表达，E03只记录
   课程边界，E04只记录考点，后三者不得单独证明医学事实、最新诊疗或干预效果。
4. 每条命题至少给出一个稳定定位：数字印刷页码、PDF页序、章节条款或
   题库复合定位。
5. 不把“来源无法提取”“系统未找到正文”等质控信息写成医学命题。
6. 明确区分感染阶段与致病阶段、诊断依据与辅助线索、危险因素与必然因果、
   防控原则与干预效果。
7. One Health关系必须由来源实际支持；不得为了形成闭环而补写因果箭头。
8. 不复制长段原文。`evidence_basis`只写简短释义和定位。
9. 题库必须使用派生TSV已提供的“来源文件+来源工作表+题号_文件内+去重ID”
   复合定位。
10. 所有内容均为候选，不得标记为正式批准或已入库。

最后独立输出：

- `source_quality`
- `omissions`
- `conflicts`
- `schema_issues`
- `quality_check`

自检必须按实际输出计算。不存在某类命题时填`NOT_APPLICABLE`，不得为了得到
全PASS而改变判定。
