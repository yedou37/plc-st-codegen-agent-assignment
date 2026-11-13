"""Compile a generated ST POU and execute JSON-driven assertions on CODESYS Control Win.

The suite uses a small cyclic PROGRAM to instantiate the candidate POU and run
deterministic input sequences. Results stay under experiments/local_runs; this
tool never edits the official 120-cell experiment matrix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from run_p02_codesys_runtime import (  # noqa: E402
    DEFAULT_PROFILE,
    DEVICE_ID,
    DEVICE_NAME,
    find_codesys,
    split_pou,
    split_pous,
)
from codesys_compile_posthoc import type_declarations  # noqa: E402


TYPE_MAP = {
    "BOOL": "BOOL", "INT": "INT", "DINT": "DINT", "SINT": "SINT",
    "USINT": "USINT", "UINT": "UINT", "UDINT": "UDINT", "WORD": "WORD",
    "DWORD": "DWORD", "REAL": "REAL", "LREAL": "LREAL", "TIME": "TIME",
    "LTIME": "LTIME", "STRING": "STRING(254)", "BYTE": "BYTE",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def literal(value, type_name: str | None = None) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        if re.match(r"^(?:T|LT)#[0-9A-Za-z_]+$", value, re.I) or re.match(
            r"^(?:BOOL|(?:U|S)?INT|DINT|REAL|LREAL|WORD|DWORD|UDINT|UINT|USINT|BYTE)#", value, re.I
        ) or re.match(r"^16#[0-9A-F]+$", value, re.I):
            return value
        if type_name and type_name.upper().startswith("STRING"):
            return "'" + value.replace("'", "''") + "'"
        return value
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        if type_name and type_name.upper() in ("WORD", "DWORD"):
            return f"{type_name.upper()}#16#{value:X}" if value >= 0 else str(value)
        return str(value)
    raise TypeError(f"Unsupported ST literal: {value!r}")


def variable_types(pous: list[dict]) -> dict[str, str]:
    found: dict[str, str] = {}
    for pou in pous:
        for line in pou["declaration"].splitlines():
            if line.strip().startswith(("(*", "//")):
                continue
            match = re.match(r"\s*([A-Za-z_]\w*)\s*:\s*([^;(*]+)", line)
            if match:
                name, raw_type = match.group(1), match.group(2).strip()
                type_match = re.match(r"(?:ARRAY\s*\[[^]]+\]\s+OF\s+)?([A-Za-z_]\w*)", raw_type, re.I)
                if type_match:
                    found[name.lower()] = type_match.group(1).upper()
    return found


def expected_type(path: str, value, types: dict[str, str]) -> str:
    base = re.split(r"[.\[]", path, maxsplit=1)[0].lower()
    known = types.get(base)
    if known in TYPE_MAP:
        return TYPE_MAP[known]
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, float):
        return "REAL"
    if isinstance(value, int):
        return "DINT"
    if isinstance(value, str) and value.upper().startswith("T#"):
        return "TIME"
    return "STRING(254)"


def prepare_candidate(source: str, task_id: str) -> tuple[list[dict], list[str]]:
    try:
        pous = split_pous(source)
    except ValueError:
        pous = [split_pou(source)]
    primary = next((item for item in pous if item["kind"] != "FUNCTION"), pous[0])
    # A PROGRAM and its cyclic task body can be hosted as an FB instance in the
    # harness; this keeps the original scan logic while making inputs writable.
    if primary["kind"] == "PROGRAM":
        primary["kind"] = "FUNCTION_BLOCK"
        primary["declaration"] = re.sub(
            r"^\s*PROGRAM\b", "FUNCTION_BLOCK", primary["declaration"], count=1, flags=re.I
        )
    if primary["kind"] == "FUNCTION":
        raise ValueError("Runtime harness currently requires a PROGRAM or FUNCTION_BLOCK POU")
    dut_types = type_declarations(source, task_id)
    if task_id.upper() == "P08" and not re.search(r"\bTYPE\s+ST_AnalogChannel\b", source, re.I):
        dut_types.append("""TYPE ST_AnalogChannel :
STRUCT
    enable : BOOL;
    hiLIM : REAL;
    loLIM : REAL;
    bipolar : BOOL;
    measuringMode : INT;
    retVal : WORD;
    outputValue : REAL;
END_STRUCT
END_TYPE""")
    return pous, dut_types


def build_driver(pou_name: str, suite: dict, pous: list[dict]) -> tuple[str, list[dict]]:
    cases = suite["cases"]
    if not cases:
        raise ValueError("Suite has no cases")
    types = variable_types(pous)
    assertions: list[dict] = []
    scan_observers = set()
    stages: list[str] = []
    stage_no = 0
    for case_index, case in enumerate(cases, start=1):
        actions = case.get("steps", [])
        if not actions:
            raise ValueError(f"{case.get('id')} has no steps")
        for step_index, action in enumerate(actions, start=1):
            lines = []
            for path, value in action.get("set", {}).items():
                target = path[1:] if path.startswith("@") else "dut." + path
                type_key = path[1:].split(".")[0].lower() if path.startswith("@") else path.split(".")[0].lower()
                lines.append(f"{target} := {literal(value, types.get(type_key))};")
            lines.extend(action.get("before_call", []))
            lines.append(suite.get("call", "dut();"))
            for check_index, expression in enumerate(action.get("scan_checks", []), start=1):
                obs_name = f"scan_c{case_index}_s{step_index}_a{check_index}"
                scan_observers.add(obs_name)
                # Latch every scan's result, so a later correct value cannot erase a failure.
                lines.append(f"{obs_name} := {obs_name} AND ({expression});")
                lines.append(f"case_pass[{case_index}] := case_pass[{case_index}] AND {obs_name};")
                assertions.append({"case_index":case_index, "step_index":step_index,
                    "assertion_index":check_index, "path":"scan invariant",
                    "expression":expression, "expected":True, "observer":obs_name, "type":"BOOL"})
            cycles = int(action.get("cycles", 1))
            if cycles < 1:
                raise ValueError("cycles must be >= 1")
            lines.append("wait_counter := wait_counter + 1;")
            lines.append(f"IF wait_counter >= {cycles} THEN")
            lines.append("    wait_counter := 0;")
            for assertion_index, (path, expected) in enumerate(action.get("expect", {}).items(), start=1):
                obs_name = f"obs_c{case_index}_s{step_index}_a{assertion_index}"
                target = path[1:] if path.startswith("@") else f"dut.{path}"
                target_type = expected_type(path, expected, types)
                assertions.append({
                    "case_index": case_index,
                    "step_index": step_index,
                    "assertion_index": assertion_index,
                    "path": path,
        "expression": target,
                    "expected": expected,
                    "observer": obs_name,
                    "type": target_type,
                })
                rhs = literal(expected, target_type)
                lines += [
                    f"    {obs_name} := {target};",
                    f"    case_pass[{case_index}] := case_pass[{case_index}] AND ({target} = {rhs});",
                ]
            is_last_step = step_index == len(actions)
            if is_last_step:
                lines += [
                    f"    IF case_pass[{case_index}] THEN",
                    "        passed := passed + 1;",
                    "    ELSE",
                    "        failed := failed + 1;",
                    "        IF first_failed_case = 0 THEN first_failed_case := " + str(case_index) + "; END_IF;",
                    "    END_IF;",
                ]
            next_stage = stage_no + 1
            if is_last_step and case_index == len(cases):
                lines += ["    test_done := TRUE;", f"    stage := {next_stage};"]
            else:
                lines += [f"    stage := {next_stage};"]
            lines.append("END_IF;")
            stages.append(f"{stage_no}:\n    " + "\n    ".join(lines))
            stage_no = next_stage

    case_init = ", ".join("TRUE" for _ in cases)
    declarations = [
        "PROGRAM RuntimeTest",
        "VAR",
        f"    dut : {pou_name};",
        "    stage : DINT := 0;",
        "    wait_counter : DINT := 0;",
        "    test_done : BOOL := FALSE;",
        "    passed : DINT := 0;",
        "    failed : DINT := 0;",
        "    first_failed_case : DINT := 0;",
        f"    case_pass : ARRAY[1..{len(cases)}] OF BOOL := [{case_init}];",
    ]
    for declaration in suite.get("declarations", []):
        declarations.append("    " + declaration.rstrip("; ") + ";")
    for assertion in assertions:
        initializer = " := TRUE" if assertion['observer'] in scan_observers else ""
        declarations.append(f"    {assertion['observer']} : {assertion['type']}{initializer};")
    declarations += ["END_VAR", ""]
    implementation = [
        "IF NOT test_done THEN",
        "    CASE stage OF",
        "        " + "\n        ".join(stages),
        "    END_CASE;",
        "END_IF;",
        "",
    ]
    driver = "\n".join(declarations + implementation)
    return driver, assertions


def runscript_source(pous: list[dict], dut_types: list[str], driver: str,
                     project_path: Path, result_path: Path, run_runtime: bool,
                     timeout_ms: int, assertions: list[dict], suite: dict) -> str:
    values = {
        "SOURCE_POUS": pous,
        "DUT_TYPES": dut_types,
        "DRIVER_DECL": split_pou(driver)["declaration"],
        "DRIVER_IMPL": split_pou(driver)["implementation"],
        "PROJECT_PATH": str(project_path.resolve()),
        "RESULT_PATH": str(result_path.resolve()),
        "PROGRESS_PATH": str(result_path.with_name("progress.json").resolve()),
        "RUN_RUNTIME": run_runtime,
        "RUNTIME_TIMEOUT_MS": timeout_ms,
        "ASSERTIONS": assertions,
        "TEST_CASES": [{"id": case["id"], "scenario": case.get("scenario", "")}
                       for case in suite["cases"]],
    }
    embedded = "\n".join("%s = %r" % (key, value) for key, value in values.items())
    body = r'''# IronPython script executed by the installed CODESYS profile.
import io, json, os, re, traceback, time
from scriptengine import *
__EMBEDDED__
result = {"status":"ERROR", "compile_errors":[], "compile_warnings":[], "runtime":{}}
project = None
online_app = None
gateway = None
def mark(stage, **details):
    with io.open(PROGRESS_PATH, "w", encoding="utf-8") as stream:
        json.dump({"stage":stage, "timestamp":time.time(), "details":details}, stream)
try:
    try:
        if hasattr(system, "script_prompt_handling"):
            system.script_prompt_handling = ScriptPromptHandling.LogPrompts
            system.log_prompt_details = True
    except Exception:
        system.prompt_handling = PromptHandling.LogSimplePrompts | PromptHandling.LogMessageKeys
    mark("project_create")
    project = projects.create(PROJECT_PATH)
    devices = device_repository.get_all_devices("__DEVICE_NAME__", None)
    matches = [item for item in devices if item.device_id.id == "__DEVICE_ID__"]
    if not matches:
        raise Exception("Installed CODESYS Control Win x64 device description is unavailable")
    device_info = sorted(matches, key=lambda item: tuple(int(x) for x in str(item.device_id.version).split(".")), reverse=True)[0]
    project.add("Device", device_info.device_id)
    app = list(project.find("Application", True))[0]
    for type_source in DUT_TYPES:
        type_match = re.search(r"^\s*TYPE\s+([A-Za-z_]\w*)\s*:", type_source, re.I | re.M)
        if not type_match:
            raise Exception("Invalid DUT type declaration")
        dut = app.create_dut(type_match.group(1), DutType.Structure)
        dut.textual_declaration.replace(type_source)
    for source_pou in SOURCE_POUS:
        kind, name = source_pou["kind"], source_pou["name"]
        if kind == "PROGRAM": pou = app.create_pou(name, PouType.Program, ImplementationLanguages.st)
        elif kind == "FUNCTION_BLOCK": pou = app.create_pou(name, PouType.FunctionBlock, ImplementationLanguages.st)
        else: pou = app.create_function(name, source_pou["return_type"], ImplementationLanguages.st)
        pou.textual_declaration.replace(source_pou["declaration"])
        pou.textual_implementation.replace(source_pou["implementation"])
    runner = app.create_pou("RuntimeTest", PouType.Program, ImplementationLanguages.st)
    runner.textual_declaration.replace(DRIVER_DECL)
    runner.textual_implementation.replace(DRIVER_IMPL)
    libs = [lib for lib in librarymanager.get_all_libraries()
            if str(lib.title) == "Standard" and str(lib.company) == "System" and str(lib.version) == "3.5.22.0"]
    if not libs:
        raise Exception("Standard (System) 3.5.22.0 library is unavailable")
    app.get_library_manager().add_library(libs[0])
    task_config = app.create_task_configuration()
    task = task_config.create_task("MainTask")
    task.kind_of_task = KindOfTask.Cyclic
    task.interval = "t#50ms"
    task.pous.add("RuntimeTest")
    for reference in app.get_library_manager().references:
        if getattr(reference, "is_placeholder", False) and reference.placeholder_name == "IoStandard":
            reference.default_resolution = "IoStandard, 3.5.22.0 (System)"
        if "Standard" in str(getattr(reference, "name", "")):
            # Standard is qualified-only by default in the scripting API. The
            # candidate POUs use the conventional unqualified IEC names TON,
            # R_TRIG, LEN, and similar symbols.
            try:
                reference.qualified_only = False
            except Exception:
                pass
            if getattr(reference, "is_placeholder", False) and reference.placeholder_name == "Standard":
                reference.default_resolution = "Standard, 3.5.22.0 (System)"
    project.save()
    mark("compile")
    for category in system.get_message_categories(False): system.clear_messages(category)
    app.rebuild()
    for category in system.get_message_categories():
        category_name = str(system.get_message_category_description(category))
        for message in system.get_message_objects(category, Severity.FatalError | Severity.Error):
            result["compile_errors"].append({"category":category_name, "text":str(message.text)})
        for message in system.get_message_objects(category, Severity.Warning):
            result["compile_warnings"].append({"category":category_name, "text":str(message.text)})
    result["target"] = {"name":"__DEVICE_NAME__", "id":"__DEVICE_ID__", "version":str(device_info.device_id.version)}
    if result["compile_errors"]:
        result["status"] = "COMPILE_FAIL"
    else:
        result["status"] = "COMPILE_PASS"
        if RUN_RUNTIME:
            try:
                mark("gateway_setup")
                drivers = list(online.gateway_drivers.find_with_name("TCP/IP"))
                if not drivers: raise Exception("CODESYS TCP/IP gateway driver is unavailable")
                gateway = online.gateways.add_new_gateway("Codex runtime suite", {"IP-Address":"localhost", "Port":1217}, drivers[0])
                device = [obj for obj in project.find("Device", True) if obj.is_device][0]
                target_address = gateway.find_address_by_ip("127.0.0.1", 11740)
                device.set_gateway_and_address(gateway, target_address)
                project.save()
                runtime_user = os.environ.get("CODESYS_TEST_USER", "")
                runtime_password = os.environ.get("CODESYS_TEST_PASSWORD", "")
                if not runtime_user or not runtime_password:
                    raise Exception("Set CODESYS_TEST_USER and CODESYS_TEST_PASSWORD in the process environment")
                online.set_default_credentials(runtime_user, runtime_password)
                online.auth_fallback_modes = getattr(CredentialSourceKind, "None")
                mark("login")
                online_app = online.create_online_application(app)
                online_device = online_app.get_online_device()
                online_device.set_credentials_for_initial_user(runtime_user, runtime_password, True, False)
                online.set_specific_credentials(online_app, runtime_user, runtime_password)
                online_app.login(OnlineChangeOption.Try, False)
                if online_app.application_state != ApplicationState.run:
                    online_app.start()
                mark("runtime_started")
                done = False
                max_polls = max(1, int(RUNTIME_TIMEOUT_MS // 100))
                for attempt in range(max_polls):
                    system.delay(100)
                    value = str(online_app.read_value("RuntimeTest.test_done")).strip().upper()
                    if attempt % 10 == 0: mark("polling", poll=attempt + 1, done=value)
                    if value == "TRUE": done = True; break
                expressions = ["RuntimeTest.test_done", "RuntimeTest.passed", "RuntimeTest.failed",
                               "RuntimeTest.first_failed_case"]
                expressions += ["RuntimeTest.case_pass[%d]" % i for i in range(1, len(TEST_CASES) + 1)]
                for assertion in ASSERTIONS:
                    expressions.append("RuntimeTest." + assertion["observer"])
                values_read = online_app.read_values(expressions)
                value_map = dict(zip(expressions, values_read))
                case_results = []
                cursor = 4 + len(TEST_CASES)
                for case_index, case in enumerate(TEST_CASES, start=1):
                    case_pass = str(value_map.get("RuntimeTest.case_pass[%d]" % case_index, "FALSE")).strip().upper() in ("TRUE", "1")
                    observed = []
                    for assertion in [item for item in ASSERTIONS if item["case_index"] == case_index]:
                        key = "RuntimeTest." + assertion["observer"]
                        actual = value_map.get(key)
                        observed.append({"step":assertion["step_index"], "expression":assertion["expression"],
                                         "expected":assertion["expected"], "observed":actual})
                    case_results.append({"id":case["id"], "scenario":case.get("scenario", ""),
                                         "pass":case_pass, "assertions":observed})
                passed = int(str(value_map.get("RuntimeTest.passed", "0")).split("#")[-1])
                failed = int(str(value_map.get("RuntimeTest.failed", "0")).split("#")[-1])
                result["runtime"] = {"state":"COMPLETED" if done else "TIMEOUT", "passed":passed,
                                      "failed":failed, "first_failed_case":value_map.get("RuntimeTest.first_failed_case"),
                                      "cases":case_results}
                if done and failed == 0 and passed == len(TEST_CASES) and all(x["pass"] for x in case_results):
                    result["status"] = "RUNTIME_PASS"
                elif done:
                    result["status"] = "RUNTIME_FAIL"
                else:
                    result["status"] = "RUNTIME_TIMEOUT"
            except Exception as error:
                result["status"] = "RUNTIME_UNAVAILABLE"
                result["runtime"] = {"state":"UNAVAILABLE", "error":str(error), "traceback":traceback.format_exc()}
finally:
    mark("cleanup", status=result["status"])
    if online_app is not None:
        try:
            if online_app.application_state == ApplicationState.run: online_app.stop()
        except Exception: pass
        try: online_app.logout()
        except Exception: pass
    if gateway is not None:
        try: online.gateways.remove_gateway(gateway.guid)
        except Exception: pass
    try: online.clear_all_credentials()
    except Exception: pass
    if project is not None:
        try: project.save(); project.close()
        except Exception: pass
with io.open(RESULT_PATH, "w", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False))
if result["status"] not in ("COMPILE_PASS", "RUNTIME_PASS"):
    system.exit(1)
'''
    embedded = "\n".join("%s = %r" % (key, value) for key, value in values.items())
    result = body.replace("__EMBEDDED__", embedded)
    result = "# -*- coding: utf-8 -*-\n" + result
    return result.replace("__DEVICE_NAME__", DEVICE_NAME).replace("__DEVICE_ID__", DEVICE_ID)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    source_text = args.source.read_text(encoding="utf-8-sig")
    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    if suite.get("task_id") != args.task_id:
        raise SystemExit("suite task_id does not match --task-id")
    source_pous, dut_types = prepare_candidate(source_text, args.task_id)
    primary = next((item for item in source_pous if item["kind"] != "FUNCTION"), source_pous[0])
    driver, assertions = build_driver(primary["name"], suite, source_pous)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (args.output_dir or ROOT / "experiments/local_runs/codesys_runtime_suite" /
                  f"{args.task_id}_{args.source.parent.name}_{stamp}").resolve()
    try:
        output_dir.relative_to((ROOT / "experiments/local_runs").resolve())
    except ValueError:
        raise SystemExit("--output-dir must be under experiments/local_runs")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit("Output directory is not empty; choose a new local_runs path")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "suite.json").write_text(json.dumps(suite, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "driver.st").write_text(driver, encoding="utf-8")
    project_path = output_dir / "RuntimeTest.project"
    result_path = output_dir / "result.json"
    planned_cycles = sum(int(action.get("cycles", 1)) for case in suite["cases"] for action in case["steps"])
    timeout_ms = max(10000, planned_cycles * 50 + 15000)
    script_path = output_dir / "codesys_test.py"
    script_path.write_text(runscript_source(source_pous, dut_types, driver, project_path, result_path,
                                            args.run, timeout_ms, assertions, suite), encoding="utf-8")
    executable = find_codesys()
    command = '"%s" --profile="%s" --runscript="%s" --noUI' % (executable, args.profile, script_path)
    try:
        process = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True,
                                 encoding="mbcs", errors="replace", timeout=args.timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        (output_dir / "stdout.txt").write_text(str(exc.stdout or ""), encoding="utf-8")
        (output_dir / "stderr.txt").write_text(str(exc.stderr or ""), encoding="utf-8")
        print(json.dumps({"status":"CODESYS_PROCESS_TIMEOUT", "output_dir":str(output_dir)}, indent=2))
        return 2
    (output_dir / "stdout.txt").write_text(process.stdout or "", encoding="utf-8")
    (output_dir / "stderr.txt").write_text(process.stderr or "", encoding="utf-8")
    if not result_path.is_file():
        print(json.dumps({"status":"NO_RESULT", "exit_code":process.returncode,
                          "output_dir":str(output_dir), "stderr":(process.stderr or "")[-3000:]}, indent=2))
        return 2
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result.update({"task_id":args.task_id, "source":str(args.source.resolve()),
                   "source_sha256":sha256(args.source.read_bytes()), "suite":str(args.suite.resolve()),
                   "suite_sha256":sha256(args.suite.read_bytes()), "driver":str((output_dir / "driver.st").resolve()),
                   "driver_sha256":sha256(driver.encode("utf-8")),
                   "runner_sha256":sha256(Path(__file__).read_bytes()), "project":str(project_path),
                   "run_requested":args.run, "codesys_return_code":process.returncode})
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key:value for key,value in result.items() if key not in ("codesys_stdout", "codesys_stderr")},
                     ensure_ascii=False, indent=2))
    return 0 if result["status"] == "COMPILE_PASS" and not args.run else (0 if result["status"] == "RUNTIME_PASS" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
