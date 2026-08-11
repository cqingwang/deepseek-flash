# 08 Verification and Performance

## 8.1 API Health

```bash
curl http://<IP_MGMT_A>:8888/health          # expect 200
curl http://<IP_MGMT_A>:8888/v1/models       # expect max_model_len: 1048576
```

## 8.2 Minimal Chat

```bash
curl http://<IP_MGMT_A>:8888/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash-0731",
       "messages":[{"role":"user","content":"What is 17*23? Answer with a number only."}],
       "temperature":0,"max_tokens":200,
       "chat_template_kwargs":{"thinking":false}}'
```

Expected: `391`, returns in seconds. Remove `thinking:false` (or keep the default `max`) if you want
the model to reason.

## 8.3 Bundled Scripts (Annotation 1: the smoke test)

The repo ships `smoke-deepseek-v4-flash-dspark.sh` (concurrent smoke), `status-...`, `logs-...`,
`stop-...`:

```bash
cd ~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark
./smoke-deepseek-v4-flash-dspark.sh          # 6 concurrent by default; CONCURRENCY=12 ./smoke-... to adjust
./status-deepseek-v4-flash-dspark.sh
./logs-deepseek-v4-flash-dspark.sh
```

Measured result: **6/6 requests succeeded**.

## 8.4 Benchmark (watch the thinking level)

```bash
cd ~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark
python3 scripts/benchmark-0731.py \
  --base-url http://127.0.0.1:8888/v1 \
  --model deepseek-v4-flash-0731 \
  --prompt-lengths 256,2048,8192 --concurrency 1,3,6 \
  --output results/benchmark-smoke.json
```

> **Important pitfall**: with `DEFAULT_THINKING=max` the model produces extremely long reasoning
> chains (a single request can generate tens of thousands of tokens), making each case take 10–20+
> minutes or run away. **Before benchmarking, set `DEFAULT_THINKING` to `low` or `off` in
> `.env.dspark` and restart the service.**

## 8.5 Performance Expectations

Measured on this setup (DSpark MTP5, NVFP4 DS-MLA, TP=2):

| Metric | Measured/expected |
|---|---|
| Single-stream decode (incl. reasoning) | ~60–80 tok/s (78–80 warm) |
| Prefill | ~99 tok/s at 372-token prompt; up to ~2000 tok/s on short prompts |
| DSpark acceptance | ~91% (mean acceptance length 5.5+) |
| GPU utilization | ~95% |
| KV pool | ~2.3M tokens across 2 nodes (measured 17.02+16.64 GiB at `GPU_MEMORY_UTILIZATION_TEXT=0.835`; legacy 0.80 was ~1.83M) |
| High-concurrency aggregate (community, thinking=off) | up to ~340 tok/s @ c32 |

The KV pool is shared: total live tokens ≤ ~2.3M, so long context and high concurrency trade off
against each other (details in [chapter 09](09-ops.md)).

## 8.6 Real-world Results: Long Agent / Vibe-Coding Runs

## 8.7 Long-context verification (Issue #22 fix, measured 2026-08-11)

> Since 94baabf, the start script auto-applies the Issue #22 hotfix so `nvfp4_ds_mla` no longer
> dispatches to the slow bf16 kernel (~1.0 tok/s) above 600K context but to the fast fp8 kernel.
> Method: calibrate a prompt via `/tokenize`, stream a request, measure TTFT and decode tok/s
> (script: `scripts/longctx-verify.py`).

| Test | prompt tokens | TTFT | prefill tok/s | decode tok/s |
|---|---|---|---|---|
| Baseline (short) | 8,299 | 9.1 s | 908 | **71.6** |
| Long #1 | 620,107 | 502.9 s (cold) | 1,233 | **73.0** |
| Long #2 | 780,109 | 201.8 s (warm) | 3,867 | **70.2** |

**Conclusion**: decode stays at 70–73 tok/s above 600K tokens, matching the short-context baseline —
the fix is effective (pre-fix the same scenario was ~1.0 tok/s, a 16× slowdown). First-request TTFT
includes FlashInfer autotune cache load + GPU warm-up; later requests are warm.

> Hands-on experience from running many consecutive Agent rounds (vibe-coding a dual-node
> monitoring dashboard plus long-chat sessions) on the dual DGX Spark setup, with live-dashboard
> screenshots from the accompanying (vibe-coded) monitoring panel.

**Bottom line**: this “2× DGX Spark × DeepSeek-V4-Flash-0731” setup is **fully usable with a good
experience** — not at “it boots” demo level, but solid enough to serve as a daily driver.

| Dimension | Measured | Notes |
|---|---|---|
| Decode speed | **60–70 tok/s (single session)** | Better than expected: long chats and multi-round Agent work barely feel like waiting |
| Stability | **Hours-long runs with no crashes** | No OOM, no NCCL hiccups — vibe-coding marathons never dropped once |
| GPU temperature | **~70°C while running Agents** | Plenty of headroom before the thermal wall (90°C+), fans quiet |
| Onboarding | Minimal | The service is persistent; usable as a local inference backend in minutes |

> No ambiguity in the takeaway: **two DGX Sparks are exactly enough to hold deepseek-v4-flash-0731**;
> 60–70 tok/s single-stream comfortably covers daily vibe coding, and most of the effort is front-loaded
> in the initial deployment — day-to-day use is zero-maintenance.

The companion monitoring dashboard (the same vibe-coding output, standalone repo
[`dgx-spark-2-deepseek-flash-dashboard`](https://github.com/maliubiao/dgx-spark-2-deepseek-flash-dashboard)) shows GPU util/temp/power, decode throughput, speculative-
decoding acceptance, KV cache and prefix hit rate in real time. The three screenshots below are live:

![Panel screenshot 1 — real-time overview](../docs/perf/vibe-panel-1.png)

![Panel screenshot 2 — GPU/host & throughput](../docs/perf/vibe-panel-2.png)

![Panel screenshot 3 — performance details](../docs/perf/vibe-panel-3.png)

> Screenshots are from a live environment; see the panel repo's README/PREVIEWS for page details and
> how to regenerate them.


