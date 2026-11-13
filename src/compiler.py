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
    result_format = "json"
    if config_path and config_path.exists():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        command = cfg.get("compiler", {}).get("command")
        result_format = cfg.get("compiler", {}).get("result_format", "json")
    command = command or os.environ.get("PLC_ST_COMPILER_COMMAND")
    if not command:
        return {"status":"NOT_CONFIGURED", "return_code":None, "stdout":"", "stderr":"",
                "elapsed_ms":0, "compiler":""}
    if isinstance(command, str):
        try:
            command = json.loads(command)
        except json.JSONDecodeError:
            return {"status":"NOT_CONFIGURED", "stderr":"Compiler command must be a JSON argv list",
                    "stdout":"", "return_code":None, "elapsed_ms":0, "compiler":""}
    if not isinstance(command, list) or not command or result_format not in ("json", "exit_code"):
        return {"status":"NOT_CONFIGURED", "stderr":"Invalid compiler command or result_format",
                "stdout":"", "return_code":None, "elapsed_ms":0, "compiler":""}
    root = Path(__file__).resolve().parent.parent
    cmd = [str(x).format(source=str(source_path.resolve()), task_id=task_id,
                         output=str(source_path.with_suffix(".compile.log").resolve()),
                         python=sys.executable, repo_root=str(root)) for x in command]
    start = time.perf_counter()
    try:
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        cp = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace",
                            capture_output=True, timeout=180, check=False, cwd=str(root), env=child_env)
        elapsed = round((time.perf_counter()-start)*1000)
        adapter = None
        for line in reversed(cp.stdout.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and "status" in value:
                adapter = value
                break
        if result_format == "exit_code":
            status = "PASS" if cp.returncode == 0 else "FAIL"
        else:
            status = (adapter or {}).get("status", "UNAVAILABLE")
            if status not in ("PASS", "FAIL", "TIMEOUT", "UNAVAILABLE", "NOT_CONFIGURED"):
                status = "UNAVAILABLE"
            if status == "PASS" and cp.returncode != 0:
                status = "UNAVAILABLE"
        return {"status":status, "adapter_result":adapter, "return_code":cp.returncode,
                "stdout":cp.stdout[-12000:], "stderr":cp.stderr[-12000:], "elapsed_ms":elapsed,
                "compiler":" ".join(cmd)}
    except subprocess.TimeoutExpired as exc:
        return {"status":"TIMEOUT", "return_code":None, "stdout":str(exc.stdout or ""),
                "stderr":str(exc.stderr or ""), "elapsed_ms":round((time.perf_counter()-start)*1000), "compiler":" ".join(cmd)}
    except OSError as exc:
        return {"status":"UNAVAILABLE", "return_code":None, "stdout":"", "stderr":str(exc),
                "elapsed_ms":0, "compiler":" ".join(cmd)}

if __name__ == "__main__":
    result = compile_st(Path(sys.argv[1]), sys.argv[2] if len(sys.argv)>2 else "manual")
    print(json.dumps(result, ensure_ascii=False, indent=2))
