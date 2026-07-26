# Phase 5第一批派生图数据与入库验收

日期：2026-07-26

## 结论

验收通过。PR #7批准的14个`reviewed`实体和10条`reviewed`关系，已经确定性生成
14个节点、10条边和10条平面三元组。派生结果没有混入第二、三批命题，也没有改变
面向学生的RAG发布边界。

本结论表示第一批派生图数据已具备随本PR进入主分支的技术条件；在本PR合并前，
状态仍为`READY_PENDING_PR_MERGE`。

## 派生文件

目录：`derived/clonorchis-sinensis/phase5-batch1/`

- `nodes.jsonl`：14个节点；
- `edges.jsonl`：10条带证据和限定的边；
- `triples.csv`：10条便于交换和浏览的扁平关系；
- `manifest.yml`：输入、数量、文件哈希和发布边界。

所有派生文件均由`scripts/build_derived_graph.py`从正式Markdown生成。正式
Markdown仍是权威主数据，不直接编辑JSONL或CSV。

## 验收项目

- 派生文件可逐字节确定性重建；
- 节点ID与P5-B1批准的14个实体完全一致；
- 边的`source_atom_id`与批准的10条命题完全一致；
- 节点和边状态均为`reviewed`；
- 每条边引用的来源均已登记；
- `triples.csv`与`edges.jsonl`关系集合一致；
- 第二、三批命题零混入；
- 未发现本地私有目录或下载路径泄漏。

机器可读验收凭证见
`phase5/clonorchis-sinensis/batch1-intake-validation.yml`。

## 未随本次放行

- P5-B2和P5-B3仍为`NOT_AUTHORIZED`；
- 学生RAG仍为`NOT_AUTHORIZED_PENDING_PHASE6`；
- 本次没有新增或改写医学事实，只转换PR #7已经批准的正式内容。
