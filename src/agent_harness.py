"""Minimal PLC ST coding-agent harness with bounded compile-repair iterations."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from adapters import AdapterError, chat_completion
from compiler import compile_st
from static_check import check_source, extract_st

ROOT = Path(__file__).resolve().parents[1]
PROMPT = (Path(__file__).with_name("prompt.md")).read_text(encoding="utf-8")

def task_prompt(task: dict) -> str:
    return ("Implement the task as one CODESYS-compatible IEC 61131-3 ST program.\n"
            "Use the exact interface in the dataset. Treat formulas as invariants to preserve.\n\n"
            + json.dumps(task, ensure_ascii=False, indent=2))

def run_task(task: dict, model_cfg: dict, run_dir: Path, config_path: Path,
             repair_limit: int = 2) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    messages = [{"role":"system","content":PROMPT}, {"role":"user","content":task_prompt(task)}]
    trace, token_in, token_out, provider_costs = [], 0, 0, []
    first_compile, final_compile = None, None
    final_code, status = "", "ERROR"
    started = time.perf_counter()
    for attempt in range(repair_limit + 1):
        try:
            response = chat_completion(messages, model_cfg)
        except AdapterError as exc:
            status = "MODEL_ERROR"
            trace.append({"attempt":attempt,"error":str(exc)})
            break
        token_in += response.get("prompt_tokens") or 0
        token_out += response.get("completion_tokens") or 0
        if response.get("provider_cost") is not None:
            provider_costs.append(response["provider_cost"])
        code = extract_st(response["content"])
        final_code = code
        if not code.strip():
            status = "EMPTY_RESPONSE"
            trace.append({"attempt":attempt+1,"status":status,
                          "response_meta":response.get("response_meta", {})})
            break
        static_errors = check_source(code)
        src_path = run_dir / f"{task['id']}_attempt{attempt+1}.st"
        src_path.write_text(code, encoding="utf-8")
        # The token precheck is diagnostic only; it is never a substitute for
        # the configured target compiler.
        compile_result = compile_st(src_path, task["id"], config_path)
        if attempt == 0:
            first_compile = compile_result["status"]
        final_compile = compile_result
        trace.append({"attempt":attempt+1,"static_errors":static_errors,"compile":compile_result})
        (run_dir / f"{task['id']}_attempt{attempt+1}.st").write_text(code, encoding="utf-8")
        if compile_result["status"] == "PASS":
            status = "COMPILE_PASS"
            break
        if compile_result["status"] in ("NOT_CONFIGURED", "UNAVAILABLE", "TIMEOUT", "UNSUPPORTED_BINDING"):
            if compile_result["status"] == "NOT_CONFIGURED":
                status = ("GENERATED_STATIC_FAIL_COMPILER_UNAVAILABLE" if static_errors
                          else "GENERATED_STATIC_PASS_COMPILER_UNAVAILABLE")
            else:
                status = compile_result["status"]
            break
        status = "COMPILE_FAIL"
        if attempt < repair_limit:
            messages.append({"role":"assistant","content":response["content"]})
            messages.append({"role":"user","content":
                "Repair the ST using only the diagnostics below. Return the complete corrected program in one ```st block.\n\n"
                + str(compile_result.get("stderr", "")) + "\n" + str(compile_result.get("stdout", ""))})
    final_static_errors = trace[-1].get("static_errors", []) if trace else []
    static_status = ("FAIL" if final_static_errors else "PASS") if trace and "static_errors" in trace[-1] else "NOT_RUN_EMPTY_RESPONSE"
    return {"task_id":task["id"],"status":status,"first_compile":first_compile,
            "final_compile":final_compile["status"] if final_compile else "NOT_RUN",
            "static_precheck":static_status,
            "repair_attempts":max(0,len(trace)-1),"prompt_tokens":token_in,"completion_tokens":token_out,
            "provider_costs":provider_costs,
            "elapsed_ms":round((time.perf_counter()-started)*1000),"trace":trace,"code":final_code}

if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: agent_harness.py TASKS_JSON MODEL_CONFIG_JSON OUTPUT_DIR")
    tasks = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["tasks"]
    model_cfg = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    out = Path(sys.argv[3])
    result = run_task(tasks[0], model_cfg, out, Path(sys.argv[2]))
    (out/"trace.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="code"},ensure_ascii=False,indent=2))
