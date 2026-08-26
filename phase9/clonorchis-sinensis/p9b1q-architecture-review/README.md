# P9-B1Q architecture review

Status: current frozen R3 evidence-package candidate, pending final independent
read-only re-review. Correction base: `e8d8c55e66c7b3a6b39967c2f6d0572082d2686f`.
The candidate SHA is the Git commit containing this README and its
manifest-bound bytes.

This atom freezes `6ac0e4b2978e5fb41e7b90e27ced17826d35a394` unchanged and
replaces the next implementation direction—not the frozen code—with a four-stage
deterministic semantic compiler:

```text
Clause AST → Event Frame → Typed Constraint Solver → QueryIR
```

The review concludes that R10 exposed a representation failure rather than a small
lexicon gap. The frozen implementation was deterministic and Schema-valid, but it
collapsed clause attachment, entity resolution, assertion scope, event identity,
ambiguity, and relation licensing while directly constructing QueryIR. That makes
semantic errors stable instead of making them correct.

## Deliverables

- `architecture-review-v1.yml`: frozen baseline, evidence boundary, root causes,
  architecture decision, and closure gates.
- `clause-ast-schema-candidate.yml`: exact spans, clause operators, assertion
  markers, surface mention candidate domains, and attachment alternatives.
- `event-frame-schema-candidate.yml`: typed participants, event-specific
  assertion/polarity, diagnostic binding, identity, reference, and override hypotheses.
- `typed-constraint-result-schema-candidate.yml`: UNIQUE/AMBIGUOUS/UNSUPPORTED/
  INVALID result with proof or ambiguity artifacts.
- `typed-constraint-solver-contract.yml`: joint constraints, cardinality semantics,
  inclusion minimality, license DAG, and fail-closed rules.
- `compiler-pipeline-contract.yml`: content-addressed stage boundaries, pure QueryIR
  emission, runtime binding, tests, and implementation slices.
- `failure-to-stage-matrix.yml`: maps aggregate R10 failure classes to the first
  authoritative compiler stage; later stages may reject but never repair them.
- `normalized-request-schema-candidate.yml` and `clause-grammar-config.yml`:
  lossless S0 normalization and the structural-only S1 grammar authority.
- `stage-semantic-validator-contract.yml` and its result Schema: executable,
  fail-closed S0–S5 validation over actual content-addressed objects.
- `constraint-id-registry.yml`, its Schema, and `constraint-set-v0.1.yml`:
  the complete 46-check validation order with no dynamically invented rules.
- `negation_semantic_authority.py` and `negation-surface-scope-authority.yml`:
  the single source of marker surface, AST scope, target type, composition, and
  assertion derivation truth consumed by both the standalone R3-B harness and
  authoritative S1/S3 validators.
- `queryir-emission-record-schema-candidate.yml`: the UNIQUE solution's complete
  QueryIR, pointer-complete field trace, rooted license DAG, and removal-based
  minimality witness.
- `object-canonicalization-and-hash-chain.yml`: per-object canonicalization and
  the request → AST → frame → solution → QueryIR → audit hash chain.
- `fixtures/`: positive actual objects plus isolated RFC 6902 negative mutations
  for every S0–S5 stage.
- `minimality-proof-schema-candidate.yml`: independently persisted semantic
  universe plus eight replayable single-removal probes.
- `execution-binding-sidecar-architecture-schema-candidate.yml`: a complete S5
  positive chain binding 48 actual objects and five stage PASS results.
- `design-manifest.yml`: the current raw-byte review inventory for the corrected
  design, fixtures, and protected implementation/P9-A boundary.
- `reference-stage-semantic-validator.py`: a deterministic, review-only
  executable that validates nine main positives plus four integrated R3-B
  positives, replays all eight minimality removals through the same semantic
  predicate, executes 37 stage negatives plus fourteen integrated R3-B
  negatives, and rejects a non-sidecar object-store index entry that drifts
  from S5 material authority. The separately executed R3-A set contains sixteen
  negatives, so the complete formal negative inventory is 67 cases
  (37 stage + 16 R3-A + 14 R3-B); the integrated reference summary contains 51.
- `fixtures/reference-validator-execution-summary.json` and its Schema: the
  byte-identical three-run result binding the actual executable and contract.

The corrected evidence set passes strict Draft 2020-12 compilation for all twelve
local candidate Schemas, validates 27 positive fixtures, resolves all 189 QueryIR
field traces to persisted source objects, and executes 13 integrated positive,
8 minimality, and 51 integrated negative gates in three byte-identical runs.
All review JSON actual objects are stored in their exact canonical bytes.

## Boundaries

- No existing implementation, test, P9-A contract, authority projection, or
  retrieval index is changed.
- No model or network call is introduced.
- No R10 secret case body is copied into the repository.
- R10 is now confidential diagnostic regression evidence, not a final unseen
  held-out set, because its aggregate failures informed this design.
- No push, PR, P9-B2 work, or student release is authorized by this atom.

## Required next sequence

1. Conduct an independent read-only review of this design atom.
2. If it passes, freeze and persist a new independent R11 held-out suite before
   any compiler implementation.
3. Implement and test the stages separately: Clause AST, Event Frame, solver,
   pure QueryIR emitter, then runtime binding.
4. Let the original independent holder execute R11. Any failure returns to the
   owning representation stage; it must not trigger another lexical patch cycle.
