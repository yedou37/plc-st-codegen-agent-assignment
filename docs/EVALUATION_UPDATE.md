# Compiler and oracle update

This revision changes new executions only. The 120-cell matrix, ST attempts,
compiler logs, runtime summaries and supplementary verification logs are kept
as historical records. No new model API calls were made.

## Changes

- The original compiler attached only PROGRAMs to a task; the post-hoc adapter
  attached no candidate. Both entry points now share a caller that references
  every PROGRAM, FUNCTION_BLOCK and FUNCTION. Input and IN_OUT ports receive
  typed storage. Open-array ports keep their declarations; the compile-only
  caller supplies a two-element array per dimension. This fixture establishes
  a call, not a functional test. VARIANT / ANY / reference bindings requiring
  a specialized fixture return UNAVAILABLE instead of silently changing type.
- Complete top-level POU endings are required. The archived truncated P11
  example now fails before project creation. CODESYS still checks body syntax;
  this source check is not used as a successful compilation substitute.
- Compiler JSON states survive the process boundary. Previously seven first
  UNAVAILABLE records and one TIMEOUT were reported as FAIL in the matrix.
  Missing or contradictory structured success is now UNAVAILABLE. External
  non-JSON compilers can explicitly set compiler.result_format to exit_code.
- P04-L4 relates the post-call accumulator to its pre-call value. P07-L4 limits
  the three-pump rule to automatic mode. The dataset version is 1.1; the old
  model input is preserved in dataset/archive/tasks_v1.json.
- P07-T2 keeps start TRUE. P04 tests now check accumulation and preservation
  after every call, including the stopped state, and latch a failed invariant.
  P01 inactive-actuator expectations are separated under expect_assumption;
  the default runner scores only requirement-derived expect assertions.

Suites remain ordered sequences with one instance per suite. This revision
does not turn them into independent fresh-instance experiments. P06 keeps the
existing timing slack; its counts do not establish exact 5-second boundaries.

## Validation

Run `python -m unittest discover -s tests -v`. The offline suite covers status
propagation, missing success records, typed caller generation for all three
POU kinds, generated script syntax, the truncated-source regression, dataset
versioning, optional expectations and per-scan invariant instrumentation.

On a machine with CODESYS installed, run:

```powershell
python tools/validate_compiler_controls.py
python tools/posthoc_recheck_failures.py --output-dir experiments/local_runs/reachable_recheck
```

The first command requires a complete valid FB to PASS and a complete FB with
an invalid assignment to FAIL. It must report controls_passed=true before
using the adapter to produce new compilation metrics. This review machine
has no CODESYS installation; both controls returned UNAVAILABLE, so a native
CODESYS validation and updated full-matrix rates are still pending.

Saved-source rechecks do not require model API spending. Rebuild every final
candidate using the same adapter before reporting a new whole-matrix rate;
also rebuild first attempts when comparing repair gains. Keep the historical
and new metrics in separate output files. Preserve original tool-failure and
timeout categories rather than changing old CSV rows retroactively.
