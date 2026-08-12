# 07 部署启动（Anemll vLLM + MiaAI recipe）

> 本文档按 [DOWNLOADS.md](DOWNLOADS.md) 使用 MiaAI 部署仓库
> **a4ce87a2f47f1be8fe64c297a0cf33a9a5e509aa**。
> 从旧版（≤ `a4ce87a`）升级的变量迁移见 [09 章 §9.5](09-ops.md#95-升级与回滚)。

## 7.1 拉取运行时镜像（双机）

```bash
# 海外/直连可用：docker pull ghcr.io/anemll/dspark-vllm-gx10:0.1.1
# 中国大陆：ghcr.io blob 直连被限速到 ~17 KB/s，改用国内镜像后打回官方 tag
docker pull ghcr.nju.edu.cn/anemll/dspark-vllm-gx10:0.1.1
docker tag ghcr.nju.edu.cn/anemll/dspark-vllm-gx10:0.1.1 ghcr.io/anemll/dspark-vllm-gx10:0.1.1
```

**镜像可信校验**（与官方 manifest 逐层对比，防镜像源篡改）：

```bash
# 取官方 manifest
curl -s -H "Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json" \
  https://ghcr.io/v2/anemll/dspark-vllm-gx10/manifests/0.1.1 -o /tmp/ghcr-manifest.json
# 取镜像源 manifest（nju 镜像）
curl -s -H "Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json" \
  https://ghcr.nju.edu.cn/v2/anemll/dspark-vllm-gx10/manifests/0.1.1 -o /tmp/nju-manifest.json
# 比对：层 digest 集合一致 + config digest 一致
python3 - <<'PY'
import json
a=json.load(open('/tmp/ghcr-manifest.json')); b=json.load(open('/tmp/nju-manifest.json'))
print("layers identical:", {l['digest'] for l in a['layers']} == {l['digest'] for l in b['layers']})
print("config identical:", a['config']['digest'] == b['config']['digest'])
PY
docker image inspect ghcr.io/anemll/dspark-vllm-gx10:0.1.1 --format '{{range .RepoDigests}}{{.}}{{end}}'
# 期望 digest: sha256:a83948492cf13df455170fb42885f5ef4db54fefe0feff0f841ecbff464ac9d8
```

## 7.2 部署仓库与配置（head）

```bash
# 本仓库已将 MiaAI runtime 作为 dspark/ 子模块下载；先核对并固定版本
git -C dspark checkout a4ce87a2f47f1be8fe64c297a0cf33a9a5e509aa
sudo mkdir -p /opt/deepseek-flash/dspark
sudo rsync -a --delete dspark/ /opt/deepseek-flash/dspark/
# worker 也必须准备同样的 DSpark 子项目，路径与 config.yaml 的 common.runtime_repo 一致
ssh <USER>@<IP_MGMT_B> 'sudo mkdir -p /opt/deepseek-flash/dspark'
rsync -a --delete dspark/ <USER>@<IP_MGMT_B>:/tmp/deepseek-flash-dspark/
ssh <USER>@<IP_MGMT_B> 'sudo rsync -a --delete /tmp/deepseek-flash-dspark/ /opt/deepseek-flash/dspark/ && rm -rf /tmp/deepseek-flash-dspark'
```

> `.env.dspark` 由本仓库的 `program.py install` 根据 `config.yaml` 和 `dspark.env.json` 自动生成，
> 不再手工复制 `.env.dspark.example`；模型下载和双机就位由部署前准备阶段完成。

配置要点（详见 [VARIABLES.md](../VARIABLES.md)）：

> 本仓库通过 `dspark/` 子模块提供 MiaAI 的 compose 和启动脚本。`common.runtime_repo` 所指的
> DSpark 子项目必须
> 先同步到 head/worker；启动脚本位于该仓库目录，不在 `/opt/models/...` 模型目录内。

- `WORKER_HOST=<IP_MGMT_B>`（head 用来 SSH worker 的地址）
- `MASTER_ADDR=<IP_FABRIC_A>`、`VLLM_HOST_IP=<IP_FABRIC_A>`、`WORKER_VLLM_HOST_IP=<IP_FABRIC_B>`
- `NCCL_IB_HCA` / `NCCL_SOCKET_IFNAME`：**head 按其实际插线口填写**；
  `WORKER_NCCL_*` 按 worker 实际口位填写（两台可以不同，本方案 head=Port0 / worker=Port1）
- GID 索引留空：启动脚本默认 `NCCL_IB_GID_AUTO=1` 自动从 sysfs 解析
- `ABLITERATED=0`（官方 0731 检查点；`1` 为 Keys abliterated 变体）
- `DSPARK_MODEL_OFFICIAL=/cache/huggingface/models/DeepSeek-V4-Flash-0731`（本地路径，不经 HF hub；
  **新版 start 脚本强制从 `DSPARK_MODEL_OFFICIAL` 解析 `DSPARK_MODEL`，不要再直接设 `DSPARK_MODEL`**）
- `DSPARK_ENCODING_FILE=.../encoding/encoding_dsv4.py`（compose 启动时自动装入 vLLM）
- `DSPARK_REVISION`：留空即可（未定义时脚本自动 pin 实测过的 `9e165c30…`，Issue #19；本地路径模型不受影响）
- `ENABLE_VL_SIDECAR=0`（text-only；`1` 开启 VL sidecar 视觉实验路径并改用 `GPU_MEMORY_UTILIZATION_VISION`）
- `GPU_MEMORY_UTILIZATION_TEXT=0.835`（text-only 显存利用率，替代旧版 `GPU_MEMORY_UTILIZATION`）
- `DEFAULT_THINKING=max`（压测时建议改 `low`/`off`，见 08 章）

## 7.3 启动前自检

复现包自带 `program.py doctor`（在 head 上经 `./deploy.sh --doctor` 调用）：

```bash
./deploy.sh --doctor                # 默认取 config.yaml 的 worker.ssh；也检查两台 runtime repo
./deploy.sh --doctor <IP_MGMT_B>    # Wi-Fi DHCP 漂移时用参数覆盖 worker 目标
```

> 检查项全部 `[OK]` 且 `8888 空闲` 才满足部署前置条件；若某项 `[FAIL]` 按提示先修复。

## 7.4 启动服务（head 上执行，worker 先起）

```bash
cd ~/deepseek-flash
./deploy.sh --doctor
./deploy.sh --install
```

`install` 自动完成：同步简化部署程序和配置 → 注册双机模型 symlink → 生成并同步 `.env.dspark` →
**先起 worker** → 起 head → 调用上游部署仓库的 start 脚本 → 等待 API。

**冷启动约 6–9 分钟**，关键日志：

```text
Resolved architecture: DeepseekV4ForCausalLM
Using nvfp4_ds_mla data type to store kv cache
Loading weights took 222.99 seconds        # 每 rank 79.17 GiB
Available KV cache memory: 17.02 GiB (head) / 16.64 GiB (worker)   # 双机合计 ≈33.7 GiB（≈230 万 token）
Maximum concurrency for 1,048,576 tokens per request: 1.75x
Starting vLLM server on http://0.0.0.0:8888
Application startup complete.
DeepSeek V4 Flash DSpark is running: http://127.0.0.1:8888/v1/models
Minimal chat request succeeded.
```

> `DSPARK_SKIP_HOTFIX=1` 可跳过 hotfix 自动应用（如已手工打过补丁或使用预补丁镜像）。

## 7.5 可选加固

```bash
# 防内存压缩线程在高负载下 soft-lockup（社区踩坑）
echo vm.compaction_proactiveness=0 | sudo tee /etc/sysctl.d/99-dsv4.conf
sudo sysctl -w vm.compaction_proactiveness=0
# 若系统装了 earlyoom，建议禁用（防止误杀 vLLM 进程）
sudo systemctl disable --now earlyoom 2>/dev/null || true
```
