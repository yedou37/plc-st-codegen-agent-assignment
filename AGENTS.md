# Instructions for coding agents

This repository is a coursework benchmark with audited experimental evidence. Read `README.md`, `docs/REPRODUCING.md`, `experiments/protocol.md`, and `验收对照表.md` before changing code or interpreting results.

## Preserve the evidence

- Treat `experiments/results.csv`, `experiments/results_summary.json`, `st/runs/`, `experiments/codesys_validation/`, `experiments/posthoc_repair/`, `experiments/functional_tests/`, and `experiments/formal_verification/` as historical evidence. Do not regenerate them in place.
- Put any new run output under `experiments/local_runs/`; Git ignores that directory. `experiments/run_matrix.py` defaults output CSVs and ST/compiler artifacts there. `tools/posthoc_recheck_failures.py` defaults to an ignored local output directory.
- `tools/finalize_matrix.py` also defaults to `experiments/local_runs/finalized_matrix/`. Do not pass `--write-archive` unless the user explicitly asks to replace the official CSV and summary after reviewing the inputs.
- Keep the original matrix and post-hoc recheck as separate populations. Never report their combined count as a uniform run with one adapter.
- Use `experiments/linked_compile_review/` for the current offline evidence. The old build-only PASS records do not demonstrate candidate code generation. New runs go under `experiments/local_runs/`.
- An offline CODESYS compile PASS is not PLC runtime, scan-cycle, or LTL verification. The separate self-agent runtime suite covered 88/224 model-scenario executions and 56/112 distinct scenario IDs; see `experiments/codesys_validation/self_agent_runtime_20261110.md`. Do not describe this partial run as full runtime coverage.

## Credentials and costs

- Do not request, print, persist, or commit API keys. Model credentials are read from the process environment as `DMXAPI_API_KEY`.
- Do not call external model APIs unless the user explicitly asks for a new run and gives a cost cap. Start with a bounded pilot; state the budget cap and expected cell count before execution.
- Never place credentials in prompts, saved configs, command arguments, CSVs, or usage logs. Do not store prompts or model reasoning in this repository.

## Change and verification workflow

- Keep changes focused. Preserve source hashes for archived model outputs unless the user explicitly requests replacing the experiment.
- For code changes, inspect the diff and run the offline suite with `py -m unittest discover -s tests -v` when the user requests verification. Do not infer that an unrun check passed.
- Do not claim all tasks passed from the P02 STruC++/CBMC bonus results; those checks cover P02 only.
- Before packaging, use `tools/package_submission.ps1`; it excludes `.git`, caches, `node_modules`, and QA PDFs.
