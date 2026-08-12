# Download Manifest (what to download, from where, and how to verify)

> Listed in execution order. **Official source** is what this project actually used; items marked
> "mirror" are only for restricted-network acceleration — use the official source on open networks.
> Every item includes a runnable verification command.

## 1. NVIDIA Sync (Windows / macOS / Ubuntu)

| Item | Value |
|---|---|
| Official source | [build.nvidia.com/spark/connect-to-your-spark](https://build.nvidia.com/spark/connect-to-your-spark) → download `nvidia-sync.dmg` |
| Docs | [docs.nvidia.com/sync/latest/getting-started.html](https://docs.nvidia.com/sync/latest/getting-started.html) |
| Size | ~100–200 MB |
| Install | **Windows**: run the downloaded `.exe` installer; **macOS**: drag the `.dmg` into Applications; **Ubuntu**: configure the official apt repo then `sudo apt install -y nvidia-sync` (commands in chapter 04) |
| Verify | App launches and onboarding works; on macOS, `xattr -d com.apple.quarantine "/Applications/NVIDIA Sync.app"` if macOS blocks it |

## 2. System OTA and Firmware (both Sparks)

| Item | Value |
|---|---|
| Official source | [DGX Spark User Guide](https://docs.nvidia.com/dgx/dgx-spark/); [First Boot](https://docs.nvidia.com/dgx/dgx-spark/first-boot.html); DGX Dashboard |
| Content | System software (requires ≥ 2026-04), ConnectX-7 / USBPD firmware |
| Size | several GB (apt incremental) |
| Verify | **After upgrading via the official flow** (Dashboard or `apt dist-upgrade` + `fwupdmgr`, see ch. 02 step 1): `cat /etc/dgx-release` for `DGX_OTA_VERSION`; `LC_ALL=C apt-cache policy dgx-spark-ota-update-meta` → `Installed` ≥ 26.04.1 (≥ 2026-04); `fwupdmgr get-devices \| grep -A2 MT2910` for ConnectX-7 firmware; only if the package was delivered with your OTA: `sudo nvidia-spark-ota-check summary` → `torn-score: 0` |

## 3. NCCL build dependency (both Sparks)

| Item | Value |
|---|---|
| Source | apt (Ubuntu official mirrors) |
| Package | `libopenmpi-dev` (~22 MB) |
| Verify | `dpkg -l libopenmpi-dev` |

## 4. NCCL source (both Sparks)

| Item | Value |
|---|---|
| Official source | <https://github.com/NVIDIA/nccl>, **tag `v2.30.7-1`** |
| Size | ~50 MB |
| Destination | `~/nccl/` |
| Verify | `git -C ~/nccl describe --tags` → `v2.30.7-1` |

## 5. nccl-tests source (both Sparks)

| Item | Value |
|---|---|
| Official source | <https://github.com/NVIDIA/nccl-tests>, pin `717b68318278e93f371d8ffb46b076069d7c7851` (2026-08-03) |
| Size | ~10 MB |
| Destination | `~/nccl-tests/` |
| Verify | `git -C ~/nccl-tests rev-parse HEAD` |

## 6. vLLM runtime image (one copy per Spark)

| Item | Value |
|---|---|
| Official source | `ghcr.io/anemll/dspark-vllm-gx10:0.1.1` ([source repo Anemll/dspark-vllm-gx10](https://github.com/Anemll/dspark-vllm-gx10)) |
| China mirror | `ghcr.nju.edu.cn/anemll/dspark-vllm-gx10:0.1.1` (layer digests verified identical to official) |
| Size | 9.79 GB compressed layers; 18.8 GB uncompressed |
| Verify | `docker image inspect --format "{{range .RepoDigests}}{{.}}{{end}}"` → expected digest `sha256:a83948492cf13df455170fb42885f5ef4db54fefe0feff0f841ecbff464ac9d8`; compare all 44 layer digests against the official manifest (chapter 07) |
| Note | The official vLLM playbook offers the NGC image `nvcr.io/nvidia/vllm:<tag>` ([NGC catalog](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm)), but the DSpark/NVFP4 path for DeepSeek-V4-Flash-0731 requires the Anemll image |

## 7. Model weights DeepSeek-V4-Flash-0731 (one copy per node)

| Item | Value |
|---|---|
| Official source | <https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731> (official `deepseek-ai` org, **not gated**) |
| China acceleration | `hf-mirror.com` (`HF_ENDPOINT=https://hf-mirror.com`) |
| Size | **166.9 GB**, 74 files / 48 safetensors shards |
| Destination | head: `$HOME/.cache/huggingface/models/DeepSeek-V4-Flash-0731/`; worker via 200G fabric rsync |
| Verify | official LFS sha256 manifest 74/74 passed on both nodes (chapter 06) |
| Note | Do not use the official HF downloader directly on restricted networks; use `scripts/dsv4-chunkdl.py` |

## 8. Python tooling (head only)

| Item | Value |
|---|---|
| Source | PyPI via `pip` (install into a venv `~/hf-venv`) |
| Packages | `huggingface_hub` (hf CLI), `hf_xet`, `httpx` |
| Purpose | generate the official sha256 manifest; chunked downloader runtime |
| Verify | `~/hf-venv/bin/hf version` |

## 9. Deployment repo (head)

| Item | Value |
|---|---|
| Official source | <https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark>, pin `a4ce87a2f47f1be8fe64c297a0cf33a9a5e509aa` (2026-08-04) |
| Size | ~10 MB |
| Destination | `$HOME/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark/` (the start script syncs required files to the worker) |
| Verify | `git rev-parse HEAD` |

## 10. Optional / alternatives

| Item | Source | Purpose |
|---|---|---|
| `aria2` (apt, ~2 MB) | Ubuntu mirrors | optional multi-connection downloader (this guide uses its own script) |
| naive proxy client | <https://github.com/klzgrad/naiveproxy/releases> (latest linux-arm64) | optional system proxy on restricted networks |
| Official playbook scripts `setup.sh` / `launch.sh` | [NVIDIA/dgx-spark-playbooks](https://github.com/NVIDIA/dgx-spark-playbooks) `nvidia/nccl/assets/` | fast NCCL install (manual commands in this guide are equivalent) |
| Official vLLM `run_cluster.sh` (Ray path, not used here) | <https://raw.githubusercontent.com/vllm-project/vllm/51c1ee9b7c8acbba4899a8ebffd390685d171946/examples/ray_serving/run_cluster.sh> | alternative launch from the official vLLM playbook |
| Alternative image family `aidendle94/sparkrun-vllm-ds4-gb10` | <https://hub.docker.com/r/aidendle94/sparkrun-vllm-ds4-gb10> | earlier community images (this guide uses Anemll 0.1.1) |

## 11. All official documentation paths

| Topic | Path |
|---|---|
| NVIDIA Sync installation | <https://docs.nvidia.com/sync/latest/getting-started.html> |
| Cluster Assistant | <https://docs.nvidia.com/sync/latest/cluster-assistant.html> |
| Sync download page | <https://build.nvidia.com/spark/connect-to-your-spark> |
| DGX Spark User Guide | <https://docs.nvidia.com/dgx/dgx-spark/> |
| DGX Spark First Boot | <https://docs.nvidia.com/dgx/dgx-spark/first-boot.html> |
| Connect two Sparks playbook | <https://build.nvidia.com/spark/connect-two-sparks> |
| NCCL playbook | <https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/nccl/README.md> |
| vLLM playbook | <https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/vllm/README.md> |
| Model card | <https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731> |
| HF API (sha256 manifest) | <https://huggingface.co/api/models/deepseek-ai/DeepSeek-V4-Flash-0731> and `/tree/main?recursive=true&expand=true` |
| Anemll image source | <https://github.com/Anemll/dspark-vllm-gx10> |
| MiaAI deployment repo | <https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark> |
| NGC vLLM catalog (alternative image) | <https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm> |
