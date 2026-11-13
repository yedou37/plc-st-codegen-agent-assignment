"""Recheck the 120 archived final ST outputs with one linked CODESYS adapter."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from codesys_linked import ROOT, compile_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / "experiments" / "local_runs"):
        parser.error("Use a new directory under experiments/local_runs")
    out.mkdir(parents=True, exist_ok=False)
    with (ROOT / "experiments/results.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 120 or len({row["run_id"] for row in rows}) != 120:
        raise ValueError("Expected 120 distinct archived outputs")

    results = []
    with (out / "diagnostics.jsonl").open("w", encoding="utf-8") as log:
        for start in range(0, len(rows), 20):
            group = rows[start:start + 20]
            checks = compile_batch([(r["task_id"], ROOT / r["output_file"]) for r in group], 300)
            for row, check in zip(group, checks, strict=True):
                result = {**{k: row[k] for k in ("run_id", "framework", "model_id", "output_file")},
                          "archived_status": row["final_compile"], **check}
                results.append(result)
                log.write(json.dumps(result, ensure_ascii=False) + "\n")
            log.flush()
            print(f"{len(results)}/{len(rows)} {dict(Counter(r['status'] for r in results))}", flush=True)
    by_condition = defaultdict(Counter)
    for result in results:
        by_condition[f"{result['framework']} + {result['model_id']}"][result["status"]] += 1
    summary = {"scope": "Offline linked builds of archived final sources",
               "model_requests": 0, "planned": len(rows), "recorded": len(results),
               "counts": dict(Counter(r["status"] for r in results)),
               "by_condition": dict(by_condition)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
