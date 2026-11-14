"""Pluggable target compiler adapter; no CODESYS compile is simulated here."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

def compile_st(source_path: Path, task_id: str, config_path: Path | None = None) -> dict:
    command = None
    if config_path and config_path.exists():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        command = cfg.get("compiler", {}).get("command")
    command = command or os.environ.get("PLC_ST_COMPILER_COMMAND")
    if not command:
        return {"status":"NOT_CONFIGURED", "return_code":None, "stdout":"", "stderr":"",
                "elapsed_ms":0, "compiler":""}
    root = Path(__file__).resolve().parent.parent
    cmd = [str(x).format(source=str(source_path.resolve()), task_id=task_id,
                         output=str(source_path.with_suffix(".compile.log").resolve()),
                         python=sys.executable, repo_root=str(root)) for x in command]
    start = time.perf_counter()
    try:
        cp = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8", errors="replace", timeout=180, check=False, cwd=str(root))
        elapsed = round((time.perf_counter()-start)*1000)
        status = "PASS" if cp.returncode == 0 else "FAIL"
        interface_status = "NOT_RUN"
        interface_issues = []
        if any(Path(arg).name == "codesys_compile.py" for arg in cmd):
            try:
                diagnostics = json.loads(cp.stdout)
                status = diagnostics["status"]
                interface_status = diagnostics.get("interface_status", "NOT_RUN")
                interface_issues = diagnostics.get("interface_issues", [])
                if status not in {"PASS", "FAIL", "INVALID_SOURCE", "UNSUPPORTED_BINDING", "TIMEOUT", "UNAVAILABLE"}:
                    status = "UNAVAILABLE"
                if status == "PASS" and cp.returncode != 0:
                    status = "UNAVAILABLE"
            except (ValueError, KeyError, TypeError):
                status = "UNAVAILABLE"
        return {"status":status, "return_code":cp.returncode,
                "interface_status":interface_status,"interface_issues":interface_issues,
                "stdout":cp.stdout[-12000:], "stderr":cp.stderr[-12000:], "elapsed_ms":elapsed,
                "compiler":" ".join(cmd)}
    except subprocess.TimeoutExpired as exc:
        return {"status":"TIMEOUT", "return_code":None, "stdout":str(exc.stdout or ""),
                "stderr":str(exc.stderr or ""), "elapsed_ms":180000, "compiler":" ".join(cmd)}
    except OSError as exc:
        return {"status":"UNAVAILABLE", "return_code":None, "stdout":"", "stderr":str(exc),
                "elapsed_ms":0, "compiler":" ".join(cmd)}

if __name__ == "__main__":
    result = compile_st(Path(sys.argv[1]), sys.argv[2] if len(sys.argv)>2 else "manual")
    print(json.dumps(result, ensure_ascii=False, indent=2))
