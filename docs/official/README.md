# 官方文档镜像（批量抓取）与准备阶段命令验证报告

> 本目录是 NVIDIA 官方文档的 **HTML → Markdown 批量抓取快照**，用于：
> 1. 复现时离线对照官方命令（不依赖随时可能改版的官网排版）；
> 2. 本仓库"准备阶段"（01 硬件 / 02 系统初始化+OTA / 03 基础配置 /
>    04 NVIDIA Sync+Cluster Assistant / 05 NCCL / DOWNLOADS 下载清单）命令的
>    **逐条对照验证依据**。
>
> 抓取日期：2026-08-12。每个文件头部保留 `<!-- source: URL -->` 溯源。
> 官方页面更新后本快照可能过期；以官网为准，本目录仅作对照参考。

## 文件清单

| 文件 | 来源 | 对应仓库章节 |
|---|---|---|
| `dgx-spark_first-boot.md` | docs.nvidia.com/dgx/dgx-spark/first-boot.html | 02 |
| `dgx-spark_os-and-component-update.md` | docs.nvidia.com/dgx/dgx-spark/os-and-component-update.html | 02 |
| `dgx-spark_release-notes.md` | docs.nvidia.com/dgx/dgx-spark/release-notes.html | 02, 09 |
| `dgx-spark_spark-clustering.md` | docs.nvidia.com/dgx/dgx-spark/spark-clustering.html | 01, 04, 05 |
| `dgx-spark_dgx-dashboard.md` | docs.nvidia.com/dgx/dgx-spark/dgx-dashboard.html | 02, 09 |
| `dgx-spark_nvidia-sync.md` | docs.nvidia.com/dgx/dgx-spark/nvidia-sync.html | 04 |
| `sync_getting-started.md` | docs.nvidia.com/sync/latest/getting-started.html | 04 |
| `sync_cluster-assistant.md` | docs.nvidia.com/sync/latest/cluster-assistant.html | 03, 04 |
| `sync_direct-connections.md` | docs.nvidia.com/sync/latest/direct-connections.html | 04 |
| `nccl-playbook.md` | github.com/NVIDIA/dgx-spark-playbooks（nvidia/nccl/README.md） | 05 |
| `vllm-playbook.md` | github.com/NVIDIA/dgx-spark-playbooks（nvidia/vllm/README.md） | 07 |

抓取工具：`curl`（UA: Mozilla/5.0）+ `python3 markdownify`（提取 `<article class="bd-article">` 主体）。

---

## 准备阶段命令对照验证结论（2026-08-12，双机实测）

验证对象：真实环境 head / worker 两台（<HOSTNAME_A>/<HOSTNAME_B>，脱敏），均已应用 OTA 至 7.5.0 / OTA2607。
总体结论：**准备阶段命令与官方文档一致；真实主机上全部可执行。**

### 1. 02 章：系统 OTA 升级

| 仓库命令 | 官方依据 | 结论 |
|---|---|---|
| DGX Dashboard → 系统更新（推荐） | os-and-component-update: "primary and recommended" | ✅ |
| `sudo apt update && sudo apt dist-upgrade && sudo fwupdmgr refresh && sudo fwupdmgr upgrade && sudo reboot` | os-and-component-update: Manual System Updates 原文 | ✅ 逐字一致 |
| ≥ 2026-04 判断：`LC_ALL=C apt-cache policy dgx-spark-ota-update-meta` Installed ≥ 26.04.1 | Cluster Assistant 即解析该包版本（同步官方实现） | ✅ 双机实测 26.04.1 |
| `nvidia-spark-ota-check`（**OTA 后才存在**，校验用） | 随 OTA 推送的包；官网不以其为升级入口 | ✅ 双机实测 /usr/bin/nvidia-spark-ota-check 1.0.16-1，summary OTA2607 torn 0.0 |
| `/etc/dgx-release`：出厂仅 DGX_SWBUILD_VERSION，OTA 后出现 DGX_OTA_VERSION | 官方 release-notes 软件栈表（出厂 build 与 OTA 版本分开记录） | ✅ 双机实测 SWBUILD 7.2.3 + OTA 7.5.0 |

### 2. 03/04 章：用户、sudo、SSH、NVIDIA Sync

| 仓库命令/状态 | 官方依据 | 结论 |
|---|---|---|
| `sudo tee /etc/sudoers.d/<USER>-nopasswd ... NOPASSWD:ALL` + `chmod 440` | sync_cluster-assistant: 需 SSH + sudo 权限；密码 sudo 会弹交互提示 | ✅ 双机 /etc/sudoers.d/<USER>-nopasswd 存在，`sudo -n true` 通过 |
| 统一用户 / UID / GID | sync_cluster-assistant: "usernames, UIDs, GIDs across devices" | ✅ 双机均为 <USER>/UID 1000 |
| SSH key + 自连 authorized_keys（mpirun 需要） | nccl-playbook: mpirun 经 SSH 跨节点启动 | ✅ 双机 authorized_keys 自含公钥 |
| 管理网口一致（enP7s7 或 wlP9s9） | nccl-playbook: 全节点统一接口（Ethernet enP7s7 / Wi-Fi wlP9s9） | ✅ 双机 enP7s7 up，同一 LAN 内（<IP_MGMT_A>/<IP_MGMT_B>） |
| NVIDIA Sync（Linux apt 源安装） | sync_getting-started: curl gpgkey + `echo "deb ..."` + `apt install nvidia-sync` | ✅ 与官方逐字一致 |
| Cluster Assistant 步骤（Device/User/Network/Link test/Inter-device SSH） | sync_cluster-assistant 全文步骤一致 | ✅ |

### 3. 01 章：硬件接线检查

| 仓库命令 | 官方依据 | 结论 |
|---|---|---|
| `ip -br link show \| grep -E "enp1s0f\|enP2p1s0f"` + `sudo ethtool <iface> \| grep -E "Speed\|Link detected"` | dgx-spark_spark-clustering（ConnectX-7 端口/链路） | ✅ 双机可见 4 个 CX-7 网口（2 UP / 2 DOWN=未插线），与 200G 直连拓扑一致 |
| 官方 QSFP112 DAC 单线 / 双线规则 | spark-clustering: 两根线需四口全配 IP 才能跑满 | ✅ 文档描述一致 |

### 4. 05 章：NCCL 编译与测试（对照官方 nccl-playbook）

| 仓库命令 | 官方 playbook | 结论 |
|---|---|---|
| `sudo apt-get install -y libopenmpi-dev` | 同 | ✅ |
| `git clone -b v2.30.7-1 ... ~/nccl` + `make -j$(nproc) src.build NVCC_GENCODE="...compute_121,code=sm_121"` | 同（官方 `make -j`，`-j$(nproc)` 等价） | ✅ |
| `export CUDA_HOME=/usr/local/cuda` 等 4 个环境变量 | 同 | ✅ |
| `git clone ... ~/nccl-tests` + `make -j$(nproc) MPI=1` | 同（官方 `make MPI=1`） | ✅ |
| mpirun all_gather_perf `-b 16G -e 16G -f 2`（大缓冲区版） | 官方同样提供该大缓冲区命令 | ✅ |
| `ibdev2netdev` 确认 RoCE 口 → 网口映射 | nccl-playbook Step 4 用 `ibdev2netdev` | ✅ |

### 5. 06 章 / DOWNLOADS.md：模型下载工具链（自研，验证可执行）

| 命令 | 双机/head 实测 | 结论 |
|---|---|---|
| `python3 -m venv ~/hf-venv` + pip install huggingface_hub hf_xet httpx | head 已建，Python 3.12.3 | ✅ |
| `~/hf-venv/bin/hf version`（DOWNLOADS.md 第 8 项校验） | 1.26.1 | ✅ |
| `~/dsv4-chunkdl.py` 分块下载器 | 存在且日志有成功记录 | ✅ |
| 官方 sha256 清单 `~/dsv4-files.json` | 存在（74 文件） | ✅ |
| 模型落地 `~/.cache/huggingface/models/DeepSeek-V4-Flash-0731` | 156 GB 已就位 | ✅ |

---

## 曾发现并已修正的问题（历史）

- **02 章旧版把 `nvidia-spark-ota-check` 当作升级工具、且写在"先检查后升级"的错误顺序，并虚构了
  `/usr/sbin/nvidia-spark-run-apt-upgrade-once.sh` 命令路径。** 已修正为官方顺序：
  先 OTA（Dashboard 或官方五连）→ 版本门槛 → 再校验。本次对照官方
  `os-and-component-update` 与真实主机 dpkg 日志（`<none> → 1.0.16-1` 与
  `26.03.1 → 26.04.1` 同一次 dist-upgrade 装入）复核通过。
