# 下载清单（要下载什么、从哪下、放哪、怎么校验）

> 按执行顺序排列。**官方路径**均为本项目实际使用的来源；标注"国内镜像"的仅为受限网络加速，
> 海外网络直接用官方源即可。所有校验方式都给出可执行命令。

## 1. NVIDIA Sync（Windows / macOS / Ubuntu）

| 项 | 值 |
|---|---|
| 官方路径 | [build.nvidia.com/spark/connect-to-your-spark](https://build.nvidia.com/spark/connect-to-your-spark) → 下载 `nvidia-sync.dmg` |
| 文档 | [docs.nvidia.com/sync/latest/getting-started.html](https://docs.nvidia.com/sync/latest/getting-started.html) |
| 大小 | 约 100–200 MB |
| 安装 | **Windows**：下载 `.exe` 安装器双击安装；**macOS**：下载 `.dmg` 拖入 Applications；**Ubuntu**：配置官方 apt 源后 `sudo apt install -y nvidia-sync`（命令见 04 章） |
| 校验 | 打开应用正常进入引导即可；macOS 如提示无法打开：`xattr -d com.apple.quarantine /Applications/NVIDIA Sync.app` |

## 2. 系统 OTA 与固件（两台 Spark）

| 项 | 值 |
|---|---|
| 官方路径 | [DGX Spark 用户指南](https://docs.nvidia.com/dgx/dgx-spark/)；[首次启动](https://docs.nvidia.com/dgx/dgx-spark/first-boot.html)；DGX Dashboard |
| 内容 | 系统软件（要求 ≥ 2026-04）、ConnectX-7 / USBPD 固件 |
| 大小 | 数 GB（apt 增量） |
| 校验 | **先按官方流程升级**（Dashboard 或 `apt dist-upgrade` + `fwupdmgr`，见 02 章步骤 1）后：`cat /etc/dgx-release` 看 `DGX_OTA_VERSION`；`LC_ALL=C apt-cache policy dgx-spark-ota-update-meta` → `Installed` ≥ 26.04.1（≥ 2026-04）；`fwupdmgr get-devices \| grep -A2 MT2910` 看 ConnectX-7 固件；仅当工具包已随 OTA 安装后：`sudo nvidia-spark-ota-check summary` → `torn-score: 0` |

## 3. NCCL 编译依赖（两台 Spark）

| 项 | 值 |
|---|---|
| 来源 | apt（Ubuntu 官方源） |
| 包 | `libopenmpi-dev`（约 22 MB） |
| 校验 | `dpkg -l libopenmpi-dev` |

## 4. NCCL 源码（两台 Spark）

| 项 | 值 |
|---|---|
| 官方路径 | <https://github.com/NVIDIA/nccl>，**tag `v2.30.7-1`** |
| 大小 | 约 50 MB |
| 放哪 | `/opt/nccl/` |
| 校验 | `git -C /opt/nccl describe --tags` → `v2.30.7-1` |

## 5. nccl-tests 源码（两台 Spark）

| 项 | 值 |
|---|---|
| 官方路径 | <https://github.com/NVIDIA/nccl-tests>，建议 pin `717b68318278e93f371d8ffb46b076069d7c7851`（2026-08-03） |
| 大小 | 约 10 MB |
| 放哪 | `/opt/nccl-tests/` |
| 校验 | `git -C /opt/nccl-tests rev-parse HEAD` |

## 6. vLLM 运行时镜像（两台 Spark，各一份）

| 项 | 值 |
|---|---|
| 官方路径 | `ghcr.io/anemll/dspark-vllm-gx10:0.1.1`（[源码仓库 Anemll/dspark-vllm-gx10](https://github.com/Anemll/dspark-vllm-gx10)） |
| 国内镜像 | `ghcr.nju.edu.cn/anemll/dspark-vllm-gx10:0.1.1`（manifest 与官方逐层一致，已验证） |
| 大小 | 压缩层合计 9.79 GB；解压后 18.8 GB |
| 校验 | 拉完后 `docker image inspect --format "{{range .RepoDigests}}{{.}}{{end}}"` → 期望 digest `sha256:a83948492cf13df455170fb42885f5ef4db54fefe0feff0f841ecbff464ac9d8`；并对比官方 manifest 的 44 层 digest（见 07 章） |
| 说明 | 官方 vLLM playbook 另提供 NGC 镜像 `nvcr.io/nvidia/vllm:<tag>`（[NGC 目录](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm)），但 DeepSeek-V4-Flash-0731 的 DSpark/NVFP4 路径需 Anemll 镜像 |

## 7. 模型权重 DeepSeek-V4-Flash-0731（双机各一份）

| 项 | 值 |
|---|---|
| 官方路径 | <https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731>（官方 deepseek-ai 组织，**非门控**） |
| 国内加速 | `hf-mirror.com`（环境变量 `HF_ENDPOINT=https://hf-mirror.com`） |
| 大小 | **166.9 GB**，74 个文件 / 48 个 safetensors 分片 |
| 放哪 | head：`/opt/models/deepseek-ai/DeepSeek-V4-Flash-0731/`（`<org>/<model>` 布局，模型库根 `/opt/models`）；worker 由 200G 内网 rsync 到同路径 |
| 校验 | 官方 LFS sha256 清单 74/74 全量通过（见 06 章），双机一致 |
| 注意 | 不要用官方 HF 下载器直连（中国网络不通/极慢）；原仓库自带 `scripts/dsv4-chunkdl.py`（已随本次改造移除） |

## 8. Python 工具（head 一台即可）

| 项 | 值 |
|---|---|
| 来源 | PyPI（`pip`，建议装进独立 venv `~/hf-venv`） |
| 包 | `huggingface_hub`（含 hf CLI）、`hf_xet`、`httpx` |
| 用途 | 生成官方 sha256 清单、分块下载器运行依赖 |
| 校验 | `~/hf-venv/bin/hf version` |

## 9. 部署仓库（head）

| 项 | 值 |
|---|---|
| 官方路径 | <https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark>，建议 pin `a4ce87a2f47f1be8fe64c297a0cf33a9a5e509aa`（2026-08-04） |
| 大小 | 约 10 MB |
| 放哪 | 本仓库 `dspark/` 子模块；部署到双机 `config.yaml` 的 `common.runtime_repo`（默认 `/opt/deepseek-flash/dspark/`） |
| 校验 | `git rev-parse HEAD` |

## 10. 备选 / 可选

| 项 | 来源 | 用途 |
|---|---|---|
| `aria2`（apt，约 2 MB） | Ubuntu 源 | 备选多线程下载器（本方案用自研脚本，可不装） |
| naive 代理客户端 | <https://github.com/klzgrad/naiveproxy/releases>（Linux arm64 最新版） | 受限网络下系统级代理（可选） |
| 官方 playbook 辅助脚本 `setup.sh` / `launch.sh` | [NVIDIA/dgx-spark-playbooks](https://github.com/NVIDIA/dgx-spark-playbooks) `nvidia/nccl/assets/` | NCCL 快速安装（本方案用手动命令，等价） |
| 官方 vLLM `run_cluster.sh`（Ray 方案，未采用） | <https://raw.githubusercontent.com/vllm-project/vllm/51c1ee9b7c8acbba4899a8ebffd390685d171946/examples/ray_serving/run_cluster.sh> | 官方 vLLM playbook 的备选启动方式 |
| 备选镜像家族 `aidendle94/sparkrun-vllm-ds4-gb10` | <https://hub.docker.com/r/aidendle94/sparkrun-vllm-ds4-gb10> | 早期社区镜像（本方案最终采用 Anemll 0.1.1，列为备选） |

## 11. 全部官方文档路径速查

| 主题 | 路径 |
|---|---|
| NVIDIA Sync 安装 | <https://docs.nvidia.com/sync/latest/getting-started.html> |
| Cluster Assistant | <https://docs.nvidia.com/sync/latest/cluster-assistant.html> |
| Sync 下载页 | <https://build.nvidia.com/spark/connect-to-your-spark> |
| DGX Spark 用户指南 | <https://docs.nvidia.com/dgx/dgx-spark/> |
| DGX Spark 首次启动 | <https://docs.nvidia.com/dgx/dgx-spark/first-boot.html> |
| 连接两台 Spark playbook | <https://build.nvidia.com/spark/connect-two-sparks> |
| NCCL playbook | <https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/nccl/README.md> |
| vLLM playbook | <https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/vllm/README.md> |
| 模型卡 | <https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731> |
| HF API（sha256 清单） | <https://huggingface.co/api/models/deepseek-ai/DeepSeek-V4-Flash-0731> 与 `/tree/main?recursive=true&expand=true` |
| Anemll 镜像源码 | <https://github.com/Anemll/dspark-vllm-gx10> |
| MiaAI 部署仓库 | <https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark> |
| MiaAI 早期 recipe（被 DSpark-2x 取代） | <https://github.com/MiaAI-Lab/DeepSeek-V4-Flash-Dual-DGX-Spark-1M-Context> |
| 社区踩坑笔记（elsung，本方案大量引用） | <https://github.com/elsung/dgx-spark-deepseek-v4-flash>（尤其 `SETUP-NOTES.md`） |
| 备选镜像 `aidendle94/sparkrun-vllm-ds4-gb10` | <https://hub.docker.com/r/aidendle94/sparkrun-vllm-ds4-gb10> |
| vLLM `run_cluster.sh`（Ray 备选） | <https://github.com/vllm-project/vllm> `examples/ray_serving/run_cluster.sh`（pin `51c1ee9b`） |
| naiveproxy 官方发布页（可选代理） | <https://github.com/klzgrad/naiveproxy/releases> |
| NGC vLLM 目录（备选镜像） | <https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm> |
