# DeepSeek-V4-Flash-0731 on Dual DGX Spark – Reproduction Guide (English)

> This document records the complete process of building a two-node NVIDIA DGX Spark (GB10)
> cluster over a direct 200GbE QSFP link and serving **DeepSeek-V4-Flash-0731** with vLLM
> (Anemll DSpark image, TP=2, 1M context). It is a step-by-step tutorial so another pair of
> machines can reproduce the setup.
>
> **All sensitive information has been masked**: every IP, hostname, Wi-Fi/proxy credential
> and SSH key is represented by `<PLACEHOLDER>`; see [VARIABLES.md](VARIABLES.md).
>
> 中文版：[../README.md](../README.md)

## Effect Preview (Live Deployment)

> After deployment, the companion dashboards (standalone repo [`dgx-spark-2-deepseek-flash-dashboard`](https://github.com/maliubiao/dgx-spark-2-deepseek-flash-dashboard))
> show live status. Screenshots below are from a real environment:
> **60–70 tok/s (single session)**, GPU **~70°C**, hours-long runs without crashes;
> full record in [chapter 8.6](docs/08-verify.md).

![Panel preview 1 — real-time overview](../docs/perf/vibe-panel-1.png)

![Panel preview 2 — GPU/host & throughput](../docs/perf/vibe-panel-2.png)

![Panel preview 3 — performance details](../docs/perf/vibe-panel-3.png)

## 1. Architecture and Results

```
┌──────────────┐   QSFP112 DAC direct (200GbE)   ┌──────────────┐
│  DGX Spark A │◄══════════════════════════════►│  DGX Spark B │
│  (head)      │  RoCE: 10.100.192.x / 193.x     │  (worker)    │
│  GB10 ×1     │                                 │  GB10 ×1     │
└──────┬───────┘                                 └──────────────┘
       │ Management LAN (wired / Wi-Fi, same subnet)
       ▼
   OpenAI-compatible API: http://<IP_MGMT_A>:8888/v1
```

- Model: `deepseek-ai/DeepSeek-V4-Flash-0731` (official 0731 GA, I8/FP4 quantized, **166.9 GB**, 48 shards)
- Engine: vLLM 0.25.2 (`ghcr.io/anemll/dspark-vllm-gx10:0.1.1`), TP=2, DSpark MTP5 speculative decoding
- KV cache: `nvfp4_ds_mla`, shared pool of about **2.3M tokens** across both nodes (94baabf + util 0.835, measured), `max_model_len=1048576`
- Measured performance (community + this setup): single stream about 60–96 tok/s, warm decode ~78–80 tok/s,
  DSpark acceptance ~91%, up to ~340 tok/s aggregate at high concurrency (community data, benchmark with
  `DEFAULT_THINKING=low/off`)

## 2. Chapter Index

| Chapter | Content | Approx. time |
|---|---|---|
| [01 Hardware & Topology](docs/01-hardware.md) | Machines, cable, physical-port mapping | 30 min |
| [02 System Initialization](docs/02-system-init.md) | First boot, OTA, firmware, driver checks | 1–2 h |
| [03 Base Configuration](docs/03-basics.md) | Users, SSH, network, proxy (masked template) | 30 min |
| [04 Two-Node Cluster](docs/04-cluster-assistant.md) | NVIDIA Sync + Cluster Assistant | 30 min |
| [05 NCCL Validation](docs/05-nccl.md) | Build NCCL + two-node communication test | 30–60 min |
| [06 Model Download](docs/06-model-download.md) | Official manifest, chunked downloader, fabric sync, integrity | 2–4 h (bandwidth dependent) |
| [07 Deploy & Launch](docs/07-deploy.md) | Image, config, start service | 30 min + ~8 min cold start |
| [08 Verification & Performance](docs/08-verify.md) | API, smoke, benchmark, expectations | 15 min |
| [09 Operations](docs/09-ops.md) | Auto-resume, hardening, troubleshooting | ongoing |
| [10 Appendices](docs/10-appendices.md) | Upstream repos, file inventory, variables | — |

## 3. Quick Start (TL;DR)

Prerequisites: two networked DGX Spark units (system ≥ 2026-04), one QSFP112 DAC cable,
a computer with NVIDIA Sync installed (**Windows, macOS, or Ubuntu — any of them works**, see chapter 04).

```bash
# 0. Replace every <PLACEHOLDER> in VARIABLES.md
# 1. Hardware: cable → system update → passwordless SSH (chapters 01–03)
# 2. Cluster: NVIDIA Sync → Cluster Assistant (chapter 04)
# 3. NCCL: chapter 05
# 4. Model: chapter 06 (restricted networks already covered; use official HF on open networks)
# 5. Deploy: chapter 07 → ./start-deepseek-v4-flash-dspark.sh
# 6. Verify: curl http://<IP_MGMT_A>:8888/v1/models
```

## 4. Package Layout

> The clone directory name equals the repo name (`dgx-spark-2-deepseek-flash-0731`).
> Current tree:

```text
dgx-spark-2-deepseek-flash-0731/
├── README.md                    # Chinese overview (incl. effect preview screenshots)
├── LICENSE                      # MIT
├── VARIABLES.md                 # Placeholder reference (Chinese)
├── .gitignore                   # .DS_Store / *.log
├── en/                          # English version (this tree)
├── docs/                        # Chinese chapters 01–10 + DOWNLOADS + perf/ images
└── scripts/
    ├── dsv4-chunkdl.py          # Chunked downloader (sha256 + resume)
    ├── resume-downloads.sh      # Boot-time auto-resume
    ├── repro-preflight.sh       # Environment preflight check
    ├── .env.dspark.example      # Two-node vLLM config template (masked)
    ├── dspark-vllm-start.sh     # systemd start wrapper (head, masked template)
    ├── dspark-vllm-stop.sh      # systemd stop wrapper (head, masked template)
    ├── dspark-vllm-ensure.sh    # worker container ensure script (masked template)
    ├── dspark-vllm.service      # head systemd unit
    ├── dspark-vllm-worker.service  # worker systemd unit
    └── install-autostart.sh     # one-shot auto-start installer
```

> The `scripts/` directory is shared by both language versions. English chapters reference
> `../scripts/...` paths.

## 5. Official Documentation and Downloads

**Read [docs/DOWNLOADS.md](docs/DOWNLOADS.md) first** — it lists everything you need to download
(NVIDIA Sync, system OTA, NCCL sources, the Anemll image, the 166.9 GB model, Python tooling, and
the deployment repo), each with its official source, size, destination and verification command.

Key official references:

- [NVIDIA Sync installation](https://docs.nvidia.com/sync/latest/getting-started.html)
- [Cluster Assistant](https://docs.nvidia.com/sync/latest/cluster-assistant.html)
- [DGX Spark User Guide / First Boot](https://docs.nvidia.com/dgx/dgx-spark/first-boot.html)
- [NCCL playbook](https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/nccl/README.md)
- [vLLM playbook](https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/vllm/README.md)
- [Model card](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731)
- [Anemll image source](https://github.com/Anemll/dspark-vllm-gx10)
- [MiaAI deployment repo](https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark)

> **Source-material index**: the complete mapping of every referenced repo/website/image/model —
> including which are bundled with this package vs referenced — is in
> [§10.2 of the English appendix](docs/10-appendices.md).

## 6. Security and Masking Notes

- No real IP, hostname, MAC, Wi-Fi/proxy password or SSH private key appears anywhere.
- Set your own `sudo` passwords; never use example credentials.
- The model and images come from official/public sources; verify image digests before use (chapter 06).
- If you are not on a restricted (China) network, replace the mirror sources with the official ones
  (alternatives are noted in each chapter).
