"""Model adapters for OpenAI-compatible APIs and a user-supplied CLI baseline."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

class AdapterError(RuntimeError):
    pass

def chat_completion(messages: list[dict], model_cfg: dict) -> dict:
    key_env = model_cfg.get("api_key_env", "")
    api_key = os.environ.get(key_env, "") if key_env else ""
    if not api_key:
        raise AdapterError(f"Missing API credential environment variable: {key_env or '(unset)'}")
    base_url = model_cfg.get("base_url", "").rstrip("/")
    if not base_url:
        raise AdapterError("Model base_url is not configured")
    body = {"model": model_cfg["model_id"], "messages": messages,
            "temperature": float(model_cfg.get("temperature", 0)),
            "max_tokens": int(model_cfg.get("max_tokens", 8192))}
    request_params = model_cfg.get("request_params", {})
    if not isinstance(request_params, dict):
        raise AdapterError("Model request_params must be a JSON object")
    reserved = {"model", "messages", "max_tokens", "temperature"}
    if reserved.intersection(request_params):
        raise AdapterError("Model request_params cannot override core chat-completion fields")
    body.update(request_params)
    req = urllib.request.Request(base_url + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization":"Bearer "+api_key,"Content-Type":"application/json"}, method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=int(model_cfg.get("timeout_seconds", 180))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AdapterError(f"Model API HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AdapterError(f"Model API request failed: {exc}") from exc
    try:
        choice = payload["choices"][0]
        message = choice["message"]
        content = message.get("content")
    except (KeyError, IndexError, TypeError) as exc:
        raise AdapterError("Unexpected chat-completions response shape") from exc
    if isinstance(content, list):
        content = "\n".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
    usage = payload.get("usage") or {}
    detail = usage.get("completion_tokens_details") or {}
    return {"content":str(content or ""), "prompt_tokens":usage.get("prompt_tokens"),
            "completion_tokens":usage.get("completion_tokens"),
            "provider_cost":usage.get("cost"),
            "elapsed_ms":round((time.perf_counter()-started)*1000), "raw_id":payload.get("id"),
            "response_meta":{"finish_reason":choice.get("finish_reason"),
                             "reasoning_chars":len(message.get("reasoning_content") or ""),
                             "reasoning_tokens":detail.get("reasoning_tokens")}}

def run_cli_baseline(prompt: str, model_cfg: dict) -> dict:
    """Run an existing coding-agent CLI without invoking a shell."""
    command = model_cfg.get("command")
    if not command:
        raise AdapterError("Baseline CLI command is not configured")
    prompt_file = Path(model_cfg["prompt_file"])
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt, encoding="utf-8")
    argv = [str(part).format(model=model_cfg.get("model_id", ""), prompt_file=str(prompt_file.resolve()))
            for part in command]
    started = time.perf_counter()
    env = os.environ.copy()
    if model_cfg.get("env"):
        env.update({str(k):str(v) for k,v in model_cfg["env"].items()})
    try:
        cp = subprocess.run(argv, input=prompt, text=True, encoding="utf-8", errors="replace",
                            capture_output=True, env=env,
                            timeout=int(model_cfg.get("timeout_seconds", 900)), check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdapterError(f"Baseline CLI failed: {exc}") from exc
    if cp.returncode:
        raise AdapterError(f"Baseline CLI exit {cp.returncode}: {cp.stderr[-3000:]}")
    events, final_text, usage = [], "", {}
    for line in cp.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        if event.get("type") == "message_end" and event.get("message", {}).get("role") == "assistant":
            message = event["message"]
            content = message.get("content", [])
            final_text = "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
            usage = message.get("usage", {})
    if not final_text:
        final_text = cp.stdout
    if not any(e.get("type") == "agent_settled" and not e.get("aborted") for e in events):
        raise AdapterError("Pi did not report a completed agent_settled event")
    return {"content":final_text, "prompt_tokens":usage.get("input"),
            "completion_tokens":usage.get("output"), "provider_cost":None,
            "elapsed_ms":round((time.perf_counter()-started)*1000), "raw_id":None,
            "events":events, "agent_usage":usage}
