#!/usr/bin/env python3
"""Verify Issue #22 fix: nvfp4_ds_mla long-context decode speed (>600K tokens)."""
import json, sys, time, urllib.request

BASE = "http://127.0.0.1:8888/v1"
MODEL = "deepseek-v4-flash-0731"
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 620000

def request_json(url, body, timeout=3600):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def tokenize(prompt):
    return request_json(BASE.replace("/v1", "") + "/tokenize", {"model": MODEL, "prompt": prompt})["count"]

# ---- build prompt to target length ----
unit = "benchmark context datum "
text = "unique request longctx-verify " + unit * max(1, TARGET // 3)
while True:
    count = tokenize(text)
    print(f"  prompt tokens so far: {count}", flush=True)
    if count >= TARGET:
        break
    text += unit * max(1, (TARGET - count) // 3)
print(f"final prompt tokens: {count}", flush=True)

# ---- streaming request ----
body = {"model": MODEL,
        "messages": [{"role": "user", "content": text + "\nReply with exactly: VERIFIED"}],
        "max_tokens": 64, "temperature": 0.2,
        "stream": True, "stream_options": {"include_usage": True}}
req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
started = time.perf_counter()
first = None
out = []
usage = None
with urllib.request.urlopen(req, timeout=3600) as r:
    for raw in r:
        line = raw.decode().strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        ev = json.loads(line[6:])
        ch = ev.get("choices") or []
        d = ch[0].get("delta", {}) if ch else {}
        if first is None and (d.get("content") or d.get("reasoning") or d.get("reasoning_content")):
            first = time.perf_counter()
            print(f"  TTFT: {first - started:.2f}s", flush=True)
        out.append(d.get("content") or d.get("reasoning") or "")
        if ev.get("usage"):
            usage = ev["usage"]
finished = time.perf_counter()
pt = usage["prompt_tokens"] if usage else count
ot = usage["completion_tokens"] if usage else 0
decode_s = finished - (first or started)
print(json.dumps({
    "prompt_tokens": pt,
    "completion_tokens": ot,
    "ttft_s": round((first or finished) - started, 2),
    "prefill_tok_s": round(pt / max(0.001, (first or finished) - started), 1),
    "decode_s": round(decode_s, 2),
    "output_tok_s": round(ot / max(0.001, decode_s), 1),
    "verdict": "FIX EFFECTIVE (fast fp8 path)" if ot / max(0.001, decode_s) >= 8 else "STILL SLOW (bf16 path)"
}, indent=2))
