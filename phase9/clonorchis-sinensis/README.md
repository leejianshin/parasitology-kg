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
- `request-schema.yml`：进入检索前必须验证并冻结哈希的请求对象；
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
9. 模型不得另写自由最终答案。模型输出只包含结构化`answer_units`；医学主张
   单元必须绑定唯一正式主张及合法引用，覆盖缺口单元只允许使用冻结枚举。
   学生可见`answer_text`由系统从正式主张文本和固定边界语句确定性生成。
10. `ANSWER`、`PARTIAL`及任何带非空响应哈希的审计记录必须同时提交实际响应
    对象进行跨对象校验，禁止仅凭格式合法的哈希形成孤立审计记录。
11. 每一条审计记录（包括关闭式拒答）都必须同时提交实际请求对象；系统先按
    冻结请求Schema校验，再以排序UTF-8 JSON、无无意义空白的规范形式计算
    `request_sha256`，并同时核对请求、响应与审计中的`request_id`。

## 当前边界

状态为`P9A_CLOSED`。最终独立只读复验结论为`PASS`，课程负责人已批准关闭
P9-A并将合同合入主线。该状态只表示设计合同已经冻结；不表示运行时已经实现，
不表示P9-B1已经启动，也不表示任何学生试点或发布已经获准。

## P9-B1本地证据检索核心

P9-B1已获单独授权并完成第一修订原子的本地实现，当前状态为
`LOCAL_TESTS_PASS_PENDING_INDEPENDENT_READ_ONLY_REVIEW`。实现只读取P9-A冻结的
四个运行输入，不调用模型、网络、外部网页或学生数据。

第一修订关闭了调用方注入索引的公开入口：每次`retrieve`与`validate_result`
都重新核验运行证据包、控制文件和索引。结果先完整执行冻结Schema，再逐字段与
重新计算的请求、索引、排序、实体、来源和定位比对；关系候选保留
`subject/predicate/object`方向。

验收包括16个原固定回归、8个独立等义改写、伪造索引、畸形结果、来源/实体/
定位篡改、方向反转、排序篡改和控制文件篡改。详见
`p9b1-local-acceptance.yml`。当前不得推送、创建PR、启动P9-B2或学生发布。
