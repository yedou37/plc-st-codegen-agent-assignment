"""Run the interface-matched archived ST outputs in the CODESYS IDE simulator."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from run_codesys_runtime_suite import (
    DEFAULT_PROFILE, ROOT, build_driver, find_codesys, prepare_candidate,
    runscript_source, runtime_timeout_ms, sha256,
)


IDE_BATCH = '''
import io, json, traceback
from scriptengine import system
with io.open(JOBS, "r", encoding="utf-8") as stream:
    jobs = json.load(stream)
for job in jobs:
    try:
        execfile(job["script"], {"__name__": "__main__"})
    except Exception:
        with io.open(job["result"], "w", encoding="utf-8") as stream:
            stream.write(unicode(json.dumps({"status":"HARNESS_ERROR", "error":traceback.format_exc()})))
system.exit(0)
'''


def prepare(record, path):
    source = ROOT / record["source"]
    raw = source.read_bytes()
    if sha256(raw) != record["source_sha256"]:
        raise ValueError(f"Source hash mismatch: {source}")
    task = record["task_id"]
    suite_path = ROOT / "tests/structured_text/runtime_suites" / f"{task}.json"
    suite_bytes = suite_path.read_bytes()
    suite = json.loads(suite_bytes)
    metadata = {
        **record, "source": source.relative_to(ROOT).as_posix(),
        "execution_target": "IDE simulation", "suite_sha256": sha256(suite_bytes),
        "planned_cases": len(suite["cases"]),
    }
    pous, duts = prepare_candidate(raw.decode("utf-8-sig"), task)
    primary = next(item for item in pous if item["kind"] != "FUNCTION")
    driver, assertions = build_driver(primary["name"], suite, pous)
    script, result = path / "test.py", path / "result.json"
    path.mkdir()
    script.write_text(runscript_source(pous, duts, driver, path / "test.project", result,
                                       True, runtime_timeout_ms(suite), assertions,
                                       suite, simulate=True, exit_on_failure=False), encoding="utf-8")
    metadata["driver_sha256"] = sha256(driver.encode("utf-8"))
    metadata["executed_script_sha256"] = sha256(script.read_bytes())
    return {"script": str(script), "result": str(result)}, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interfaces", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profile", default=os.environ.get("CODESYS_PROFILE", DEFAULT_PROFILE))
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT / "experiments/local_runs"):
        parser.error("--output-dir must be under experiments/local_runs")
    audit = json.loads(args.interfaces.read_text(encoding="utf-8"))
    matches = [row for row in audit["records"] if row["status"] == "MATCH"]
    if len(matches) != audit["matched"] or len({row["run_id"] for row in matches}) != len(matches):
        parser.error("Invalid interface audit")
    executable = find_codesys()
    output.mkdir(parents=True)
    entries = [prepare(record, output / record["run_id"]) for record in matches]
    with (output / "results.jsonl").open("x", encoding="utf-8") as report:
        for offset in range(0, len(entries), 10):
            batch = entries[offset:offset + 10]
            manifest = output / f"jobs_{offset}.json"
            manifest.write_text(json.dumps([job for job, _ in batch]), encoding="utf-8")
            script = output / f"sim_{offset}.py"
            script.write_text(f"JOBS = {str(manifest)!r}\n" + IDE_BATCH, encoding="utf-8")
            with (output / f"ide_{offset}.log").open("wb") as log:
                command = f'"{executable}" --profile="{args.profile}" --runscript="{script}" --noUI'
                try:
                    proc = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                          timeout=600, check=False)
                    unavailable = f"No candidate result (IDE exit code {proc.returncode})"
                except subprocess.TimeoutExpired:
                    unavailable = "No candidate result before the CODESYS process deadline"
            for job, metadata in batch:
                try:
                    row = json.loads(Path(job["result"]).read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    row = {"status": "NO_RESULT", "error": unavailable}
                row.update({k: v for k, v in metadata.items() if k not in {"status", "issues"}})
                report.write(json.dumps(row, ensure_ascii=False) + "\n")
                report.flush()
                print(f"{row['run_id']} {row['status']}", flush=True)


if __name__ == "__main__":
    main()
