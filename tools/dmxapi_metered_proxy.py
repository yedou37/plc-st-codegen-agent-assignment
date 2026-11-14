"""Loopback-only DMXAPI relay that records usage metadata, never prompts or keys."""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UPSTREAM = "https://www.dmxapi.cn"
ALLOWED_MODELS = {"gpt-6.1-sol", "deepseek-v4.1-flash-1017"}

class Relay(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class BudgetLedger:
    """Reserve headroom before each request and account provider-reported cost."""
    def __init__(self, limit_cny: float, reserve_cny: float, max_output_tokens: int,
                 model_reserves: dict[str, float] | None = None):
        self.limit_cny = limit_cny
        self.reserve_cny = reserve_cny
        self.max_output_tokens = max_output_tokens
        self.model_reserves = model_reserves or {}
        self.spent_cny = 0.0
        self.in_flight_cny = 0.0
        self.active_reserves: dict[int, float] = {}
        self.lock = threading.Lock()

    def reserve(self, model: str | None = None) -> bool:
        with self.lock:
            amount = self.model_reserves.get(model, self.reserve_cny)
            if self.spent_cny + self.in_flight_cny + amount > self.limit_cny:
                return False
            self.in_flight_cny += amount
            self.active_reserves[threading.get_ident()] = amount
            return True

    def settle(self, cost_cny):
        with self.lock:
            amount = self.active_reserves.pop(threading.get_ident(), self.reserve_cny)
            self.in_flight_cny = max(0.0, self.in_flight_cny - amount)
            # If the provider omits cost, charge the reserve locally so the next
            # request fails closed instead of treating an unknown charge as zero.
            charged = amount if cost_cny is None else max(0.0, float(cost_cny))
            self.spent_cny += charged
            return charged

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PLCExperimentRelay/1.0"

    def log_message(self, fmt, *args):
        # Default HTTP logs can accidentally contain request paths or identifiers.
        return

    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 2_000_000:
                self.send_error(413)
                return
            raw = self.rfile.read(size)
            payload = json.loads(raw.decode("utf-8"))
            model = payload.get("model")
            if model not in ALLOWED_MODELS:
                self.send_error(403, "model not allowed")
                return
            max_tokens = payload.get("max_tokens", payload.get("max_completion_tokens"))
            if not isinstance(max_tokens, int) or max_tokens < 1 or max_tokens > self.server.budget.max_output_tokens:
                self.send_error(400, "request output exceeds configured token limit")
                return
            api_key = os.environ.get("DMXAPI_API_KEY")
            if not api_key:
                self.send_error(503, "DMXAPI_API_KEY is not available in relay process")
                return
        except Exception:
            self.send_error(400, "invalid request")
            return

        if not self.server.budget.reserve(model):
            self.server.log_usage({"model":model,"http_status":429,"prompt_tokens":None,
                "completion_tokens":None,"total_tokens":None,"cost_cny":None,
                "budget_blocked":True,"timestamp_utc":datetime.now(timezone.utc).isoformat()})
            body = json.dumps({"error":{"message":"DMXAPI spend reserve reached the configured budget cap",
                "type":"budget_cap"}}).encode("utf-8")
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            return

        upstream_req = urllib.request.Request(
            UPSTREAM + self.path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization":"Bearer " + api_key,
                     "Content-Type":"application/json",
                     "Accept":"text/event-stream" if payload.get("stream") else "application/json"},
            method="POST")
        started = time.perf_counter()
        details = {"model":model,"http_status":None,"prompt_tokens":None,"completion_tokens":None,
                   "total_tokens":None,"cost_cny":None,"provider_cost":None}
        try:
            with urllib.request.urlopen(upstream_req, timeout=240) as response:
                details["http_status"] = response.status
                content_type = response.headers.get("Content-Type", "application/json")
                if payload.get("stream"):
                    self.send_response(response.status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    pending = []
                    while True:
                        line = response.readline()
                        if not line:
                            break
                        self.wfile.write(line)
                        self.wfile.flush()
                        if line.startswith(b"data:"):
                            value = line[5:].strip()
                            if value == b"[DONE]":
                                _collect_stream_usage(pending, details)
                                pending = []
                            elif value:
                                pending.append(value)
                    if pending:
                        _collect_stream_usage(pending, details)
                else:
                    response_body = response.read()
                    try:
                        body_json = json.loads(response_body.decode("utf-8"))
                        _collect_usage(body_json, details)
                    except Exception:
                        pass
                    self.send_response(response.status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(response_body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(response_body)
        except urllib.error.HTTPError as exc:
            details["http_status"] = exc.code
            response_body = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response_body)
        except Exception as exc:
            details["http_status"] = 599
            body = json.dumps({"error":{"message":str(exc),"type":"relay_error"}}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        finally:
            details["elapsed_ms"] = round((time.perf_counter()-started)*1000)
            details["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
            details["budget_reserve_cny"] = self.server.budget.active_reserves.get(threading.get_ident(),
                                                                                   self.server.budget.reserve_cny)
            details["budget_charged_cny"] = self.server.budget.settle(details["cost_cny"])
            self.server.log_usage(details)
            api_key = None

def _collect_usage(data, target):
    usage = data.get("usage") or {}
    target["prompt_tokens"] = usage.get("prompt_tokens", usage.get("input_tokens"))
    target["completion_tokens"] = usage.get("completion_tokens", usage.get("output_tokens"))
    target["total_tokens"] = usage.get("total_tokens")
    cost = usage.get("cost")
    if cost is not None:
        target["provider_cost"] = cost
        if isinstance(cost, str):
            cleaned = cost.replace("¥", "").replace("￥", "").replace(",", "").strip()
            try: target["cost_cny"] = float(cleaned)
            except ValueError: pass
        elif isinstance(cost, (int,float)):
            target["cost_cny"] = float(cost)

def _collect_stream_usage(chunks, target):
    for raw in chunks:
        try:
            data = json.loads(raw.decode("utf-8"))
            if data.get("usage"):
                _collect_usage(data, target)
        except Exception:
            continue

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--log-file", required=True)
    ap.add_argument("--max-cost-cny", type=float, required=True)
    ap.add_argument("--request-reserve-cny", type=float, default=0.15)
    ap.add_argument("--gpt-request-reserve-cny", type=float, default=None)
    ap.add_argument("--deepseek-request-reserve-cny", type=float, default=None)
    ap.add_argument("--max-output-tokens", type=int, default=768)
    args = ap.parse_args()
    if args.max_cost_cny <= 0 or args.request_reserve_cny <= 0 or args.request_reserve_cny >= args.max_cost_cny:
        raise SystemExit("budget and per-request reserve must be positive; reserve must be below budget")
    if args.max_output_tokens < 1:
        raise SystemExit("max-output-tokens must be positive")
    log_path = Path(args.log_file).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    class Server(Relay):
        def log_usage(self, record):
            with lock:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False)+"\n")
                    f.flush()
    server = Server(("127.0.0.1", args.port), Handler)
    model_reserves = {}
    if args.gpt_request_reserve_cny is not None:
        model_reserves["gpt-6.1-sol"] = args.gpt_request_reserve_cny
    if args.deepseek_request_reserve_cny is not None:
        model_reserves["deepseek-v4.1-flash-1017"] = args.deepseek_request_reserve_cny
    if any(value <= 0 for value in model_reserves.values()):
        raise SystemExit("model request reserves must be positive")
    server.budget = BudgetLedger(args.max_cost_cny,args.request_reserve_cny,args.max_output_tokens,model_reserves)
    server.serve_forever(poll_interval=0.2)

if __name__ == "__main__": main()
