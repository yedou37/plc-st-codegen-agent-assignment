# Post-hoc CODESYS recheck

> Historical diagnostics. This adapter did not call each candidate. Use the [linked rebuild of all 120 outputs](../linked_compile_review/summary.json) for the current offline assessment.

The original experiment matrix remains unchanged in `../results.csv`: it
records 90 PASS and 30 FAIL under the first compiler adapter. The compiler
adapter had four project-input issues that could report valid ST as failed:

1. Markdown code fences around source were included in the compiler input.
2. The generated project did not reference CODESYS Standard 3.5.22.0, so
   standard symbols such as `TON`, `R_TRIG`, and `LEN` were unresolved.
3. The P07 and P17 task-defined record types were missing from the project.
4. Programs with `VAR_IN_OUT` were placed directly on a task without binding an
   actual argument.

`tools/posthoc_recheck_failures.py` recompiles all 30 original FAIL sources
using `tools/codesys_compile_posthoc.py`. The compile-only input removes
Markdown fences, includes the Standard library, adds the task-defined DUTs,
and builds each POU without a task call. It does not modify the source ST.

## Result

- Original failed cells rechecked: 30/30.
- Post-hoc offline CODESYS compile: 30 PASS, 0 FAIL, 0 TIMEOUT.
- Source hashes unchanged: yes.
- Combined evidence: 90 original PASS plus 30 post-hoc PASS means every one of
  the 120 source artifacts has at least one recorded offline compile PASS.

The combined 120/120 count is not a uniform rebuild of all cells with the new
adapter. The original experimental metric remains 90/120 and is retained for
reproducibility. A compiler PASS checks ST project compilation only; it does
not establish runtime behavior, full task invocation wiring, or LTL
correctness. P07 and P17 support DUTs are delivered in `st/support_types/`.

Evidence is in `recheck.csv`, `summary.json`, and one compiler JSON log per
original failed cell in `codesys_logs/`.

To repeat the 30-cell pass without overwriting this archived evidence, run from
the repository root:

```powershell
py tools/posthoc_recheck_failures.py `
  --output-dir experiments/local_runs/posthoc_repair
```

This requires the same CODESYS installation/profile. The script reads the
committed matrix and source files and writes the rerun into the ignored
`experiments/local_runs/` directory.
