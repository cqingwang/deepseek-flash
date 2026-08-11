# 07 Deploy and Launch (Anemll vLLM + MiaAI recipe)

## 7.1 Pull the Runtime Image (both nodes)

```bash
# open network: docker pull ghcr.io/anemll/dspark-vllm-gx10:0.1.1
# China mainland: ghcr.io blob downloads are throttled to ~17 KB/s; use the mirror then retag
docker pull ghcr.nju.edu.cn/anemll/dspark-vllm-gx10:0.1.1
docker tag ghcr.nju.edu.cn/anemll/dspark-vllm-gx10:0.1.1 ghcr.io/anemll/dspark-vllm-gx10:0.1.1
```

**Trust verification** (compare layer digests with the official manifest to rule out mirror tampering):

```bash
curl -s -H "Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json" \
  https://ghcr.io/v2/anemll/dspark-vllm-gx10/manifests/0.1.1 -o /tmp/ghcr-manifest.json
curl -s -H "Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json" \
  https://ghcr.nju.edu.cn/v2/anemll/dspark-vllm-gx10/manifests/0.1.1 -o /tmp/nju-manifest.json
python3 - <<'PY'
import json
a=json.load(open('/tmp/ghcr-manifest.json')); b=json.load(open('/tmp/nju-manifest.json'))
print("layers identical:", {l['digest'] for l in a['layers']} == {l['digest'] for l in b['layers']})
print("config identical:", a['config']['digest'] == b['config']['digest'])
PY
docker image inspect ghcr.io/anemll/dspark-vllm-gx10:0.1.1 --format '{{range .RepoDigests}}{{.}}{{end}}'
# expect digest: sha256:a83948492cf13df455170fb42885f5ef4db54fefe0feff0f841ecbff464ac9d8
```

## 7.2 Deployment Repo and Config (head)

```bash
git clone https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark.git \
  ~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark
cd ~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark
cp .env.dspark.example .env.dspark   # template lives in this repo's root; replace <placeholders>
```

Config essentials (see [VARIABLES.md](../VARIABLES.md)):

- `WORKER_HOST=<IP_MGMT_B>` (address head uses to SSH the worker)
- `MASTER_ADDR=<IP_FABRIC_A>`, `VLLM_HOST_IP=<IP_FABRIC_A>`, `WORKER_VLLM_HOST_IP=<IP_FABRIC_B>`
- `NCCL_IB_HCA` / `NCCL_SOCKET_IFNAME`: fill per the **head's actual cabled port**;
  `WORKER_NCCL_*` per the worker's actual port (the two may differ; here head=Port0 / worker=Port1)
- GID index: leave empty; the start script auto-resolves from sysfs (`NCCL_IB_GID_AUTO=1`)
- `ABLITERATED=0` (official 0731 checkpoint; `1` = Keys abliterated variant)
- `DSPARK_MODEL_OFFICIAL=/cache/huggingface/models/DeepSeek-V4-Flash-0731` (local path, no HF hub;
  **the new start script resolves `DSPARK_MODEL` from `DSPARK_MODEL_OFFICIAL` — do not set `DSPARK_MODEL` directly**)
- `DSPARK_ENCODING_FILE=.../encoding/encoding_dsv4.py` (installed into vLLM at container start)
- `DSPARK_REVISION`: leave empty (script auto-pins tested `9e165c30…` when unset, Issue #19; local-path models unaffected)
- `ENABLE_VL_SIDECAR=0` (text-only; `1` enables the experimental VL sidecar path and switches to `GPU_MEMORY_UTILIZATION_VISION`)
- `GPU_MEMORY_UTILIZATION_TEXT=0.835` (text-only GPU utilization, replaces legacy `GPU_MEMORY_UTILIZATION`)
- `DEFAULT_THINKING=max` (set to `low`/`off` before benchmarking, see chapter 08)

## 7.3 Preflight

The reproduction package ships `scripts/repro-preflight.sh` (this repo, not the deployment repo).
Copy it to the head and run:

```bash
bash repro-preflight.sh <IP_MGMT_B>   # SSH/GPU/CUDA/image/model/RoCE/port on both nodes
```

> Every check must be `[OK]` and `8888 idle` before deployment; fix any `[FAIL]` first.

## 7.4 Launch (on head; worker starts first)

```bash
cd ~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark
./start-deepseek-v4-flash-dspark.sh
```

The script: resolves GIDs → syncs compose/env to the worker → validates compose on both → starts
**worker first** → starts head → waits for the API → runs a minimal chat request.

**Cold start ≈ 6–9 minutes.** Key log lines:

```text
Resolved architecture: DeepseekV4ForCausalLM
Using nvfp4_ds_mla data type to store kv cache
Loading weights took 222.99 seconds        # 79.17 GiB per rank
GPU KV cache size: 1,833,828 tokens
Maximum concurrency for 1,048,576 tokens per request: 1.75x
Starting vLLM server on http://0.0.0.0:8888
Application startup complete.
DeepSeek V4 Flash DSpark is running: http://127.0.0.1:8888/v1/models
Minimal chat request succeeded.
```

## 7.5 Optional Hardening

```bash
# prevent the memory-compaction thread from soft-locking under load (community pitfall)
echo vm.compaction_proactiveness=0 | sudo tee /etc/sysctl.d/99-dsv4.conf
sudo sysctl -w vm.compaction_proactiveness=0
# disable earlyoom if installed (it may OOM-kill vLLM)
sudo systemctl disable --now earlyoom 2>/dev/null || true
```
