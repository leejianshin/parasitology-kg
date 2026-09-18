# P10 scientific evaluation protocol

This directory publishes the protocol and authority artifacts for the P10
scientific evaluation of the frozen *Clonorchis sinensis* knowledge domain.
It does not publish benchmark question text, gold content, system outputs, or
the private Batch 0 package.

## Version boundary

- `SYSTEM_UNDER_EVALUATION`: `d77a76e6219482e1933e6377dfbad2151c829bef`
- `P10_PROTOCOL_DOCUMENTATION_BASE`: `7163840325abb62cba5fdca7bb9149b4b1c11a81`
- `P10_PROTOCOL_DOCUMENTATION_HEAD`: the Git commit containing this directory
- `P10_PROTOCOL_VERSION`: `P10_PROTOCOL_CAPACITY_CORRECTED_V2`

The P10 documentation commit is a research-protocol publication only. It is
not a new system version and does not mutate the system under evaluation.

## Frozen public identities

| Artifact | SHA-256 |
|---|---|
| P10 AEM V1 | `ff12f479af5e367ada38bad02c89e255a88ca26cd45efd5cd9086ae5c6acdc93` |
| Tier/area/semantic-tag matrix | `9466c949924e190e18453e3a6c54d26b6b35be5e50140f261313a011841e99cb` |
| Slot allocation | `151b533be8b516fbc920003fcc3b24f3603e229e024888e0e3e9f15151b8fb46` |
| Authority-cluster register | `45ccff36347351e46f7c7a3b8814c5c8dea076c9d00caa783ea9ea54aeabf006` |
| Pre-authoring package | `66ee7aa615f76ee7290184765240300f9927b5c327754a077143591a91c6adbd` |
| Private Batch 0 package commitment | `c9704e8c08d8790f09a1144956c633314deaf53b2d60d1f7f384f26313b65727` |

## Design state

- Total benchmark capacity: 209 questions (`T1=20`, `T2=131`, `T3=58`).
- Confirmatory family after capacity correction: `C4` only.
- `C1`, `C2`, `C3`, and `C5` are estimation-only.
- Batch 0: 15 items, privately retained; only its cryptographic commitment is public.
- A/B/C/D have not been executed and no system outcomes exist.

Public files under `benchmark/commitments/` are commitments, not benchmark
content. Disclosure of private questions or gold objects before evaluation
closure is prohibited.
