"""Run the paired Pi baseline and custom harness benchmark through a metered relay."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
if str(ROOT/"src") not in sys.path: sys.path.insert(0,str(ROOT/"src"))
TASKS_FILE = ROOT / "dataset" / "tasks.json"
DEFAULT_CONFIG = HERE / "config.example.json"
FIELDS = ["run_id","task_id","origin","framework","model_id","status","static_precheck",
          "first_compile","final_compile","test_passed","test_total","verifier_status",
          "prompt_tokens","completion_tokens","cost_cny","latency_ms","repairs","output_file","notes"]

def read_usage(log_path: Path, byte_offset: int) -> list[dict]:
    if not log_path.exists(): return []
    with log_path.open("rb") as f:
        f.seek(byte_offset)
        raw = f.read().decode("utf-8", errors="replace")
    rows=[]
    for line in raw.splitlines():
        try: rows.append(json.loads(line))
        except json.JSONDecodeError: pass
    return rows

def wait_for_usage(log_path: Path, byte_offset: int, timeout: float = 15.0) -> list[dict]:
    """Wait for the relay to flush usage for the just-finished request(s)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = read_usage(log_path, byte_offset)
        if rows:
            # Streaming clients can exit just before the relay writes its log.
            time.sleep(0.15)
            return read_usage(log_path, byte_offset)
        time.sleep(0.05)
    return read_usage(log_path, byte_offset)

def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

def create_pi_config(dirpath: Path, models: dict, max_tokens: int, base_url: str):
    provider_models=[]
    for key in ("gpt","deepseek"):
        cfg=models[key]
        provider_models.append({"id":cfg["model_id"],"name":cfg["label"],"api":"openai-completions",
            "reasoning":bool(cfg.get("reasoning", False)),"input":["text"],"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0},
            "contextWindow":32768,"maxTokens":max_tokens,
            "samplingParams":{"temperature":0,**cfg.get("sampling_params", {})}})
    data={"$schema":"https://pi.dev/schemas/models.schema.json","providers":{"dmxapi":{
        "name":"DMXAPI","baseUrl":base_url,"apiKey":"$DMXAPI_API_KEY","authHeader":True,
        "api":"openai-completions","models":provider_models}}}
    dirpath.mkdir(parents=True,exist_ok=True)
    (dirpath/"models.json").write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (dirpath/"settings.json").write_text(json.dumps({"quietStartup":True,"defaultTools":[]},indent=2)+"\n",encoding="utf-8")

def start_relay(log_path: Path, budget_cny: float, request_reserve_cny: float,
                max_tokens: int = 768) -> subprocess.Popen:
    script=ROOT/"tools"/"dmxapi_metered_proxy.py"
    python=sys.executable
    scale=max(1, max_tokens/768)
    proc=subprocess.Popen([python,str(script),"--port","8765","--log-file",str(log_path.resolve()),
                           "--max-cost-cny",str(budget_cny),"--request-reserve-cny",str(request_reserve_cny),
                           "--gpt-request-reserve-cny",str(0.08*scale),"--deepseek-request-reserve-cny",str(0.01*scale),
                           "--max-output-tokens",str(max_tokens)],
        cwd=str(ROOT),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    for _ in range(50):
        if proc.poll() is not None: raise RuntimeError("metered relay exited during startup")
        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/health",timeout=0.4) as r:
                if r.status==200: return proc
        except Exception: time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("metered relay did not become ready")

def available_node_candidates() -> list[str]:
    """Prefer a Node version supported by Pi without changing the system default."""
    configured=os.environ.get("PI_NODE_EXE")
    if configured:
        return [configured]
    candidates=[]
    system_node=shutil.which("node")
    if system_node:
        candidates.append(system_node)
    if os.name == "nt":
        nvm_home=Path(os.environ.get("NVM_HOME",str(Path.home()/"AppData"/"Local"/"nvm")))
        versions=[]
        try:
            for directory in nvm_home.iterdir():
                match=re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)",directory.name)
                if not match:
                    continue
                version=tuple(int(part) for part in match.groups())
                node_path=directory/"node.exe"
                if version >= (22,19,0) and node_path.is_file():
                    versions.append((version,str(node_path)))
        except OSError:
            pass
        candidates.extend(path for _,path in sorted(versions,reverse=True))
    return candidates

def find_pi_node() -> tuple[str,str]:
    errors=[]
    for node in available_node_candidates():
        result=subprocess.run([node,"--version"],capture_output=True,text=True,encoding="utf-8",
                              errors="replace",timeout=10,check=False)
        version=result.stdout.strip()
        try:
            numeric=tuple(int(x) for x in version.lstrip("v").split(".")[:3])
        except ValueError:
            numeric=(0,0,0)
        if result.returncode == 0 and numeric >= (22,19,0):
            return node,version
        errors.append(version or f"exit {result.returncode}")
    if not errors:
        raise RuntimeError("Node.js is not installed")
    raise RuntimeError("Pi requires Node.js 22.19.0 or newer; found " + ", ".join(errors))

def run_pi(task: dict, model_cfg: dict, pi_dir: Path, entry: Path) -> dict:
    from src.static_check import check_source, extract_st
    node,version=find_pi_node()
    if not entry.exists(): raise RuntimeError(f"Pi coding-agent is not installed at {entry}")
    from src.agent_harness import task_prompt, PROMPT
    env=os.environ.copy()
    env["PI_CODING_AGENT_DIR"]=str(pi_dir)
    env["PI_SKIP_VERSION_CHECK"]="1"
    env["PI_TELEMETRY"]="0"
    thinking_level="low" if model_cfg.get("reasoning", False) else "off"
    argv=[node,str(entry),"--no-tools","--no-mcp","--no-extensions","--no-session","--print","--mode","json",
          "--no-context-files","--no-skills","--no-prompt-templates","--system-prompt",PROMPT,
          "--provider","dmxapi","--model",model_cfg["model_id"],"--thinking",thinking_level]
    started=time.perf_counter()
    cp=subprocess.run(argv,input=task_prompt(task),text=True,encoding="utf-8",errors="replace",
                      capture_output=True,cwd=str(ROOT),env=env,timeout=900,check=False)
    if cp.returncode:
        raise RuntimeError(f"Pi exited with code {cp.returncode}")
    events=[]
    for line in (cp.stdout or "").splitlines():
        try: events.append(json.loads(line))
        except json.JSONDecodeError: pass
    final=""
    usage={}
    finish_reason=None
    for event in events:
        if event.get("type")=="message_end" and event.get("message",{}).get("role")=="assistant":
            message=event["message"]
            content=message.get("content",[])
            final="\n".join(x.get("text","") for x in content if isinstance(x,dict) and x.get("type")=="text")
            usage=message.get("usage",{})
            finish_reason=message.get("stopReason") or message.get("finishReason")
    settled=any(x.get("type")=="agent_settled" and not x.get("aborted") for x in events)
    if not settled: raise RuntimeError("Pi stream did not settle normally")
    code=extract_st(final)
    static_status=("FAIL" if check_source(code) else "PASS") if code.strip() else "NOT_RUN"
    return {"code":code,"static_precheck":static_status,
            "prompt_tokens":usage.get("input"),"completion_tokens":usage.get("output"),
            "latency_ms":round((time.perf_counter()-started)*1000),"finish_reason":finish_reason}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    ap.add_argument("--pilot",action="store_true",help="run one public and one self-built task across all four conditions (8 bounded calls)")
    ap.add_argument("--full",action="store_true",help="run all 120 cells, subject to --max-cost-cny")
    ap.add_argument("--max-cost-cny",type=float,default=1.0,help="stop before the next request when this run reaches the cap")
    ap.add_argument("--max-output-tokens",type=int,help="shared response limit for both strategies and the relay")
    ap.add_argument("--task-ids",default="",help="optional comma-separated task IDs for a bounded rerun")
    ap.add_argument("--frameworks",default="pi,self",help="comma-separated subset: pi,self")
    ap.add_argument("--models",default="gpt,deepseek",help="comma-separated subset: gpt,deepseek")
    ap.add_argument("--plan",action="store_true",help="print the selected cells and limits without making requests")
    ap.add_argument("--resume",action="store_true",help="reuse completed cells in the existing output and retry errors")
    ap.add_argument("--output",type=Path,default=None,
                    help="CSV path; defaults to an ignored file under experiments/local_runs")
    ap.add_argument("--artifact-root",type=Path,default=None,
                    help="directory for generated ST and compiler logs; defaults beside the CSV, under experiments/local_runs")
    args=ap.parse_args()
    if args.pilot==args.full: raise SystemExit("Choose exactly one of --pilot or --full")
    if not math.isfinite(args.max_cost_cny) or args.max_cost_cny <= 0: raise SystemExit("--max-cost-cny must be positive")
    cfg=json.loads(args.config.read_text(encoding="utf-8"))
    data=json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    tasks=data["tasks"]
    if args.task_ids:
        selected={item.strip() for item in args.task_ids.split(",") if item.strip()}
        unknown=selected-{t["id"] for t in tasks}
        if unknown: raise SystemExit(f"Unknown task IDs: {', '.join(sorted(unknown))}")
        tasks=[t for t in tasks if t["id"] in selected]
    framework_names={"pi":"Pi coding-agent single-shot","self":"Self-developed harness"}
    model_keys=("gpt","deepseek")
    selected_frameworks={item.strip().lower() for item in args.frameworks.split(",") if item.strip()}
    if not selected_frameworks or selected_frameworks-set(framework_names):
        raise SystemExit("--frameworks must be a comma-separated subset of: pi,self")
    selected_models={item.strip().lower() for item in args.models.split(",") if item.strip()}
    if not selected_models or selected_models-set(model_keys):
        raise SystemExit("--models must be a comma-separated subset of: gpt,deepseek")
    local_runs=HERE/"local_runs"
    output=args.output
    if args.pilot:
        chosen={"P02","S08"}
        tasks=[t for t in tasks if t["id"] in chosen]
        max_tokens=int(cfg["experiment"].get("pilot_max_tokens",4096))
        output=output or (local_runs/"pilot_results.csv")
    else:
        max_tokens=int(cfg["experiment"].get("full_max_tokens",4096))
        output=output or (local_runs/"full_matrix.csv")
    if args.max_output_tokens is not None:
        max_tokens=args.max_output_tokens
    if max_tokens < 1:
        ap.error("--max-output-tokens must be positive")
    if not tasks:
        ap.error("The selected tasks do not intersect this run mode")
    output=output.resolve()
    artifact_root=(args.artifact_root or output.with_name(output.stem+"_artifacts")).resolve()
    if not output.is_relative_to(local_runs) or not artifact_root.is_relative_to(local_runs):
        ap.error("CSV and artifacts must be under experiments/local_runs")
    if output.is_relative_to(artifact_root):
        ap.error("CSV must be outside the dedicated artifact directory")
    seed=int(cfg["experiment"].get("seed",20261108))
    random.Random(seed).shuffle(tasks)
    run_specs=[]
    cells=((task,key,fw) for task in tasks for key in model_keys for fw in ("pi","self"))
    for idx,(task,key,fw) in enumerate(cells,1):
        if key in selected_models and fw in selected_frameworks:
            run_specs.append((f"{idx:03d}-{task['id']}-{key}-{fw}",task,key,framework_names[fw]))
    plan={
        "cells":[run_id for run_id, _, _, _ in run_specs], "pilot":args.pilot,
        "seed":seed, "max_output_tokens":max_tokens, "artifact_root":str(artifact_root),
        "dataset_sha256":hashlib.sha256(TASKS_FILE.read_bytes()).hexdigest(),
        "config_sha256":hashlib.sha256(args.config.read_bytes()).hexdigest(),
        "prompt_sha256":hashlib.sha256((ROOT/"src/prompt.md").read_bytes()).hexdigest(),
    }
    if args.plan:
        print(json.dumps({**plan,"budget_limit_cny":args.max_cost_cny},ensure_ascii=False,indent=2))
        return
    plan_path=output.with_name(output.stem+"_plan.json")
    if plan_path.exists():
        if not args.resume or json.loads(plan_path.read_text(encoding="utf-8")) != plan:
            ap.error("Use --resume with the same plan or choose a new --output and --artifact-root")
    else:
        if output.exists() or artifact_root.exists() or any(output.parent.glob(output.stem+"_usage_*.jsonl")):
            ap.error("This path already has artifacts. Choose a new --output and --artifact-root")
        artifact_root.mkdir(parents=True)
        output.parent.mkdir(parents=True,exist_ok=True)
        with plan_path.open("x",encoding="utf-8") as stream:
            json.dump(plan,stream,ensure_ascii=False,indent=2)
    existing_rows=[]
    if args.resume and output.exists():
        with output.open(newline="",encoding="utf-8-sig") as stream:
            existing_rows=list(csv.DictReader(stream))
    key_env=cfg["models"]["gpt"].get("api_key_env","DMXAPI_API_KEY")
    credential_available=bool(os.environ.get(key_env))
    baseline=cfg["baseline"]
    entry=(ROOT/baseline["entry"]).resolve()
    pi_available="pi" in selected_frameworks and entry.is_file()
    existing_usage=[]
    if args.resume:
        for usage_file in sorted(output.parent.glob(output.stem+"_usage_*.jsonl")):
            try:
                for line in usage_file.read_text(encoding="utf-8").splitlines():
                    try: existing_usage.append(json.loads(line))
                    except json.JSONDecodeError: pass
            except OSError:
                pass
    total_spend=round(sum(float(row.get("cost_cny") or 0) for row in existing_usage),8)
    budget_spend=round(sum(float(row.get("budget_charged_cny",row.get("cost_cny")) or 0)
                           for row in existing_usage),8)
    budget_exhausted=budget_spend >= args.max_cost_cny
    rows=list(existing_rows)
    existing_by_id={row.get("run_id"):row for row in existing_rows if row.get("run_id")}
    reusable_statuses={"COMPILE_PASS","COMPILE_FAIL","EMPTY_RESPONSE","NOT_RUN_NO_CODE",
                       "MODEL_TRUNCATED","INVALID_SOURCE","UNSUPPORTED_BINDING","INTERFACE_MISMATCH"}
    run_stamp=time.strftime("%Y%m%d_%H%M%S")
    log_path=output.with_name(output.stem+f"_usage_{run_stamp}.jsonl")
    pi_dir=Path(tempfile.mkdtemp(prefix="plc_pi_"))
    relay=None
    try:
        remaining_budget=max(0.0,args.max_cost_cny-budget_spend)
        request_reserve_cny=min(0.08,remaining_budget/2)
        if credential_available and not budget_exhausted and (pi_available or "self" in selected_frameworks):
            relay=start_relay(log_path,remaining_budget,request_reserve_cny,max_tokens)
        if pi_available and relay is not None:
            create_pi_config(pi_dir,cfg["models"],max_tokens,"http://127.0.0.1:8765/v1")
        for idx,(run_id,task,model_key,framework) in enumerate(run_specs,1):
            if args.resume and existing_by_id.get(run_id,{}).get("status") in reusable_statuses:
                continue
            if not credential_available or (framework == framework_names["pi"] and not pi_available):
                missing_status=("NOT_RUN_MISSING_CREDENTIAL" if not credential_available
                                else "NOT_RUN_BASELINE_UNAVAILABLE")
                notes=(f"Set {key_env} in the process environment." if not credential_available
                       else f"Install {baseline['package']}@{baseline['version']}.")
                rows=[row for row in rows if row["run_id"]!=run_id]
                rows.append({"run_id":run_id,"task_id":task["id"],"origin":task["origin"],
                    "framework":framework,"model_id":cfg["models"][model_key]["model_id"],
                    "status":missing_status,"first_compile":"NOT_RUN","final_compile":"NOT_RUN",
                    "verifier_status":"NOT_RUN","notes":notes})
                write_csv(output,rows)
                continue
            reserve_cny=(0.08 if model_key=="gpt" else 0.01)*max(1,max_tokens/768)
            if budget_exhausted or budget_spend+reserve_cny>args.max_cost_cny:
                budget_exhausted=True
                budget_row={"run_id":run_id,"task_id":task["id"],"origin":task["origin"],"framework":framework,
                    "model_id":cfg["models"][model_key]["model_id"],"status":"NOT_RUN_BUDGET_CAP",
                    "first_compile":"NOT_RUN","final_compile":"NOT_RUN","verifier_status":"NOT_RUN",
                    "notes":f"Next {model_key} request reserve would exceed configured cap {args.max_cost_cny:.4f} CNY."}
                rows=[row for row in rows if row.get("run_id")!=run_id]
                rows.append(budget_row)
                existing_by_id[run_id]=budget_row
                write_csv(output,rows)
                continue
            before=log_path.stat().st_size if log_path.exists() else 0
            model_cfg=dict(cfg["models"][model_key]); model_cfg["max_tokens"]=max_tokens
            model_cfg["base_url"]="http://127.0.0.1:8765/v1"
            try:
                if framework.startswith("Pi"):
                    result=run_pi(task,model_cfg,pi_dir,entry)
                    code=result["code"]
                    outdir=artifact_root/("pilot" if args.pilot else "runs")/"pi"/model_key
                    outpath=outdir/f"{task['id']}.st"
                    if code.strip():
                        outdir.mkdir(parents=True,exist_ok=True)
                        outpath.write_text(code,encoding="utf-8")
                    else:
                        outpath=None
                    static_status=result["static_precheck"]
                    token_in=result.get("prompt_tokens"); token_out=result.get("completion_tokens")
                    latency=result["latency_ms"]; repairs=0
                else:
                    from src.agent_harness import run_task
                    outdir=artifact_root/("pilot" if args.pilot else "runs")/"self"/model_key
                    result=run_task(task,model_cfg,outdir,args.config,repair_limit=0 if args.pilot else int(cfg["experiment"].get("repair_limit",2)))
                    code=result["code"]
                    outpath=Path(result["output_path"]) if result.get("output_path") else None
                    static_status=result.get("static_precheck", "NOT_RUN")
                    token_in=result.get("prompt_tokens"); token_out=result.get("completion_tokens")
                    latency=result.get("elapsed_ms"); repairs=result.get("repair_attempts",0)
                interface_status="NOT_RUN"
                if framework.startswith("Pi"):
                    if result.get("finish_reason") in ("length", "max_tokens"):
                        first_compile_status=final_compile_status="NOT_RUN_TRUNCATED"
                        run_status="MODEL_TRUNCATED"
                    elif code.strip() and outpath:
                        from src.compiler import compile_st
                        pi_compile=compile_st(outpath,task["id"],args.config)
                        first_compile_status=pi_compile["status"]
                        final_compile_status=pi_compile["status"]
                        interface_status=pi_compile.get("interface_status","NOT_RUN")
                        run_status=("INTERFACE_MISMATCH" if interface_status=="MISMATCH" else
                                    "COMPILE_PASS" if pi_compile["status"]=="PASS" else
                                    "COMPILE_FAIL" if pi_compile["status"]=="FAIL" else pi_compile["status"])
                    else:
                        first_compile_status="NOT_RUN_NO_CODE"
                        final_compile_status="NOT_RUN_NO_CODE"
                        run_status="EMPTY_RESPONSE"
                else:
                    first_compile_status=result.get("first_compile","NOT_RUN")
                    final_compile_status=result.get("final_compile","NOT_RUN")
                    run_status=result.get("status","ERROR")
                    interface_status=result.get("interface_status","NOT_RUN")
                meter=wait_for_usage(log_path,before)
                costs=[x.get("cost_cny") for x in meter if x.get("cost_cny") is not None]
                row_cost=round(sum(costs),8) if costs else None
                if row_cost is not None: total_spend += row_cost
                reserved=[x.get("budget_charged_cny",x.get("cost_cny")) for x in meter
                          if x.get("budget_charged_cny",x.get("cost_cny")) is not None]
                budget_row=round(sum(reserved),8) if reserved else 0.0
                budget_spend += budget_row
                if any(x.get("budget_blocked") for x in meter):
                    budget_exhausted=True
                    run_status="NOT_RUN_BUDGET_CAP"
                prompts=[x.get("prompt_tokens") for x in meter if x.get("prompt_tokens") is not None]
                completions=[x.get("completion_tokens") for x in meter if x.get("completion_tokens") is not None]
                if prompts: token_in=sum(prompts)
                if completions: token_out=sum(completions)
                rows.append({"run_id":run_id,"task_id":task["id"],"origin":task["origin"],"framework":framework,
                    "model_id":model_cfg["model_id"],"status":run_status,"static_precheck":static_status,
                    "first_compile":first_compile_status,"final_compile":final_compile_status,"test_passed":"","test_total":"",
                    "verifier_status":"NOT_RUN_NO_VERIFIER","prompt_tokens":token_in,"completion_tokens":token_out,
                    "cost_cny":row_cost,"latency_ms":latency,"repairs":repairs,
                    "output_file":str(outpath.relative_to(ROOT)) if outpath else "",
                    "notes":("Functional test vectors and PLCVerif are not configured; static precheck is not compilation."
                             if final_compile_status in ("NOT_CONFIGURED","NOT_RUN","NOT_RUN_NO_CODE") else
                             f"CODESYS compilation={final_compile_status}, interface={interface_status}. See adjacent .compile.log if created.")})
            except Exception as exc:
                meter=wait_for_usage(log_path,before)
                costs=[x.get("cost_cny") for x in meter if x.get("cost_cny") is not None]
                row_cost=round(sum(costs),8) if costs else None
                if row_cost is not None: total_spend += row_cost
                reserved=[x.get("budget_charged_cny",x.get("cost_cny")) for x in meter
                          if x.get("budget_charged_cny",x.get("cost_cny")) is not None]
                budget_row=round(sum(reserved),8) if reserved else 0.0
                budget_spend += budget_row
                if any(x.get("budget_blocked") for x in meter):
                    budget_exhausted=True
                    status="NOT_RUN_BUDGET_CAP"
                    note=f"Request blocked before upstream forwarding at configured cap {args.max_cost_cny:.4f} CNY."
                else:
                    status="ERROR"
                    note=str(exc).replace("\n"," ")[:1000]
                rows.append({"run_id":run_id,"task_id":task["id"],"origin":task["origin"],"framework":framework,
                    "model_id":model_cfg["model_id"],"status":status,"first_compile":"NOT_RUN","final_compile":"NOT_RUN",
                    "test_passed":"","test_total":"","verifier_status":"NOT_RUN","cost_cny":row_cost,
                    "notes":note})
            completed_row=next((row for row in reversed(rows) if row.get("run_id")==run_id),None)
            if completed_row is not None:
                rows=[row for row in rows if row.get("run_id")!=run_id]
                rows.append(completed_row)
                write_csv(output,rows)
            existing_by_id[run_id]=completed_row or {}
            print(f"{idx}/{len(run_specs)} {run_id}: {existing_by_id[run_id].get('status')} cost={existing_by_id[run_id].get('cost_cny')} CNY; total={total_spend:.6f} CNY")
    finally:
        if relay and relay.poll() is None:
            relay.terminate()
            try: relay.wait(timeout=5)
            except subprocess.TimeoutExpired: relay.kill()
        shutil.rmtree(pi_dir,ignore_errors=True)
    rows.sort(key=lambda row:int((row.get("run_id") or "0").split("-",1)[0]) if (row.get("run_id") or "0").split("-",1)[0].isdigit() else 0)
    write_csv(output,rows)
    summary={"run_rows":len(rows),"cost_cny":round(total_spend,8),"budget_accounted_cny":round(budget_spend,8),
             "budget_limit_cny":args.max_cost_cny,"pilot":args.pilot,
             "dataset_total":data["task_count"],"planned_cells":len(run_specs),"results_csv":str(output),
             "usage_log":str(log_path),"resumed":bool(args.resume),"max_output_tokens":max_tokens,
             "run_status":"COMPLETE" if len(rows)==len(run_specs) and all(row.get("status") in reusable_statuses for row in rows) else "INCOMPLETE"}
    output.with_name(output.stem+"_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__": main()
