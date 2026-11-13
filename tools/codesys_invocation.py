"""Create compile-only call sites without changing candidate ST interfaces."""
from __future__ import annotations

import re


class SourceSyntaxError(ValueError):
    """The submitted source is incomplete before project construction."""


class UnsupportedBinding(ValueError):
    """A caller cannot be constructed safely for the declared interface."""


def source_pous(source: str, splitter) -> list[dict]:
    # Ignore presentation fences; require complete top-level source units.
    source = re.sub(r"^\s*```[^\n]*$", "", source, flags=re.M)
    headers = list(re.finditer(
        r"^\s*(PROGRAM|FUNCTION_BLOCK|FUNCTION)\s+([A-Za-z_]\w*)(?:\s*:\s*[^\n]+)?\s*$",
        source, flags=re.I | re.M))
    if not headers:
        raise SourceSyntaxError("No ST POU header found")
    pous = []
    for i, header in enumerate(headers):
        chunk = source[header.start():headers[i+1].start() if i+1 < len(headers) else len(source)]
        end = re.search(r"^\s*END_" + header.group(1) + r"\s*;?\s*$", chunk, re.I | re.M)
        if end is None:
            raise SourceSyntaxError("Missing END_" + header.group(1).upper() + " for " + header.group(2))
        try:
            pous.append(splitter(chunk[:end.end()]))
        except ValueError as exc:
            raise SourceSyntaxError(str(exc)) from exc
    if len({p['name'].lower() for p in pous}) != len(pous):
        raise SourceSyntaxError("Duplicate POU names")
    return pous


def parameters(declaration: str) -> list[tuple[str, str]]:
    text = re.sub(r"\(\*.*?\*\)|//[^\n]*", "", declaration, flags=re.S)
    result = []
    for block in re.finditer(r"\bVAR_(?:INPUT|IN_OUT)\b(.*?)\bEND_VAR\b", text, re.I | re.S):
        for statement in block.group(1).split(';'):
            statement = statement.strip()
            if not statement:
                continue
            match = re.fullmatch(r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*:\s*(.+)", statement, re.S)
            if not match:
                raise UnsupportedBinding("Cannot bind parameter declaration: " + statement)
            type_name = match.group(2).split(':=', 1)[0].strip()
            if re.search(r"\b(?:ANY\w*|VARIANT|REFERENCE)\b", type_name, re.I):
                raise UnsupportedBinding("Explicit caller fixture required for type " + type_name)
            # Open-array formal ports remain unchanged. Only caller storage is concrete.
            type_name = re.sub(r"\[([*\s,]+)\]", lambda m: '[' + ', '.join('0..1' for _ in m.group(1).split(',')) + ']', type_name)
            result.extend((name.strip(), type_name) for name in match.group(1).split(','))
    return result


def compile_caller(pous: list[dict]) -> dict:
    """Reference every POU from a cyclic program, including FBs and functions."""
    names = {p['name'].lower() for p in pous}
    name = 'BenchmarkCompileCaller'
    while name.lower() in names:
        name += '_'
    declarations, calls = [], []
    for i, pou in enumerate(pous):
        arguments = []
        for j, (formal, type_name) in enumerate(parameters(pou['declaration'])):
            actual = f'arg_{i}_{j}'
            declarations.append(f'    {actual} : {type_name};')
            arguments.append(f'{formal} := {actual}')
        target = pou['name']
        if pou['kind'] == 'FUNCTION_BLOCK':
            target = f'instance_{i}'
            declarations.append(f'    {target} : {pou["name"]};')
        call = target + '(' + ', '.join(arguments) + ')'
        if pou['kind'] == 'FUNCTION':
            declarations.append(f'    result_{i} : {pou["return_type"]};')
            call = f'result_{i} := ' + call
        calls.append(call + ';')
    return {'name': name, 'declaration': '\n'.join(['PROGRAM ' + name, 'VAR', *declarations, 'END_VAR']),
            'implementation': '\n'.join(calls), 'referenced_pous': [p['name'] for p in pous]}
