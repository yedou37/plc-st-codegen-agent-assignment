"""Compile a generated ST candidate with an explicit offline CODESYS call harness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from codesys_linked import ROOT, compile_batch
from audit_interfaces import interface_issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--task-id", default="manual")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result, = compile_batch([(args.task_id, args.source)], timeout=150)
    except OSError as exc:
        result = {"status": "UNAVAILABLE", "error": str(exc)}
    if result["status"] == "PASS":
        tasks = json.loads((ROOT / "dataset/tasks.json").read_text(encoding="utf-8"))["tasks"]
        task = next((row for row in tasks if row["id"] == args.task_id), None)
        if task:
            _, issues = interface_issues(args.source.read_text(encoding="utf-8-sig"), task)
            result["interface_status"] = "MISMATCH" if issues else "MATCH"
            result["interface_issues"] = issues
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
