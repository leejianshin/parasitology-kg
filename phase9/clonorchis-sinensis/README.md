# Phase 9-A：受控RAG运行合同设计原子

P9-A只冻结学生端受控RAG的接口、证据、拒答、审计和发布门禁，不实现模型调用、
检索服务、网页、学习通集成或真实学生发布。

## 权威输入

- Git基线：`9a9ff5a17de0fc6d32595730f10dfbebd55d9897`
- 正式知识：`derived/clonorchis-sinensis/pcms-v1/`
- 正式来源登记：`sources/registry.yml`
- 结构化叙述证据：
  `phase7/clonorchis-sinensis/pilot-content-minimum-set-authority-review.yml`

运行时不得读取候选稿、教师原始回件、平台自动生成内容、学生数据、外部网页或
模型既有记忆来补齐答案。

## 本原子交付

- `runtime-contract.yml`：运行状态机、证据白名单、回答处置和硬失败；
- `runtime-bundle-manifest.yml`：逐文件冻结运行证据包的大小、SHA256、
  Git blob和来源提交；
- `response-schema.yml`：学生可见回答信封；
- `audit-log-schema.yml`：逐次运行的机器审计记录；
- `reviewer-evidence-admission.yml`：去标识化复核证据的准入与排除；
- `release-boundary.yml`：实现、试用和发布授权边界；
- `acceptance-cases/plan.yml`：从PCMS v1回归迁移的固定验收用例；
- `acceptance-cases/adjudication-cases.yml`及记录Schema：冻结关键教师分歧及
  课程负责人裁决边界；
- `scripts/validate_phase9_contract.py`及单元测试：自动门禁。

## 核心规则

1. 只允许`ANSWER`、`PARTIAL`、`ABSTAIN`三种处置。
2. 每项学生可见医学主张都必须绑定已审核`claim_id`，并显示登记的
   `source_id`和定位信息。
3. 后端日志中存在来源ID不等于学生已经获得可见来源。
4. 线索不得升级为确证，关联不得升级为因果，推荐不得升级为量化疗效。
5. 缺少知识覆盖、必要限定语、合法来源或有效ID时必须关闭式失败。
6. 任何医学硬失败、未裁决关键分歧或学生数据泄漏都阻止发布。
7. 启动前必须逐文件验证运行证据包；响应和审计必须依次通过JSON Schema与
   跨字段语义校验。
8. `ANSWER/PARTIAL`必须通过校验且每项实质命题均有合法可见引用；
   未验证权威状态只能关闭式拒答。

## 当前边界

状态为`P9A_REVISED_PENDING_REREVIEW`。这表示合同已按首轮独立复审意见修订，
正等待再次独立只读复审；不表示P9-A已经关闭，不表示运行时已经实现，也不表示
任何学生试点或发布已经获准。
