# Route B prompt v1.2

Use only the private Drive folder whose manifest declares
`pack_id: clonorchis_phase3_private_pack_v1_2`.

Read:

- `CONTROL_source-pack-manifest-v1.2.md`
- `CONTROL_extraction-protocol-v1.2.md`
- `CONTROL_candidate-template-v1.2.md`

Execute Phase 3 Route B for *Clonorchis sinensis* in a clean context. Do not read
`candidates/`, `reviews/`, Route A output, prior NotebookLM answers, earlier candidate
discussions, archive files, verification-copy PDFs, supplemental files, or Phase 4
authority files.

Use:

```yaml
execution_scope: PREFLIGHT_ONLY
```

Perform only the protocol preflight. A runtime field that cannot be observed is
`not_observable`, not `confirmed`. Stop after `source_manifest` and
`preflight_conclusion`.

Do not extract or write
`phase3/clonorchis-sinensis/route-b-independent-candidates.yml` until PR #4 is merged and
the teacher explicitly changes the execution scope to `EXTRACTION`.
