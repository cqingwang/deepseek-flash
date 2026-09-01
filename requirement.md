# DeepSeek-V4-Flash 纯净 Ubuntu 24.04 Server 复刻硬性要求

本文是本项目在两台全新 Ubuntu 24.04 Server / NVIDIA DGX Spark 上复刻
DeepSeek-V4-Flash 双机推理服务的准入条件与验收契约。它补充并收敛
`README.md`、`deploy.md`、`docs/01`–`docs/09`、`VARIABLES.md` 和当前
`config.yaml` 的要求。

目标是用 SSH、rsync/scp、systemd、Docker Compose 和 shell 检查脚本完成部署。
NVIDIA Sync/Cluster Assistant 不是前置条件，也不得作为配置来源；所有网络地址、
接口、GID 和版本必须由宿主机检查结果或项目配置明确给出。

## 1. 未满足即停止的总闸门

以下任一项不满足，只允许继续做诊断，不得启动双机 vLLM：

1. 两台机器都是 NVIDIA DGX Spark GB10、128 GB 统一内存、Blackwell `sm_121`，并且安装的是 Ubuntu 24.04 Server。两台机的硬件、系统架构、内核、驱动和 OTA 代际必须一致。
2. DGX Spark OTA/系统软件达到项目文档要求的 **2026-04 或更新版本**；`dgx-spark-ota-update-meta` 的已安装版本必须不低于 `26.04.1`。升级必须使用官方 `apt dist-upgrade + fwupdmgr` 路径，完成后重启并重新检查驱动。
3. 每台机器均能正常执行 `nvidia-smi`，识别 `NVIDIA GB10`；CUDA Toolkit 为项目现行基线 `13.0`，且 `nvcc` 可用。驱动版本以当前运行 Spark 采集值为准，不得自行升级到未经验证的版本。
4. 两台机器使用同一部署用户（当前配置为 `chan`，新环境可替换但必须同步修改 `config.yaml`），UID/GID、家目录、sudo 权限和 Docker 权限一致。
5. head 能免密 SSH 到 worker；worker 能免密 SSH 到自身；host key、hostname 和 `/etc/hosts` 稳定。部署脚本不得依赖交互式密码、NVIDIA Sync 或手工点击。
6. QSFP112 DAC 直连链路两端均为 Link UP；实际接口、HCA、fabric IP 必须从 `ibdev2netdev`、`ip`、`rdma` 和 `ethtool` 结果填写，不能照抄其他机器的接口名。
7. 管理网 SSH、fabric 网 TCP、RoCE GID、MPI `hostname` 和 `nccl-tests all_gather_perf` 全部通过；通信检查失败时禁止用管理网替代 NCCL fabric 参数掩盖问题。
8. 模型在 head 和 worker 各有一份，文件数量、大小、SHA-256 完整性均通过；TP=2 不能只在 head 放模型。
9. 两台均存在同一镜像 tag 和 digest、同一 `dspark/` runtime、同一配置生成物；`docker compose config --quiet` 通过，容器最终 `/proc/1/cmdline` 与 `.env.dspark` 一致。
10. `./deploy.sh --doctor` 的 FAIL 数为 0，随后 `./deploy.sh --install`、API 健康检查、鉴权检查和最小对话全部通过。静态检查通过不等于部署完成。

## 2. 必须冻结的版本与运行指纹

版本以“当前运行 Spark 实际值”为准，采集完成后把值填入本文件的部署记录或单独的受控变更中。不得只凭 README 的历史值判定对齐。

| 项目 | 当前仓库基线 | 硬性要求 |
|---|---|---|
| OS | Ubuntu 24.04 Server | 两台一致；记录 `/etc/os-release`、`uname -a` |
| GPU | NVIDIA GB10 / `sm_121` | 两台 `nvidia-smi` 一致 |
| CUDA | 13.0（文档基线） | 记录 `nvcc --version` 和驱动版本 |
| vLLM 镜像 | `ghcr.io/anemll/dspark-vllm-gx10:0.1.1` | 两台镜像 digest 必须相同；文档期望 digest 为 `sha256:a83948492cf13df455170fb42885f5ef4db54fefe0feff0f841ecbff464ac9d8`，以现网采集值复核 |
| vLLM | 镜像记录为 `0.25.2.dev0+g752a3a504.d20260714` | 以容器内 `vllm --version`/Python 包元数据复核 |
| DSpark runtime | 当前工作区子模块 `a6073994983851099c60042b5f69ec5df60d9205` | 目标节点必须使用冻结 commit；文档旧 pin `a4ce87a...` 不得自动覆盖当前工作区 |
| 模型 | 当前配置为 drowzeys abliterated 变体 | 若复刻官方检查点，改为 `deepseek-ai/DeepSeek-V4-Flash-0731` 并重新生成 env；模型名、revision、编码文件必须成套 |
| 推理 profile | `MAX_MODEL_LEN=1048576`、`MAX_NUM_SEQS=6`、`MAX_NUM_BATCHED_TOKENS=8192`、`MTP_NUM_TOKENS=5` | 当前 `config.yaml` 的 c=4 覆盖值与模板 c=6 值存在差异，安装前必须以目标运行 Spark 的最终 `.env.dspark` 和 `/proc/1/cmdline` 定版 |
| API | `0.0.0.0:8888` | `common.api_url`、服务名、端口与配置一致 |

在可连通 Spark 后，head 上执行以下只读采集并保存脱敏结果；API key、HF token 和 SSH 私钥不得进入日志：

```bash
source ~/.zshrc 2>/dev/null
ssh -o BatchMode=yes <USER>@<SPARK_HOST> '
  hostname; cat /etc/os-release; uname -a; cat /etc/dgx-release 2>/dev/null || true
  dpkg-query -W -f="${Package}\t${Version}\n" docker.io docker-ce containerd nvidia-container-toolkit libnccl2 libnccl-dev libopenmpi-dev openmpi-bin rdma-core ibverbs-providers 2>/dev/null || true
  nvidia-smi; /usr/local/cuda-13.0/bin/nvcc --version 2>/dev/null || nvcc --version
  docker --version; docker compose version; docker image inspect ghcr.io/anemll/dspark-vllm-gx10:0.1.1 --format "{{json .RepoDigests}}"
  docker ps --no-trunc; docker exec <CONTAINER> sh -lc "python3 -m pip show vllm; tr "\\0" " " </proc/1/cmdline"
  git -C /opt/deepseek-flash/dspark rev-parse HEAD 2>/dev/null || true
'
```

## 3. 纯净机只装必要的宿主依赖

基础系统只保留项目需要的 SSH、同步、网络/RDMA、MPI、编译和 Docker 组件；不要在宿主机安装另一个 Python/vLLM/CUDA 运行时来替代容器镜像。

```bash
sudo apt update
sudo apt install -y \
  openssh-client openssh-server rsync git curl ca-certificates jq \
  ethtool iproute2 pciutils lshw \
  rdma-core ibverbs-providers ibverbs-utils perftest \
  libopenmpi-dev openmpi-bin build-essential
```

硬性限制：

- Docker 使用 DGX Spark 系统已验证的 Docker/containerd 组件；如果纯净镜像没有它，必须安装与当前 Spark 相同来源/版本的 Docker Engine、Compose v2 和 NVIDIA Container Toolkit，再重启 Docker。
- 不在宿主机 `pip install vllm`、不编译另一套 CUDA、不混装不同 NCCL 作为容器运行时。`/opt/nccl` 和 `/opt/nccl-tests` 仅用于宿主机通信验收。
- 两台统一安装并加入 Docker 组；重新建立 SSH 会话后验证普通用户可执行 `docker ps`。
- 可设置 `vm.compaction_proactiveness=0`；若有 `earlyoom`，必须确认其不会杀死 vLLM。不得卸载 Docker、containerd、NVIDIA persistence、RDMA、NetworkManager 或 SSH。

## 4. SSH、管理网和 fabric 配置

head/worker 的角色、管理地址、fabric 地址、接口和 HCA 必须填写到 `config.yaml`，示例值不能直接当成新机器值。两台 `/etc/hosts` 至少包含：

```text
<IP_MGMT_A>  spark-a
<IP_MGMT_B>  spark-b
```

head 上必须能完成：

```bash
ssh <USER>@<IP_MGMT_B> hostname
ssh <USER>@<IP_MGMT_B> 'docker ps >/dev/null && sudo -n true'
ssh <USER>@<IP_MGMT_B> 'ip -br addr; rdma link show; ibdev2netdev'
```

管理网仅用于 SSH、MPI 启动和 API；NCCL/TP/Gloo 使用实际 QSFP/RoCE fabric 接口。启动参数必须分别支持 head 与 worker 的 `WORKER_NCCL_IB_HCA`、`WORKER_NCCL_SOCKET_IFNAME`、`WORKER_TP_SOCKET_IFNAME` 和 `WORKER_GLOO_SOCKET_IFNAME`。

## 5. 无 NVIDIA Sync 的通信检查

### 5.1 物理链路与 RoCE

两台分别执行，记录实际输出：

```bash
ip -br link
ip -br addr
sudo ethtool <FABRIC_IF> | grep -E 'Speed|Link detected'
ibdev2netdev
rdma link show
```

预期插线口为 `Speed: 200000Mb/s`、`Link detected: yes`，RDMA link 为 ACTIVE/LINK_UP。使用一根官方 QSFP112 DAC 直连；不以两条普通线缆或交换机替代该拓扑。

### 5.2 GID

```bash
HCA=<实际HCA>
for i in 0 1 2 3 4 5; do
  printf 'idx%s: ' "$i"
  cat "/sys/class/infiniband/$HCA/ports/1/gids/$i" 2>/dev/null || true
  cat "/sys/class/infiniband/$HCA/ports/1/gid_attrs/types/$i" 2>/dev/null || true
done
```

启动脚本默认 `NCCL_IB_GID_AUTO=1`，按每台机器的 RoCE IPv4 自动解析；只有在采集并验证两台索引后才允许关闭自动解析并固定 `NCCL_IB_GID_INDEX`。禁止把一台机器的固定 idx3 盲拷到另一台。

### 5.3 MPI 与 NCCL all-gather

先做最小 SSH/MPI 检查，再做大包通信。`NCCL_HOME` 和 `LD_LIBRARY_PATH` 必须指向同一份已编译 NCCL：

```bash
export CUDA_HOME=/usr/local/cuda
export MPI_HOME=/usr/lib/aarch64-linux-gnu/openmpi
export NCCL_HOME=/opt/nccl/build
export LD_LIBRARY_PATH="$NCCL_HOME/lib:$CUDA_HOME/lib64:$MPI_HOME/lib:${LD_LIBRARY_PATH:-}"

mpirun -np 2 -H <IP_MGMT_A>:1,<IP_MGMT_B>:1 \
  --mca plm_rsh_agent 'ssh -o BatchMode=yes' hostname

mpirun -np 2 -H <IP_MGMT_A>:1,<IP_MGMT_B>:1 \
  --mca plm_rsh_agent 'ssh -o BatchMode=yes' \
  -x LD_LIBRARY_PATH -x UCX_NET_DEVICES=<MGMT_OR_VERIFIED_IF> \
  -x NCCL_SOCKET_IFNAME=<MGMT_OR_VERIFIED_IF> \
  -x OMPI_MCA_btl_tcp_if_include=<MGMT_OR_VERIFIED_IF> \
  /opt/nccl-tests/build/all_gather_perf -b 16G -e 16G -f 2
```

验收：两个 rank 都识别 GB10，`#wrong = 0`，bus bandwidth 约 21 GB/s（约 171 Gbit/s，允许受实际链路和系统负载影响）。MPI 卡住、`ibv_modify_qp`、`unhandled system error` 或 GID 报错都属于阻断项。

## 6. 配置、runtime、镜像和模型的复制契约

### 6.1 复制顺序

只从 head 的 Git 工作区复制，避免两台分别 checkout 漂移版本：

```bash
sudo mkdir -p /opt/deepseek-flash/dspark /opt/models
sudo rsync -a --delete dspark/ /opt/deepseek-flash/dspark/
ssh <USER>@<IP_MGMT_B> 'sudo mkdir -p /opt/deepseek-flash/dspark /opt/models'
rsync -a --delete dspark/ <USER>@<IP_MGMT_B>:/tmp/deepseek-flash-dspark/
ssh <USER>@<IP_MGMT_B> 'sudo rsync -a --delete /tmp/deepseek-flash-dspark/ /opt/deepseek-flash/dspark/ && rm -rf /tmp/deepseek-flash-dspark'
```

随后在 head 运行 `./deploy.sh --doctor`，只用 `./deploy.sh --install [MODEL_PATH]` 生成并复制 `/etc/dspark-vllm/config.yaml`、`program.py`、`dspark.env.json`、systemd 单元和两台 runtime 的 `.env.dspark`。不要手工编辑生成的 `.env.dspark`。

### 6.2 镜像

两台必须存在完全相同的镜像 tag 和 digest。网络受限时可先在可联网机器 `docker save`，再在目标机 `docker load`；使用国内镜像时必须按 `docs/07-deploy.md` 比较官方与镜像源 manifest 的 config/layer digest，不能只相信 tag。

### 6.3 模型

模型目录必须位于 `common.model_lib` 下，并在两台各有一份；容器内路径必须能访问 `/cache/huggingface/.../config.json`。模型下载不是纯净安装的必要步骤，可以使用已校验离线模型，但必须执行同等的 74 文件/48 个 safetensors 分片检查和 `--verify-only`。禁止把模型目录当 runtime repo，禁止使用指向宿主绝对路径的容器内 symlink。

### 6.4 env 关键一致性

由 `config.yaml + dspark.env.json + program.py gen-env` 派生并核验：

- `MASTER_ADDR`/`VLLM_HOST_IP` 为 head fabric IP，worker 使用 `WORKER_VLLM_HOST_IP`；`MASTER_PORT`（当前配置 `25000`）两台可达且未被占用。
- `NCCL_NET=IB`、`NCCL_IB_DISABLE=0`、`NCCL_IB_ADDR_FAMILY=AF_INET`、`NCCL_IB_ROCE_VERSION_NUM=2`、`NCCL_CROSS_NIC=1`。
- GB10/SM121 关闭 symmetric-memory 路径：`NCCL_NVLS_ENABLE=0`、`VLLM_USE_NCCL_SYMM_MEM=0`，保留项目验证过的 PYNCCL fallback。
- text-only 默认 `ENABLE_VL_SIDECAR=0`；`GPU_MEMORY_UTILIZATION_TEXT=0.835`；模型变体、编码文件和 served model name 必须匹配。
- `VLLM_API_KEY` 由 `common.api_key` 生成；非空时必须在容器最终 argv 出现 `vllm serve --api-key`，为空时必须验证鉴权关闭。日志只允许打印 enabled/disabled，不得打印密钥。
- `DEFAULT_THINKING=max` 只作为现有配置基线；性能验收前改为 `low` 或 `off`，否则不能将长推理链耗时当作吞吐结论。

## 7. 部署、服务和最终验收

```bash
cd /opt/deepseek-flash
./deploy.sh --doctor
./deploy.sh --install <MODEL_PATH>
./deploy.sh --live_check --wait 1200
./deploy.sh status
sudo systemctl is-enabled dspark-vllm-head.service
ssh <USER>@<IP_MGMT_B> 'sudo systemctl is-enabled dspark-vllm-worker.service'
```

必须同时满足：

1. worker 先起、head 后起；两台容器均为 running，不能用 `docker ps -a` 的“存在”结果代替运行证据。
2. `curl http://<IP_MGMT_A>:8888/health` 返回 200；`/v1/models` 返回正确模型和 `max_model_len=1048576`（若最终冻结为其他 profile，必须以冻结值为准）。
3. 鉴权开启时，无 Bearer 请求得到 401，正确 Bearer 请求能访问 `/v1/models` 和 chat；`/metrics` 按当前项目契约单独检查。
4. 最小对话返回确定答案（项目示例 `17*23 -> 391`），并保存脱敏请求/响应和启动日志。
5. 记录容器内：`docker inspect`、环境变量白名单、最终 `/proc/1/cmdline`、head/worker 日志、runtime commit、镜像 digest、模型校验结果。
6. 运行 `python3 -m py_compile program.py tests/test_program.py`、`bash -n deploy.sh dspark/start-deepseek-v4-flash-dspark.sh dspark/stop-deepseek-v4-flash-dspark.sh`、`python3 -m unittest discover -s tests` 和 `git diff --check`。
7. 若需要性能验收，先完成短上下文基线，再做 620K/780K 长上下文锚点；记录 TTFT、prefill、decode、并发、温度和是否冷启动。性能参考值约 60–80 tok/s 仅是已有运行节点的经验，不是新机器在未完成环境对齐时的保证。

## 8. 当前运行双 Spark 的实测快照（2026-08-19）

以下内容通过只读 SSH 实测采集：

```text
head   chan@192.168.2.180  hostname=spark-a
worker chan@192.168.2.161  hostname=spark-b
```

### 8.1 宿主机硬件、系统和存储

| 项目 | spark-a | spark-b | 复刻要求 |
|---|---|---|---|
| 系统 | Ubuntu 24.04.4 LTS | Ubuntu 24.04.4 LTS | 新机必须为 Ubuntu 24.04 Server；两台版本一致 |
| 架构/硬件 | arm64 / NVIDIA DGX Spark | arm64 / NVIDIA DGX Spark | 必须一致 |
| DGX 软件 | `DGX_SWBUILD_VERSION=7.5.0`、`DGX_OTA_VERSION=7.5.0`、commit `03dc741` | 相同 | 新机 OTA 至少达到该级别，不能低于文档要求的 `26.04.1` |
| 固件 | `5.36_0ACUM027`，2026-06-12 | 相同 | 新机记录并对齐；不得只升级 apt 不核对固件 |
| 内核 | `6.17.0-1029-nvidia` | 相同 | 以 DGX OTA 配套内核为准 |
| CPU | 20 logical CPUs | 20 logical CPUs | 必须为 DGX Spark 同等级硬件 |
| 内存 | Linux `121 GiB`，物理标称 128 GB | Linux `121 GiB`，物理标称 128 GB | 记录 `free -h`，不要将统一内存误写成独立显存 |
| 根盘 | 3.7T，总可用约 3.2T | 3.7T，总可用约 3.3T | 模型、Docker 层、cache 和日志必须有余量；不要求固定盘型号，但不得低于实际所需空间 |
| Swap | 15 GiB，运行时约使用 2 GiB | 15 GiB，运行时约使用 2 GiB | 记录并观察；不得用 swap 掩盖内存不足 |

### 8.2 GPU、CUDA、Docker 和宿主依赖实测值

两台实测一致：

```text
GPU: NVIDIA GB10
Driver: 580.173.02
CUDA reported by nvidia-smi: 13.0
nvcc: release 13.0, V13.0.88
CUDA package runtime in container: CUDA_VERSION=13.0.2
Docker Engine: 29.2.1
Docker Compose: v5.0.2
containerd.io: 2.2.1-1~ubuntu.24.04~noble
nvidia-container-toolkit: 1.19.1-1
libnvidia-container-tools/libnvidia-container1: 1.19.1-1
Open MPI: 4.1.6
rdma-core/ibverbs: 50.0-2ubuntu0.2
perftest: 24.01.0+0.38-1build2
Python: 3.12.3
Cgroup: v2
Docker default runtime: runc
```

新机硬性要求：Docker、Compose、NVIDIA Container Toolkit、Open MPI、RDMA/ibverbs
和 perftest 至少先对齐上述版本；如果发行源提供的版本不同，必须记录差异并先做
容器启动与通信回归，不能把宿主机 Python 包或宿主机 vLLM 当作替代方案。

### 8.3 网络、接口和 GID 实测值

两台管理网均为 Wi-Fi `wlP9s9`，head 为 `192.168.2.180/24`，worker 为
`192.168.2.161/24`。两条 fabric 链路均实际启用，且两端 `ethtool` 报告：

```text
enp1s0f0np0   10.100.240.1/24 (head)   / 10.100.240.2/24 (worker)   200000Mb/s, Link yes
enP2p1s0f0np0 10.100.241.1/24 (head)   / 10.100.241.2/24 (worker)   200000Mb/s, Link yes
```

对应 RoCE 设备为：

```text
head:   rocep1s0f0 -> enp1s0f0np0       roceP2p1s0f0 -> enP2p1s0f0np0
worker: rocep1s0f0 -> enp1s0f0np0       roceP2p1s0f0 -> enP2p1s0f0np0
```

两台的 `rocep1s0f0` 和 `roceP2p1s0f0` 均为 `state ACTIVE / LINK_UP`；另一组
`f1` 接口均为 DOWN。IPv4 RoCE v2 GID 均为 idx3：

```text
head rocep1s0f0:   ::ffff:10.100.240.1  RoCE v2 idx3
head roceP2p1s0f0: ::ffff:10.100.241.1  RoCE v2 idx3
worker rocep1s0f0:   ::ffff:10.100.240.2  RoCE v2 idx3
worker roceP2p1s0f0: ::ffff:10.100.241.2  RoCE v2 idx3
```

两条 fabric IP 互相 ping 均为 0% 丢包；这只是 L3 连通证据，不替代
`mpirun` 和 `all_gather_perf`。新机必须先动态发现接口/HCA/GID，再写入配置；当前
实测配置使用第一条链路作为 NCCL 主链路：`rocep1s0f0` + `enp1s0f0np0` + GID idx3。

### 8.4 当前容器和最终启动参数

两台均有运行容器：

```text
container: deepseek-v4-flash-vllm-dspark-1
image tag: ghcr.io/anemll/dspark-vllm-gx10:0.1.1
image ID: sha256:3430d6614a8e2925f34d059af6caf05aff42387326db4d05639a60f10f2654d8
container vLLM: 0.25.2.dev0+g752a3a504.d20260714
container OCI revision label: 47503f8e38dadd4dededca798150db2619594fce
Compose: v5.0.2, project=deepseek-v4-flash, service=vllm-dspark
```

注意：本地 `docker image inspect` 的 `RepoDigests` 为空，因此当前环境没有提供可直接
核验的 registry digest。复刻时必须通过在线 registry manifest 或离线 tar 的 SHA-256
建立内容指纹；不能把 tag `0.1.1` 单独当作完整版本证明。

容器最终 `/proc/1/cmdline` 实测的关键参数如下，worker 仅 `node-rank` 为 1、并带
`--headless`，其余分布式参数对齐：

```text
model=/models/drowzeys/keys-DeepSeekV4Flash-Vision-EXP-ablit
served_model=keys-DeepSeekV4Flash-Vision-EXP-ablit
api=0.0.0.0:8888, api-key enabled
tensor-parallel=2, pipeline-parallel=1, nnodes=2
kv-cache-dtype=nvfp4_ds_mla, block-size=256
max-model-len=1048576
max-num-seqs=4
max-num-batched-tokens=16384
max-cudagraph-capture-size=28
gpu-memory-utilization=0.835
speculative method=dspark, num_speculative_tokens=6
distributed-executor-backend=mp
moe-backend=flashinfer_b12x
master-addr=10.100.240.1, master-port=25000
default thinking=true, reasoning_effort=max
```

这是当前运行事实，优先级高于模板中的旧值：新机复刻默认应使用
`MAX_NUM_SEQS=4`、`MAX_NUM_BATCHED_TOKENS=16384`、`MTP_NUM_TOKENS=6`、cudagraph
有效大小 28。若要恢复官方模板的 c=6/8192/5 profile，必须作为显式变更重新完成
冷启动、长上下文和通信验收，不能在纯净安装时隐式切换。

### 8.5 当前配置和 runtime 源码漂移

两台当前 `/opt/deepseek-flash` 顶层 commit 都是：

```text
07b225517e68ebe24f5b910829482feb746b3893
```

两台 `/opt/deepseek-flash/dspark` 子目录 commit 都是：

```text
ab8884d7b66ed7a23bd3345adc1b5a9e6e4d822e
```

但两个工作区均存在未提交修改/未跟踪文件，且与当前本地 checkout 的
`dspark` commit 不同。因此复刻前必须先从当前运行 Spark 导出实际 runtime 文件快照
或 commit，并由 head 用 `rsync --delete` 复制到新 worker；禁止直接以本地 `a607399...`
或文档历史 `a4ce87a...` 替换线上运行版本。

当前实际绑定关系还包括：

- `/opt/models` → 容器 `/models`（只读）和 `/cache/huggingface`（读写）；
- `/opt/deepseek-flash/dspark/patches` → `/opt/dspark-patches`；
- 多个 DSV4 hotfix 以只读 bind mount 注入容器；
- `vllm_patch_gb10` 以可写 bind mount 注入 `/opt/vllm-gb10-hybrid-nvfp4`；
- `.env.dspark`、Compose、patches 和启动脚本必须作为一个版本集合复制。

## 9. 当前运行异常与复刻时的强制修复项

### 9.1 head systemd 状态不能只看 enabled/active

实测：

```text
head:   dspark-vllm-head.service enabled，但 failed
worker: dspark-vllm-worker.service enabled，active
容器：  head/worker 的 vLLM 容器均 Up 约 7 小时
```

head 的 journal 显示：Docker 已恢复已有容器，上游启动脚本返回 exit 3（“container
already exists / cluster may already be serving”），`program.py` 将其转成 exit 1，导致
systemd 重试 5 次后失败。当前 API 仍能工作，但这不是合格的自恢复状态。

新机验收必须保证以下行为之一成立：

1. systemd 对“已有且健康容器”的 exit 3 按成功处理，并通过 API health 判断服务已就绪；或
2. service 启动前显式区分 running container、stopped container 和 stale container，只有 stale 情况才执行清理。

不能仅以 `systemctl is-enabled` 或 `docker ps -a` 判定部署成功；必须同时检查
`systemctl is-active`、`docker ps`、API `/health` 和 `/v1/models`。

### 9.2 `docker compose ps` 的工作目录契约

在当前采集时，直接进入 `/opt/deepseek-flash/dspark` 执行 Compose 查询未列出容器，
而 `docker ps` 可看到容器。新机必须使用镜像标签、project name、env-file 和 compose
文件的完整组合查询，不能只依赖当前 shell 的默认 Compose 项目：

```bash
docker compose -p deepseek-v4-flash \
  --env-file /opt/deepseek-flash/dspark/.env.dspark \
  -f /opt/deepseek-flash/dspark/docker-compose.dspark.yml ps
```

若该命令仍为空，必须先检查容器 labels 中的
`com.docker.compose.project.config_files`、`project.environment_file` 和
`project.working_dir`，再判断是否存在 runtime/source drift。

## 10. 更新后的复刻验收顺序

纯净 Ubuntu 24.04 Server 上严格按以下顺序执行：

1. 完成官方 DGX OTA/固件更新，重启，核对 OS、kernel、driver、CUDA、firmware、内存和磁盘。
2. 只安装与本节 8.2 对齐的 Docker/Compose/NVIDIA Toolkit、SSH、rsync、Git、RDMA/ibverbs、Open MPI 和 perftest。
3. 配置统一用户、sudo、双向 SSH、`/etc/hosts` 和管理网；用 BatchMode SSH 验收。
4. 接通 QSFP112 DAC，动态确认两条 200G 链路、HCA、fabric IP、RDMA ACTIVE 和 IPv4 RoCE v2 idx3。
5. 编译/准备与现网一致的 NCCL 和 nccl-tests，完成 MPI hostname、双链路 ping 和 all-gather。
6. 从已冻结的运行 Spark 复制 runtime、Compose、启动脚本、patches、配置模板和模型；禁止手工拼接 env。
7. 校验镜像内容指纹和模型完整性；两台镜像、runtime、模型、配置哈希一致。
8. 运行 `./deploy.sh --doctor`；校验最终 env、Compose config、容器 mounts、`/proc/1/cmdline`。
9. 先启动 worker、再启动 head；确认 systemd active、容器 running、API 200、鉴权 401/200 双路径。
10. 最后执行最小对话、短上下文吞吐和长上下文回归；任何一层只通过静态检查不得宣称完成。

## 11. 当前复刻状态

- 已完成：通过指定 SSH 地址采集两台真实软硬件、Docker、CUDA、RDMA、网络、GID、容器、vLLM、最终启动参数和 API 鉴权状态。
- 已确认：无需 NVIDIA Sync 即可完成本项目的 SSH/rsync/网络配置/Compose/systemd 复刻。
- 已发现：head systemd 失败状态、runtime 工作区 dirty、当前实际 runtime commit 与本地 checkout 不同、镜像没有 RepoDigest、Compose 查询需要完整 project/env/file 参数。
- 未完成：尚未在全新 Ubuntu 24.04 Server 上执行重装和完整双机复刻；尚未重新运行宿主机 `nccl-tests all_gather_perf`，因此通信当前只有接口、GID、L3 ping 证据，不应写成 NCCL all-gather 已验收。

## 12. 不在纯净安装中引入的内容

不安装 NVIDIA Sync、Cluster Assistant、桌面环境、宿主机 vLLM/PyTorch、额外 Python 推理栈、VL sidecar、模型下载器运行时（除非选择在线下载）、未验证的 CUDA/NCCL 版本和与当前 runtime 不同的第三方镜像。所有可选组件必须在基础 text-only 双机服务通过后单独评估。
