"""Compare linked compile passes with the benchmark's declared IEC interfaces."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from codesys_linked import ROOT, BindingError, SourceError, mask_comments, source_units


SECTION = {"Input": "VAR_INPUT", "Output": "VAR_OUTPUT", "Input/Output": "VAR_IN_OUT"}


def normalize(dtype: str) -> str:
    dtype = re.sub(r"\s+", "", dtype.upper())
    if dtype.startswith(("STRING[", "WSTRING[")):
        return dtype.replace("[", "(").replace("]", ")")
    return dtype


def fields(block: str, section: str) -> dict:
    result = {}
    for declaration in block.split(";"):
        match = re.fullmatch(r"\s*(\w+(?:\s*,\s*\w+)*)\s*:\s*(.*?)\s*", declaration, re.S)
        if match:
            for name in match[1].split(","):
                result[name.strip().lower()] = (section, normalize(match[2].split(":=", 1)[0]))
    return result


def interface_issues(source: str, task: dict) -> tuple[str, list[str]]:
    units = source_units(source.replace("\r\n", "\n"))
    candidate = next((unit for unit in units if unit["kind"] in ("PROGRAM", "FUNCTION_BLOCK")), None)
    if candidate is None:
        return "", ["No main PROGRAM or FUNCTION_BLOCK"]
    expected = {field["name"].lower(): (SECTION[field["direction"]], normalize(field["type"]))
                for field in task["interface"] if field["direction"] in SECTION}
    actual = {}
    for section, block in candidate["sections"]:
        actual.update(fields(block, section))
    issues = []
    for name, (direction, dtype) in expected.items():
        if name not in actual:
            issues.append(f"Missing {direction} {name}: {dtype}")
        elif actual[name] != (direction, dtype):
            issues.append(f"{name}: expected {direction} {dtype}, got {' '.join(actual[name])}")
    for name, (direction, dtype) in actual.items():
        if direction in SECTION.values() and name not in expected:
            issues.append(f"Unexpected {direction} {name}: {dtype}")
    # A candidate-defined DUT can compile while disagreeing with the task's record layout.
    task_dut = {"P07": "ST_Pump", "P08": "ST_AnalogChannel", "P17": "ST_Recipe"}.get(task["id"])
    for unit in units:
        if unit["kind"] != "TYPE" or not task_dut or unit["name"].lower() != task_dut.lower():
            continue
        reference = (ROOT / "st/support_types" / f"{task_dut}.st").read_text(encoding="utf-8")
        def layout(text):
            block = re.search(r"\bSTRUCT\b(.*?)\bEND_STRUCT\b", mask_comments(text), re.I | re.S)[1]
            return list(fields(block, "STRUCT").items())
        if layout(unit["declaration"]) != layout(reference):
            issues.append(f"{task_dut}: fields, order or types differ from the task DUT")
    return candidate["name"], issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linked-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tasks = {t["id"]: t for t in json.loads((ROOT / "dataset/tasks.json").read_text(encoding="utf-8"))["tasks"]}
    results = []
    for line in args.linked_results.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["status"] != "PASS":
            continue
        source = ROOT / row["output_file"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != row["source_sha256"]:
            raise ValueError(f"Source changed for {row['run_id']}")
        try:
            name, issues = interface_issues(source.read_text(encoding="utf-8-sig"), tasks[row["task_id"]])
        except (SourceError, BindingError) as exc:
            name, issues = "", [str(exc)]
        results.append({"run_id": row["run_id"], "task_id": row["task_id"],
                        "source": row["output_file"], "source_sha256": row["source_sha256"],
                        "candidate": name, "status": "MISMATCH" if issues else "MATCH", "issues": issues})
    matched = sum(row["status"] == "MATCH" for row in results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"checked": len(results), "matched": matched, "mismatched": len(results)-matched,
                   "records": results}, stream, ensure_ascii=False, indent=2)
    print(f"Interface audit: {matched}/{len(results)} matches")


if __name__ == "__main__":
    main()
