"""Compile archived ST in a fresh, offline application with explicit POU calls."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from codesys_compile_posthoc import DEFAULT_PROFILE, DEVICE_ID, DEVICE_NAME, find_codesys


class SourceError(ValueError):
    """The archived text does not contain a complete supported ST unit."""


class BindingError(ValueError):
    """The harness cannot supply a typed argument for this interface."""


def mask_comments(source):
    # Keep offsets and newlines, and keep comment delimiters inside strings inert.
    pattern = r"'(?:\$[\s\S]|[^'])*'|\"(?:\$[\s\S]|[^\"])*\"|\(\*[\s\S]*?(?:\*\)|\Z)|//[^\n]*"

    def replace(match):
        value = match.group()
        if value.startswith("(*") and not value.endswith("*)"):
            raise SourceError("Unterminated ST block comment")
        if value.startswith(("(*", "//")):
            return re.sub(r"[^\n]", " ", value)
        return value

    return re.sub(pattern, replace, source)


def source_units(source):
    fence = re.search(r"(?im)^[ \t]*\x60{3}(?:st|iecst|structured[ \t]+text)?[ \t]*\n", source)
    if fence:
        body = source[fence.end():]
        close = re.search(r"(?m)^[ \t]*\x60{3}[ \t]*$", body)
        source = body[:close.start()] if close else body
    masked = mask_comments(source)
    header = re.compile(r"(?im)^[ \t]*(PROGRAM|FUNCTION_BLOCK|FUNCTION|TYPE)[ \t]+"
                        r"([A-Za-z_]\w*)[ \t]*(?::[ \t]*([^\n]*?))?[ \t]*$")
    terminal = re.compile(r"(?im)^[ \t]*END_(PROGRAM|FUNCTION_BLOCK|FUNCTION|TYPE)\b[ \t]*;?[ \t]*$")
    pos, units = 0, []
    while masked[pos:].strip():
        pos += len(masked[pos:]) - len(masked[pos:].lstrip())
        start = header.match(masked, masked.rfind("\n", 0, pos) + 1)
        if not start:
            raise SourceError("Unexpected source outside a POU or DUT: " + masked[pos:].splitlines()[0][:100])
        kind, name, annotation = start.groups()
        kind = kind.upper()
        end = terminal.search(masked, start.end())
        next_start = header.search(masked, start.end())
        if not end or end[1].upper() != kind or (next_start and next_start.start() < end.start()):
            raise SourceError(f"{name}: missing matching END_{kind}")
        if kind == "TYPE":
            if not re.search(r"(?im)^[ \t]*STRUCT\b", masked[start.end():end.start()]):
                raise BindingError(f"{name}: harness supports structure DUTs")
            units.append(dict(kind=kind, name=name, declaration=source[start.start():end.end()]))
        else:
            if (kind == "FUNCTION") != bool(annotation):
                raise SourceError(f"{name}: invalid POU header")
            decl_end = start.end()
            sections = []
            while True:
                opening = re.match(r"\s*(VAR(?:_[A-Z]+)*)(?:[ \t]+[^\n]*)?[ \t]*\n",
                                   masked[decl_end:end.start()], re.I)
                if not opening:
                    break
                offset = decl_end + opening.end()
                closing = re.search(r"(?im)^[ \t]*END_VAR\b[ \t]*;?[ \t]*$",
                                    masked[offset:end.start()])
                if not closing:
                    raise SourceError(f"{name}: missing END_VAR")
                sections.append((opening[1].upper(), masked[offset:offset + closing.start()]))
                decl_end = offset + closing.end()
            if not masked[decl_end:end.start()].strip():
                raise SourceError(f"{name}: empty implementation")
            units.append(dict(kind=kind, name=name, return_type=annotation,
                              declaration=source[start.start():decl_end],
                              implementation=source[decl_end:end.start()],
                              sections=sections))
        pos = end.end()
    if not any(unit["kind"] != "TYPE" for unit in units):
        raise SourceError("No candidate POU found")
    if len({unit["name"].lower() for unit in units}) != len(units):
        raise SourceError("Duplicate source object names")
    return units


ROOT = Path(__file__).resolve().parents[1]


def prepare(source, task_id):
    units = source_units(source)
    known_dut = {"P07": "ST_Pump", "P08": "ST_AnalogChannel", "P17": "ST_Recipe"}.get(task_id)
    if known_dut and known_dut.lower() not in {u["name"].lower() for u in units}:
        units.extend(source_units_for_dut(known_dut))
    occupied = {u["name"].lower() for u in units}
    prefix = "AuditHarness"
    while any(name.startswith(prefix.lower()) for name in occupied):
        prefix += "X"
    decl, calls = [], []
    for i, unit in enumerate(units):
        kind = unit["kind"]
        if kind == "TYPE":
            continue
        name = unit["name"]
        instance = f"{prefix}Instance{i}"
        arguments = []
        for section, fields in unit.pop("sections"):
            if section != "VAR_IN_OUT" and not (section == "VAR_INPUT" and kind == "FUNCTION"):
                continue
            for field in fields.split(";"):
                if not field.strip():
                    continue
                match = re.fullmatch(r"\s*(\w+(?:\s*,\s*\w+)*)\s*:\s*(.+?)\s*", field, re.S)
                if not match:
                    raise BindingError(f"{name}: unsupported argument declaration {field.strip()!r}")
                dtype = match[2].split(":=", 1)[0].strip()
                if re.fullmatch(r"VARIANT", dtype, re.I):
                    raise BindingError(f"{name}: no concrete CODESYS VARIANT binding for {match[1]}")
                # A variable-length formal array receives a fixed-size caller array.
                dtype = re.sub(r"(ARRAY\s*\[)([^]]+)(\])",
                               lambda m: m[1] + m[2].replace("*", "1..5") + m[3], dtype, flags=re.I)
                for field_name in re.split(r"\s*,\s*", match[1]):
                    variable = f"{prefix}Arg{i}_{len(arguments)}"
                    decl.append(f"    {variable} : {dtype};")
                    arguments.append(f"{field_name} := {variable}")
        target = name
        if kind == "FUNCTION_BLOCK":
            decl.append(f"    {instance} : {name};")
            target = instance
        call = f"{target}({', '.join(arguments)})"
        if kind == "FUNCTION":
            decl.append(f"    {instance} : {unit['return_type']};")
            call = f"{instance} := {call}"
        calls.append(call + ";")
    return {"units": units, "runner": prefix, "calls": calls,
            "declaration": "\n".join([f"PROGRAM {prefix}", "VAR"] + decl + ["END_VAR"])}


def source_units_for_dut(name):
    path = ROOT / "st" / "support_types" / (name + ".st")
    return [{"kind": "TYPE", "name": name, "declaration": path.read_text(encoding="utf-8")}]


IDE_SCRIPT = r'''
import io, json, os, traceback
from scriptengine import *

def compile_candidate(job):
    result = {"status": "UNAVAILABLE", "errors": [], "warnings": [],
              "calls": job["calls"], "signatures": {}}
    project = None
    try:
        project = projects.create(job["project"])
        devices = device_repository.get_all_devices(DEVICE_NAME, None)
        target = sorted((d for d in devices if d.device_id.id == DEVICE_ID),
                        key=lambda d: tuple(int(x) for x in str(d.device_id.version).split(".")))[-1]
        project.add("Device", target.device_id)
        app = list(project.find("Application", True))[0]
        result["device_version"] = str(target.device_id.version)
        for unit in job["units"]:
            if unit["kind"] == "TYPE":
                obj = app.create_dut(unit["name"], DutType.Structure)
                obj.textual_declaration.replace(unit["declaration"])
        candidates = []
        for unit in job["units"]:
            kind, name = unit["kind"], unit["name"]
            if kind == "TYPE": continue
            if kind == "PROGRAM": obj = app.create_pou(name, PouType.Program, ImplementationLanguages.st)
            elif kind == "FUNCTION_BLOCK": obj = app.create_pou(name, PouType.FunctionBlock, ImplementationLanguages.st)
            else: obj = app.create_function(name, unit["return_type"], ImplementationLanguages.st)
            obj.textual_declaration.replace(unit["declaration"])
            obj.textual_implementation.replace(unit["implementation"])
            candidates.append((name, obj))
        runner = app.create_pou(job["runner"], PouType.Program, ImplementationLanguages.st)
        runner.textual_declaration.replace(job["declaration"])
        runner.textual_implementation.replace("\n".join(job["calls"]))
        task = app.create_task_configuration().create_task("AuditTask")
        task.kind_of_task = KindOfTask.Cyclic
        task.interval = "t#50ms"
        task.pous.add(job["runner"])
        manager = app.get_library_manager()
        library = next(lib for lib in librarymanager.get_all_libraries()
                       if str(lib.title) == "Standard" and str(lib.company) == "System"
                       and str(lib.version) == "3.5.22.0")
        manager.add_library(library)
        for ref in manager.references:
            if getattr(ref, "is_placeholder", False) and ref.placeholder_name == "IoStandard":
                ref.default_resolution = "IoStandard, 3.5.22.0 (System)"
            if "Standard" in str(getattr(ref, "name", "")):
                ref.qualified_only = False
                if getattr(ref, "is_placeholder", False) and ref.placeholder_name == "Standard":
                    ref.default_resolution = "Standard, 3.5.22.0 (System)"
        project.save()
        for category in system.get_message_categories(False): system.clear_messages(category)
        try:
            app.rebuild()
            app.create_boot_application(job["boot"], False, False)
        except Exception as exc:
            result["error"] = str(exc)
        for category in system.get_message_categories():
            for msg in system.get_message_objects(category, Severity.FatalError | Severity.Error):
                result["errors"].append({"number": str(msg.number), "text": str(msg.text)})
            for msg in system.get_message_objects(category, Severity.Warning):
                result["warnings"].append({"text": str(msg.text)})
        if result["errors"]:
            result["status"] = "FAIL"
        elif not result.get("error") and os.path.isfile(job["boot"]) and os.path.getsize(job["boot"]):
            result["boot_bytes"] = os.path.getsize(job["boot"])
            for name, obj in candidates + [(job["runner"], runner)]:
                crc = obj.get_signature_crc(app)
                if not crc:
                    raise Exception("Missing compiled signature for " + name)
                result["signatures"][name] = str(crc)
            result["status"] = "PASS"
        else:
            result["error"] = result.get("error") or "CODESYS produced no boot application"
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        if project is not None:
            project.close()
    return result

with io.open(JOBS_PATH, "r", encoding="utf-8") as stream:
    jobs = json.load(stream)
for job in jobs:
    result = compile_candidate(job)
    with io.open(job["result"], "w", encoding="utf-8") as stream:
        stream.write(unicode(json.dumps(result, ensure_ascii=True)))
system.exit(0)
'''


def compile_batch(entries, timeout):
    """Return one result per (task_id, source path) in input order."""
    with tempfile.TemporaryDirectory(prefix="plc_linked_") as directory:
        temp = Path(directory)
        results, jobs = [], []
        for i, (task_id, source_path) in enumerate(entries):
            raw = source_path.read_bytes()
            record = {"task_id": task_id, "source_sha256": hashlib.sha256(raw).hexdigest()}
            results.append(record)
            try:
                job = prepare(raw.decode("utf-8-sig").replace("\r\n", "\n"), task_id)
            except (SourceError, UnicodeError) as exc:
                record.update(status="INVALID_SOURCE", error=str(exc))
                continue
            except BindingError as exc:
                record.update(status="UNSUPPORTED_BINDING", error=str(exc))
                continue
            job.update(index=i, project=str(temp / f"unit{i}.project"),
                       boot=str(temp / f"unit{i}.app"), result=str(temp / f"unit{i}.json"))
            jobs.append(job)
        if not jobs:
            return results
        jobs_path = temp / "jobs.json"
        jobs_path.write_text(json.dumps(jobs), encoding="utf-8")
        script = temp / "compile.py"
        script.write_text(f"JOBS_PATH = {str(jobs_path)!r}\n" + IDE_SCRIPT, encoding="utf-8")
        status, detail = "UNAVAILABLE", "CODESYS did not write a per-candidate result"
        try:
            executable = find_codesys()
            profile = os.environ.get("CODESYS_PROFILE", DEFAULT_PROFILE)
            script.write_text(f"DEVICE_NAME = {DEVICE_NAME!r}\nDEVICE_ID = {DEVICE_ID!r}\n"
                              + script.read_text(encoding="utf-8"), encoding="utf-8")
            launcher = temp / "launch.ps1"
            launcher.write_text(
                "param($Exe,$Profile,$Script,$Output,$Errors)\n"
                "$arguments = '--profile=\"' + $Profile + '\" --runscript=\"' + $Script + '\" --noUI'\n"
                "$process = Start-Process -FilePath $Exe -ArgumentList $arguments -PassThru -Wait"
                " -WindowStyle Hidden -RedirectStandardOutput $Output -RedirectStandardError $Errors\n"
                "exit $process.ExitCode\n", encoding="utf-8")
            stdout, stderr = temp / "stdout.txt", temp / "stderr.txt"
            process = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 str(launcher), str(executable), profile, str(script), str(stdout), str(stderr)],
                cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=timeout, check=False)
            detail += f" (IDE exit code {process.returncode})"
            detail += " ".join([process.stdout, process.stderr] + [
                p.read_text(encoding="utf-8", errors="replace")[-3000:]
                for p in (stdout, stderr) if p.exists()])
        except subprocess.TimeoutExpired:
            status, detail = "TIMEOUT", "CODESYS batch deadline exceeded"
        except OSError as exc:
            detail = str(exc)
        for job in jobs:
            record = results[job["index"]]
            try:
                record.update(json.loads(Path(job["result"]).read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                record.update(status=status, error=detail)
        return results
