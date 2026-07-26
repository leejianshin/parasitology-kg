# Route A prompt v1.2

Create or use the dedicated NotebookLM notebook containing exactly eight sources from
`clonorchis_phase3_private_pack_v1_2`: the four Route A control files and E01–E04.
Do not reuse the 202-source notebook.

Read:

- `CONTROL_source-pack-manifest-v1.2.md`
- `CONTROL_extraction-protocol-v1.2.md`
- `CONTROL_candidate-template-v1.2.md`

Do not add the Route B prompt, archive files, verification-copy PDFs, supplemental files,
Phase 4 authority files, prior candidates, reviews, or saved notes.

Execute Phase 3 Route A for *Clonorchis sinensis* with:

```yaml
execution_scope: PREFLIGHT_ONLY
```

Perform only the protocol preflight. If Drive file IDs or SHA256 values are not exposed
by NotebookLM, report them as `not_observable`; do not claim that they were confirmed.
If all observable checks pass, use `PASS_WITH_NOT_OBSERVABLE_FIELDS`. If a real mismatch
is found, use `FAIL` and list it.

Stop after `source_manifest` and `preflight_conclusion`. Do not extract or save candidate
claims until PR #4 is merged and the teacher explicitly changes the execution scope to
`EXTRACTION`.
