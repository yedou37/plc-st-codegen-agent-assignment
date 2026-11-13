"""Execute self-agent candidates that passed the linked offline build."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = {"deepseek-v4.1-flash-1017", "gpt-6.1-sol"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def latest_matching(task_id: str, source_hash: str, suite_hash: str) -> dict | None:
    base = ROOT / "experiments/local_runs/codesys_runtime_suite"
    runner_hash = sha256((ROOT / "tools/run_codesys_runtime_suite.py").read_bytes())
    for path in sorted(base.glob("*/result.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (result.get("task_id") == task_id and result.get("source_sha256") == source_hash
                and result.get("suite_sha256") == suite_hash
                and (result.get("runner_sha256") == runner_hash
                     or result.get("status") in ("RUNTIME_PASS", "RUNTIME_FAIL"))
                and result.get("run_requested") is True):
            return result
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", action="append", help="Limit to one or more task IDs")
    parser.add_argument("--model", action="append", help="Limit to a model ID")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--linked-results", type=Path, required=True,
                        help="diagnostics.jsonl from recheck_linked_matrix.py")
    args = parser.parse_args()
    if not os.environ.get("CODESYS_TEST_USER") or not os.environ.get("CODESYS_TEST_PASSWORD"):
        raise SystemExit("Set CODESYS_TEST_USER and CODESYS_TEST_PASSWORD only in this process environment.")
    filter_tasks = set(args.task or [])
    filter_models = set(args.model or MODELS)
    rows = list(csv.DictReader((ROOT / "experiments/results.csv").open(encoding="utf-8-sig", newline="")))
    linked = {record["run_id"]: record for record in (
        json.loads(line) for line in args.linked_results.read_text(encoding="utf-8").splitlines())}
    selected = [row for row in rows if row["framework"] == "Self-developed harness"
                and row["model_id"] in filter_models
                and (not filter_tasks or row["task_id"] in filter_tasks)]
    selected.sort(key=lambda row: (row["task_id"], row["model_id"]))
    batch_id = datetime.now().strftime("self_runtime_%Y%m%d_%H%M%S")
    base = ROOT / "experiments/local_runs/codesys_runtime_suite"
    base.mkdir(parents=True, exist_ok=True)
    progress_path = base / f"{batch_id}_progress.json"
    summary_path = base / f"{batch_id}_summary.json"
    records = []
    progress_path.write_text(json.dumps({"batch_id":batch_id, "current":0, "total":len(selected),
                                        "updated_at":datetime.now().isoformat(timespec="seconds"),
                                        "records":records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for index, row in enumerate(selected, start=1):
        task_id, model_id = row["task_id"], row["model_id"]
        source = ROOT / row["output_file"].replace("\\", "/")
        suite_path = ROOT / "tests/structured_text/runtime_suites" / f"{task_id}.json"
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        suite_hash, source_hash = sha256(suite_path.read_bytes()), sha256(source.read_bytes())
        record = {"task_id":task_id, "model_id":model_id, "official_compile_status":row["status"],
                  "source":str(source.relative_to(ROOT)), "source_sha256":source_hash,
                  "suite":str(suite_path.relative_to(ROOT)), "suite_sha256":suite_hash,
                  "scenario_total":len(suite["cases"])}
        progress_path.write_text(json.dumps({"batch_id":batch_id, "current":index, "total":len(selected),
                                             "active_candidate":f"{task_id} {model_id}",
                                             "updated_at":datetime.now().isoformat(timespec="seconds"),
                                             "records":records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        checked = linked.get(row["run_id"], {})
        eligible = (checked.get("status") == "PASS" and checked.get("source_sha256") == source_hash
                    and checked.get("boot_bytes", 0) > 0 and checked.get("signatures"))
        record["linked_compile_status"] = checked.get("status", "NOT_RUN")
        if not eligible:
            record.update({"status":"NOT_RUN_LINKED_BUILD_NOT_CONFIRMED", "scenario_executed":0,
                           "scenario_blocked":len(suite["cases"])})
        else:
            existing = latest_matching(task_id, source_hash, suite_hash)
            if existing:
                result = existing
                record["reused_result"] = result.get("project")
                artifact = latest_result_path(base, task_id, source_hash, suite_hash)
                if artifact:
                    record["result_artifact"] = str(artifact.relative_to(ROOT))
            else:
                command = [sys.executable, str(ROOT / "tools/run_codesys_runtime_suite.py"),
                           "--source", str(source), "--task-id", task_id,
                           "--suite", str(suite_path), "--run", "--timeout", str(args.timeout)]
                try:
                    proc = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True,
                                          encoding="mbcs", errors="replace", timeout=args.timeout + 60,
                                          check=False)
                    result_path = latest_result_path(base, task_id, source_hash, suite_hash)
                    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path else None
                    if result_path:
                        record["result_artifact"] = str(result_path.relative_to(ROOT))
                    if result is None:
                        record["runner_output"] = (proc.stdout or "")[-1500:]
                        record["runner_error"] = (proc.stderr or "")[-1500:]
                        record.update({"status":"NO_RESULT", "scenario_executed":0,
                                       "scenario_blocked":len(suite["cases"])})
                except subprocess.TimeoutExpired as exc:
                    result = None
                    record.update({"status":"BATCH_PROCESS_TIMEOUT", "scenario_executed":0,
                                   "scenario_blocked":len(suite["cases"]), "error":str(exc)[:1000]})
            if result is not None:
                record["runtime_result"] = result.get("status")
                record["result_path"] = result.get("project")
                runtime = result.get("runtime", {})
                record["scenario_executed"] = len(runtime.get("cases", []))
                record["scenario_blocked"] = max(0, len(suite["cases"]) - record["scenario_executed"])
                record["scenario_passed"] = int(runtime.get("passed", 0))
                record["scenario_failed"] = int(runtime.get("failed", 0))
                if result.get("status") == "RUNTIME_PASS":
                    record["status"] = "RUNTIME_PASS"
                elif result.get("status") == "RUNTIME_FAIL":
                    record["status"] = "RUNTIME_FAIL"
                else:
                    record["status"] = result.get("status", "UNKNOWN")
        records.append(record)
        snapshot = {"batch_id":batch_id, "current":index, "total":len(selected),
                    "updated_at":datetime.now().isoformat(timespec="seconds"), "records":records}
        progress_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{index}/{len(selected)}] {task_id} {model_id} => {record['status']} "
              f"({record.get('scenario_passed',0)}/{record.get('scenario_executed',0)} scenarios)", flush=True)
    summary = {"schema_version":1, "batch_id":batch_id, "scope":"Self-developed harness; GPT and DeepSeek",
               "started_at":batch_id, "completed_at":datetime.now().isoformat(timespec="seconds"),
               "matrix_source":"experiments/results.csv (read-only)", "records":records}
    summary["counts"] = {
        "candidate_outputs":len(records),
        "runtime_pass_outputs":sum(r.get("status") == "RUNTIME_PASS" for r in records),
        "runtime_fail_outputs":sum(r.get("status") == "RUNTIME_FAIL" for r in records),
        "other_or_blocked_outputs":sum(r.get("status") not in ("RUNTIME_PASS", "RUNTIME_FAIL") for r in records),
        "scenarios_executed":sum(r.get("scenario_executed",0) for r in records),
        "scenarios_passed":sum(r.get("scenario_passed",0) for r in records),
        "scenarios_failed":sum(r.get("scenario_failed",0) for r in records),
        "scenarios_blocked":sum(r.get("scenario_blocked",0) for r in records),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary":str(summary_path), "counts":summary["counts"]}, ensure_ascii=False, indent=2))
    return 0


def latest_result_path(base: Path, task_id: str, source_hash: str, suite_hash: str) -> Path | None:
    runner_hash = sha256((ROOT / "tools/run_codesys_runtime_suite.py").read_bytes())
    for path in sorted(base.glob("*/result.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (item.get("task_id") == task_id and item.get("source_sha256") == source_hash
                and item.get("suite_sha256") == suite_hash
                and (item.get("runner_sha256") == runner_hash
                     or item.get("status") in ("RUNTIME_PASS", "RUNTIME_FAIL"))
                and item.get("run_requested") is True):
            return path
    return None


if __name__ == "__main__":
    raise SystemExit(main())
