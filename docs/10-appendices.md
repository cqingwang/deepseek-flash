# 10 附录：参考资料与文件清单

## 10.1 官方文档与仓库（全部路径）

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
| HF API：模型信息 | <https://huggingface.co/api/models/deepseek-ai/DeepSeek-V4-Flash-0731> |
| HF API：文件树（sha256） | <https://huggingface.co/api/models/deepseek-ai/DeepSeek-V4-Flash-0731/tree/main?recursive=true&expand=true> |
| Anemll 镜像源码 | <https://github.com/Anemll/dspark-vllm-gx10> |
| MiaAI 部署仓库 | <https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark> |
| MiaAI 早期 recipe | <https://github.com/MiaAI-Lab/DeepSeek-V4-Flash-Dual-DGX-Spark-1M-Context> |
| 社区踩坑笔记（elsung） | <https://github.com/elsung/dgx-spark-deepseek-v4-flash>（`SETUP-NOTES.md`） |
| 备选镜像（aidendle94） | <https://hub.docker.com/r/aidendle94/sparkrun-vllm-ds4-gb10> |
| vLLM 源码（run_cluster.sh 备选） | <https://github.com/vllm-project/vllm> |
| naiveproxy 官方发布页（可选） | <https://github.com/klzgrad/naiveproxy/releases> |
| NGC vLLM 目录（备选镜像） | <https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm> |
| NCCL 源码 | <https://github.com/NVIDIA/nccl> |
| nccl-tests 源码 | <https://github.com/NVIDIA/nccl-tests> |

## 10.2 原始素材索引（完整）

下表是本文档引用的**全部原始素材**：哪些是"打包在包内"，哪些是"引用 + 获取命令"。
本包只内置我们自研的脚本与文档（约 84 KB）；上游仓库/网站/镜像/模型均为**引用**，
文档中给出官方路径、pin 版本和获取命令，不复制上游代码进包（避免体积与版权问题）。

| 素材 | 类型 | 来源（网站/仓库） | 用途 | 相关章节 | 形态 |
|---|---|---|---|---|---|
| NVIDIA Sync（Windows / macOS / Ubuntu 桌面应用） | 桌面软件 | build.nvidia.com/spark/connect-to-your-spark | 集群配置 | 04 | 引用 |
| NVIDIA Sync 文档 | 网站 | docs.nvidia.com/sync/latest/ | 安装/Cluster Assistant | 03, 04 | 引用 |
| DGX Spark 用户指南 | 网站 | docs.nvidia.com/dgx/dgx-spark/ | 首次启动/OTA/网络 | 01, 02, 04 | 引用 |
| NVIDIA/dgx-spark-playbooks | GitHub 仓库 | github.com/NVIDIA/dgx-spark-playbooks | NCCL/vLLM 官方 playbook | 05, 07 | 引用 |
| NVIDIA/nccl（tag v2.30.7-1） | GitHub 仓库 | github.com/NVIDIA/nccl | NCCL 编译 | 05 | 引用 |
| NVIDIA/nccl-tests（pin 717b6831） | GitHub 仓库 | github.com/NVIDIA/nccl-tests | 双机通信测试 | 05 | 引用 |
| Anemll/dspark-vllm-gx10（镜像 0.1.1） | GitHub 仓库 + 容器镜像 | github.com/Anemll/dspark-vllm-gx10；ghcr.io（国内 ghcr.nju.edu.cn） | vLLM 运行时 | 07 | 引用（含 digest 校验） |
| MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark（pin a4ce87a2） | GitHub 仓库 | github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark | compose/启动脚本 | 07, 08, 09 | 引用 |
| MiaAI 早期 recipe（Dual-DGX-Spark-1M-Context） | GitHub 仓库 | github.com/MiaAI-Lab/DeepSeek-V4-Flash-Dual-DGX-Spark-1M-Context | 早期方案（被取代，留档） | 10 | 引用 |
| elsung/dgx-spark-deepseek-v4-flash | GitHub 仓库 | github.com/elsung/dgx-spark-deepseek-v4-flash | 社区踩坑笔记（GID/Xet/内核崩溃/性能） | 06, 09 | 引用 |
| aidendle94/sparkrun-vllm-ds4-gb10 | Docker Hub 镜像 | hub.docker.com/r/aidendle94/sparkrun-vllm-ds4-gb10 | 备选镜像家族 | 07 | 引用 |
| vllm-project/vllm（run_cluster.sh） | GitHub 仓库 | github.com/vllm-project/vllm（pin 51c1ee9b） | Ray 备选启动 | 07 | 引用 |
| deepseek-ai/DeepSeek-V4-Flash-0731 | HuggingFace 模型 | huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731 | 模型权重（166.9 GB） | 06 | 引用 |
| HF API（sha256 清单） | 网站 API | huggingface.co/api/models/... | 官方逐文件校验 | 06 | 引用 |
| hf-mirror.com / ghcr.nju.edu.cn | 国内镜像站 | hf-mirror.com；ghcr.nju.edu.cn | 受限网络加速 | 06, 07 | 引用 |
| klzgrad/naiveproxy | GitHub 发布页 | github.com/klzgrad/naiveproxy/releases | 可选代理客户端 | 03 | 引用 |
| NGC vLLM 目录 | 网站 | catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm | 备选官方镜像 | 07 | 引用 |
| 自研脚本（下载器/自恢复/自检/模板） | 本包 | — | 复现核心工具 | 06, 07 | **打包** |
| 本文档（README/章节/变量表） | 本包 | — | 复现指南 | 全部 | **打包** |

## 10.3 版本 pin（可复现性）

| 组件 | 版本/commit |
|---|---|
| 模型 | `deepseek-ai/DeepSeek-V4-Flash-0731` @ main `7872f01b1d1fe23eabc4c98b48bffcef5a386062`（下载时） |
| 运行时镜像 | `ghcr.io/anemll/dspark-vllm-gx10:0.1.1`，repo digest `sha256:a83948492cf13df455170fb42885f5ef4db54fefe0feff0f841ecbff464ac9d8` |
| MiaAI 仓库 | `a4ce87a2f47f1be8fe64c297a0cf33a9a5e509aa`（2026-08-04） |
| NCCL | tag `v2.30.7-1` |
| nccl-tests | `717b68318278e93f371d8ffb46b076069d7c7851`（2026-08-03） |
| vLLM（镜像内） | `0.25.2.dev0+g752a3a504.d20260714` |
| CUDA | 13.0（系统自带） |
| 驱动 | 580.x（内核模块 610.x API 兼容） |
| 网络计划 | Cluster Assistant 生成：`10.100.192.0/24` + `10.100.193.0/24` |

## 10.4 本包文件清单

| 文件 | 说明 |
|---|---|
| `README.md` | 总览与快速开始 |
| `VARIABLES.md` | 脱敏变量对照表 |
| `docs/DOWNLOADS.md` | 完整下载清单（官方路径/大小/校验） |
| `docs/01-hardware.md` … `docs/10-appendices.md` | 分章节教程 |
| `config.yaml` | 集群参数 SSOT（common/head/worker 分类，program.py 读取） |
| `deploy.sh` | 统一部署入口（薄层：命令解析 → 转发 program.py） |
| `program.py` | 唯一实现（install/uninstall/restart/live_check/chat_verify/doctor/start/stop/ensure/status/load-config/gen-env/help；随部署同步到双机 /etc/dspark-vllm/） |
| `dspark.env.json` | .env 参数模板（固定键值 + null 占位变化键，gen-env 派生生产 .env） |
| `systemd/dspark-vllm-head.service` | head systemd 单元（ExecStart=program.py start / stop，开机自启 + 失败重试） |
| `systemd/dspark-vllm-worker.service` | worker systemd 单元（ExecStart=program.py ensure，开机自启） |

## 10.5 变量引用速查

所有 `<占位符>` 定义见 [VARIABLES.md](../VARIABLES.md)。替换完成后：

```bash
rg -n "<[A-Z_]+>" README.md docs/ dspark.env.json   # 确认没有遗漏
```
