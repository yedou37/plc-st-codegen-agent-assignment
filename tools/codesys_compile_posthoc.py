"""Compile one IEC 61131-3 ST POU with the installed CODESYS profile."""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import hashlib
from pathlib import Path

from codesys_invocation import source_pous, compile_caller, SourceSyntaxError


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = "CODESYS V3.5 SP22 Patch 4"
DEVICE_NAME = "CODESYS Control Win V3 x64"
DEVICE_ID = "0000 0004"


def find_codesys() -> Path:
    configured = os.environ.get("CODESYS_EXE")
    candidates = [Path(configured)] if configured else []
    programs = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    candidates.extend(sorted(programs.glob("CODESYS*/CODESYS/Common/CODESYS.exe"), reverse=True))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("CODESYS.exe not found; set CODESYS_EXE to its full path")


def split_pou(source: str) -> dict:
    """Separate a complete emitted ST POU into CODESYS declaration/body parts."""
    source = source.lstrip("\ufeff")
    lines = source.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    # Markdown code fences are presentation wrappers, not IEC source tokens.
    lines = [line for line in lines
             if not re.match(r"^\s*```(?:st|iecst|structured\s+text)?\s*$", line, re.IGNORECASE)]
    header_re = re.compile(
        r"^\s*(PROGRAM|FUNCTION_BLOCK|FUNCTION)\s+([A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s*:\s*(.+?))?\s*$",
        re.IGNORECASE,
    )
    header_index = None
    match = None
    for index, line in enumerate(lines):
        found = header_re.match(line)
        if found:
            header_index, match = index, found
            break
    if match is None:
        raise ValueError("No PROGRAM, FUNCTION_BLOCK, or FUNCTION declaration found")

    kind, name, return_type = match.group(1).upper(), match.group(2), match.group(3)
    return_type = return_type.strip() if return_type else None
    if kind == "FUNCTION" and not return_type:
        raise ValueError("FUNCTION declaration must specify a return type")

    end_re = re.compile(r"^\s*END_(?:PROGRAM|FUNCTION_BLOCK|FUNCTION)\s*;?\s*$", re.IGNORECASE)
    var_re = re.compile(r"^\s*VAR(?:_[A-Z_]+)?(?:\s+.*)?\s*$", re.IGNORECASE)
    end_var_re = re.compile(r"^\s*END_VAR\s*;?\s*$", re.IGNORECASE)

    # The declaration starts with the mandatory POU header. Consume any
    # leading comments and contiguous VAR blocks; the rest is implementation.
    decl_end = header_index + 1
    cursor = decl_end
    while cursor < len(lines):
        probe = cursor
        in_comment = False
        while probe < len(lines):
            stripped = lines[probe].strip()
            if not stripped:
                probe += 1
                continue
            if in_comment or stripped.startswith("(*"):
                if "*)" in stripped:
                    in_comment = False
                else:
                    in_comment = True
                probe += 1
                continue
            break
        if probe >= len(lines) or not var_re.match(lines[probe]):
            break
        if not end_var_re.match(lines[probe]):
            block_end = probe + 1
            while block_end < len(lines) and not end_var_re.match(lines[block_end]):
                block_end += 1
            if block_end >= len(lines):
                raise ValueError("Variable declaration block is missing END_VAR")
            decl_end = block_end + 1
            cursor = decl_end
        else:
            break

    declaration = "\n".join(lines[header_index:decl_end]).strip() + "\n"
    body_lines = lines[decl_end:]
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    while body_lines and end_re.match(body_lines[-1]):
        body_lines.pop()
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
    implementation = "\n".join(body_lines).strip() + "\n"
    return {"kind": kind, "name": name, "return_type": return_type,
            "declaration": declaration, "implementation": implementation}


def type_declarations(source: str, task_id: str) -> list[str]:
    """Extract supplied DUTs and add benchmark-defined external record types."""
    declarations = []
    names = set()
    for match in re.finditer(r"\bTYPE\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*.*?\bEND_TYPE\b", source,
                            flags=re.IGNORECASE | re.DOTALL):
        block = match.group(0).strip()
        name = match.group(1)
        if re.search(r"\bSTRUCT\b", block, re.IGNORECASE):
            declarations.append(block)
            names.add(name.lower())
    benchmark_types = {
        "P07": ("ST_Pump", "TYPE ST_Pump :\nSTRUCT\n    priority : INT;\n    selection : BOOL;\n    RunComd : BOOL;\nEND_STRUCT\nEND_TYPE"),
        "P17": ("ST_Recipe", "TYPE ST_Recipe :\nSTRUCT\n    recipeID : INT;\n    ingredientType : INT;\n    ingredientRatio : REAL;\n    productionTemperature : REAL;\nEND_STRUCT\nEND_TYPE"),
    }
    if task_id.upper() in benchmark_types:
        dut_name, declaration = benchmark_types[task_id.upper()]
        if re.search(r"\b" + re.escape(dut_name) + r"\b", source, re.IGNORECASE) and dut_name.lower() not in names:
            declarations.append(declaration)
            names.add(dut_name.lower())
    return declarations


def script_source(input_path: Path, project_path: Path, result_path: Path, output_path: Path,
                  dut_declarations: list[str], exit_process: bool = True) -> str:
    pous = source_pous(input_path.read_text(encoding="utf-8-sig"), split_pou)
    caller = compile_caller(pous)
    values = {
        "input_path": str(input_path.resolve()),
        "project_path": str(project_path.resolve()),
        "result_path": str(result_path.resolve()),
        "output_path": str(output_path.resolve()),
    }
    embedded = "\n".join(f"{key.upper()} = {value!r}" for key, value in values.items())
    embedded += "\nDUT_DECLARATIONS = " + repr(dut_declarations)
    embedded += "\nSOURCE_POUS = " + repr(pous) + "\nCALLER = " + repr(caller)
    exit_line = 'system.exit(0 if result.get("status") == "PASS" else 1)' if exit_process else "pass"
    return f'''# IronPython script executed by the installed CODESYS profile.
import io, json, re, traceback
from scriptengine import *
{embedded}
result = {{"status":"ERROR", "errors":[], "warnings":[]}}
project = None
try:
    project = projects.create(PROJECT_PATH)
    devices = device_repository.get_all_devices("{DEVICE_NAME}", None)
    matches = [item for item in devices if item.device_id.id == "{DEVICE_ID}"]
    if not matches: raise Exception("Installed CODESYS Control Win x64 device description is unavailable")
    def version_key(item):
        try: return tuple(int(part) for part in item.device_id.version.split("."))
        except Exception: return (0,)
    target = sorted(matches, key=version_key, reverse=True)[0]
    project.add("Device", target.device_id)
    app = list(project.find("Application", True))[0]
    for dut_source in DUT_DECLARATIONS:
        dut_match = re.search(r"^\\s*TYPE\\s+([A-Za-z_][A-Za-z0-9_]*)\\s*:", dut_source, re.IGNORECASE | re.MULTILINE)
        if not dut_match: raise Exception("Invalid posthoc DUT declaration")
        dut = app.create_dut(dut_match.group(1), DutType.Structure)
        dut.textual_declaration.replace(dut_source)
    for source_pou in SOURCE_POUS:
        kind, name = source_pou["kind"], source_pou["name"]
        if kind == "PROGRAM": pou = app.create_pou(name, PouType.Program, ImplementationLanguages.st)
        elif kind == "FUNCTION_BLOCK": pou = app.create_pou(name, PouType.FunctionBlock, ImplementationLanguages.st)
        else: pou = app.create_function(name, source_pou["return_type"], ImplementationLanguages.st)
        pou.textual_declaration.replace(source_pou["declaration"])
        pou.textual_implementation.replace(source_pou["implementation"])
    runner = app.create_pou(CALLER["name"], PouType.Program, ImplementationLanguages.st)
    runner.textual_declaration.replace(CALLER["declaration"])
    runner.textual_implementation.replace(CALLER["implementation"])
    task_config = app.create_task_configuration()
    task = task_config.create_task("MainTask")
    task.kind_of_task = KindOfTask.Cyclic
    task.interval = "t#50ms"
    task.pous.add(CALLER["name"])
    standard_libraries = [library for library in librarymanager.get_all_libraries()
                          if str(library.title) == "Standard" and str(library.company) == "System"
                          and str(library.version) == "3.5.22.0"]
    if not standard_libraries: raise Exception("Standard (System) library is unavailable")
    app.get_library_manager().add_library(standard_libraries[0])
    for reference in app.get_library_manager().references:
        if getattr(reference, "is_placeholder", False) and reference.placeholder_name == "IoStandard":
            reference.default_resolution = "IoStandard, 3.5.22.0 (System)"
    project.save()
    for category in system.get_message_categories(False):
        system.clear_messages(category)
    app.rebuild()
    result["referenced_pous"] = CALLER["referenced_pous"]
    result["pou"] = {{"kind":SOURCE_POUS[0]["kind"], "name":SOURCE_POUS[0]["name"],
                     "device_name":"{DEVICE_NAME}",
                     "device_id":target.device_id.id,
                     "device_version":target.device_id.version}}
    for category in system.get_message_categories():
        category_name = str(system.get_message_category_description(category))
        for message in system.get_message_objects(category, Severity.FatalError | Severity.Error):
            result["errors"].append({{"category":category_name, "severity":"Error", "prefix":str(message.prefix), "number":str(message.number), "text":str(message.text)}})
        for message in system.get_message_objects(category, Severity.Warning):
            result["warnings"].append({{"category":category_name, "text":str(message.text)}})
    result["status"] = "PASS" if not result["errors"] else "FAIL"
except Exception as error:
    result["error"] = str(error)
    result["traceback"] = traceback.format_exc()
finally:
    if project is not None:
        try: project.close()
        except Exception: pass
with io.open(RESULT_PATH, "w", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=True, indent=2)
print(json.dumps(result, ensure_ascii=True))
{exit_line}
'''


def compile_one(source_path: Path, task_id: str, output_path: Path, timeout: int = 120) -> dict:
    started = time.perf_counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        source = source_path.read_text(encoding="utf-8-sig")
        pous = source_pous(source, split_pou)
        compile_caller(pous)
        dut_declarations = type_declarations(source, task_id)
        executable = find_codesys()
        profile = os.environ.get("CODESYS_PROFILE", DEFAULT_PROFILE)
        with tempfile.TemporaryDirectory(prefix="plc_codesys_") as temp:
            temp_path = Path(temp)
            project_path = temp_path / (re.sub(r"[^A-Za-z0-9_]", "_", task_id) + ".project")
            result_path = temp_path / "result.json"
            script_path = temp_path / "compile.py"
            launcher_path = temp_path / "launch.ps1"
            stdout_path = temp_path / "codesys.stdout.txt"
            stderr_path = temp_path / "codesys.stderr.txt"
            script_path.write_text(script_source(source_path, project_path, result_path, output_path,
                                                 dut_declarations), encoding="utf-8")
            launcher_path.write_text(
                "param([string]$Executable,[string]$Profile,[string]$ScriptPath,[string]$StdoutPath,[string]$StderrPath)\n"
                "$arguments = '--profile=\"' + $Profile + '\" --runscript=\"' + $ScriptPath + '\" --noUI'\n"
                "$process = Start-Process -FilePath $Executable -ArgumentList $arguments -PassThru -Wait `\n"
                "    -WindowStyle Hidden -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath\n"
                "exit $process.ExitCode\n", encoding="utf-8")
            powershell = shutil.which("powershell.exe") or "powershell.exe"
            process = subprocess.run(
                [powershell, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 str(launcher_path), str(executable), profile, str(script_path), str(stdout_path), str(stderr_path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, check=False, cwd=str(ROOT))
            ide_stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
            ide_stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
            ide_result = {}
            if result_path.exists():
                try: ide_result = json.loads(result_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError: pass
            status = ide_result.get("status") if ide_result else None
            if status not in ("PASS", "FAIL"):
                status = "UNAVAILABLE"
            elif process.returncode != 0 and status == "PASS":
                status = "UNAVAILABLE"
            result = {"status":status, "task_id":task_id, "source":str(source_path.resolve()),
                      "source_sha256":hashlib.sha256(source_path.read_bytes()).hexdigest(),
                      "posthoc_duts":[re.search(r"TYPE\s+([A-Za-z_][A-Za-z0-9_]*)", block, re.IGNORECASE).group(1)
                                       for block in dut_declarations],
                      "build_adapter":"v2: Standard + task DUTs + reachable calls with bound input and IN_OUT storage",
                      "compiler":str(executable), "profile":profile,
                      "version":(ide_result.get("pou") or {}).get("device_version"),
                      "return_code":process.returncode, "elapsed_ms":round((time.perf_counter()-started)*1000),
                      "pou":ide_result.get("pou"), "referenced_pous":ide_result.get("referenced_pous", []), "errors":ide_result.get("errors", []),
                      "warnings":ide_result.get("warnings", []), "error":ide_result.get("error"),
                      "stdout":ide_stdout + process.stdout, "stderr":ide_stderr + process.stderr}
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return result
    except subprocess.TimeoutExpired as error:
        result = {"status":"TIMEOUT", "task_id":task_id, "elapsed_ms":timeout*1000,
                  "stdout":str(error.stdout or ""), "stderr":str(error.stderr or "")}
    except SourceSyntaxError as error:
        result = {"status":"FAIL", "task_id":task_id, "elapsed_ms":round((time.perf_counter()-started)*1000),
                  "error":str(error), "stage":"source_parse"}
    except Exception as error:
        result = {"status":"UNAVAILABLE", "task_id":task_id, "elapsed_ms":round((time.perf_counter()-started)*1000),
                  "error":str(error)}
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--task-id", default="manual")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compile_one(args.source, args.task_id, args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
