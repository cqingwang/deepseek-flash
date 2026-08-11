# DeepSeek-V4-Flash-0731 双 DGX Spark 部署复现手册

> 🌐 **English version:** [English Documentation](en/README.md) — the complete guide for English users.

> 本文档完整记录了在一对 NVIDIA DGX Spark（GB10）上，通过 200GbE QSFP 直连组成双机集群，
> 并以 vLLM（Anemll DSpark 镜像）部署 **DeepSeek-V4-Flash-0731**（TP=2、100 万上下文）的
> 全部过程。目标是让另一对机器可以按章节逐步复现。
>
> **敏感信息已全部脱敏**：所有 IP、主机名、Wi-Fi/代理账号密码、SSH 密钥均以 `<占位符>` 表示，
> 见 [VARIABLES.md](VARIABLES.md)。

## 效果预览（最终部署运行实况）

> 部署完成后，配合自研监控面板（独立仓库 [`dgx-spark-2-deepseek-flash-dashboard`](https://github.com/maliubiao/dgx-spark-2-deepseek-flash-dashboard)）可实时查看运行实况。
> 下图为面板在真实环境中的截图：单会话 **60–70 tok/s**、GPU 约 **70°C**、连续长跑不崩溃；
> 完整图文实录见 [08 章 §8.6](docs/08-verify.md)。

![面板预览 1 —— 实时总览](docs/perf/vibe-panel-1.png)

![面板预览 2 —— GPU/主机与吞吐](docs/perf/vibe-panel-2.png)

![面板预览 3 —— 性能详情](docs/perf/vibe-panel-3.png)

## 一、架构与结果

```
┌──────────────┐   QSFP112 DAC 直连 (200GbE)   ┌──────────────┐
│  DGX Spark A │◄══════════════════════════════►│  DGX Spark B │
│  (head)      │  RoCE: 10.100.192.x / 193.x    │  (worker)    │
│  GB10 ×1     │                                │  GB10 ×1     │
└──────┬───────┘                                └──────────────┘
       │ 管理网 (有线/ Wi-Fi, 同一 LAN)
       ▼
   OpenAI 兼容 API: http://<IP_MGMT_A>:8888/v1
```

- 模型：`deepseek-ai/DeepSeek-V4-Flash-0731`（官方 0731 GA，I8/FP4 量化，**166.9 GB**，48 分片）
- 推理引擎：vLLM 0.25.2（`ghcr.io/anemll/dspark-vllm-gx10:0.1.1`），TP=2，DSpark MTP5 投机解码
- KV cache：`nvfp4_ds_mla`，双机约 **230 万 token** 共享池（94baabf + util 0.835 实测），`max_model_len=1048576`
- 实测性能（社区 + 本方案）：单流约 **60–96 tok/s**，热机 decode ~78–80 tok/s，DSpark 接受率 ~91%，
  高并发聚合最高约 340 tok/s（社区数据，需配合 `DEFAULT_THINKING=low/off` 压测）
- 长跑体验（本方案实测）：Agent/Vibe Coding 连续多轮长跑 **稳定不崩溃**，单会话 **60–70 tok/s**，
  跑 Agent 期间 GPU 约 **70°C**，体验结论为“完全能用、使用体验不错”——图文实录见 [08 章 §8.6](docs/08-verify.md)

## 二、章节导航

| 章节 | 内容 | 用时参考 |
|---|---|---|
| [01 硬件与拓扑](docs/01-hardware.md) | 机器、线缆、物理口映射 | 30 min（含装机） |
| [02 系统初始化](docs/02-system-init.md) | 首次启动、OTA、固件、驱动验证 | 1–2 h |
| [03 基础配置](docs/03-basics.md) | 用户、SSH、网络、代理（脱敏模板） | 30 min |
| [04 双机集群](docs/04-cluster-assistant.md) | NVIDIA Sync + Cluster Assistant | 30 min |
| [05 NCCL 验证](docs/05-nccl.md) | 编译 NCCL + 双机通信测试 | 30–60 min |
| [06 模型下载](docs/06-model-download.md) | 官方清单、分块下载器、内网同步、完整性校验 | 2–4 h（取决于带宽） |
| [07 部署启动](docs/07-deploy.md) | 镜像、配置、启动服务 | 30 min + 冷启动 ~8 min |
| [08 验证与性能](docs/08-verify.md) | API、冒烟、压测、性能预期 | 15 min |
| [09 运维与排查](docs/09-ops.md) | 自恢复、加固、故障表 | 持续 |
| [10 附录](docs/10-appendices.md) | 上游仓库、文件清单、变量表 | — |

## 三、快速开始（TL;DR）

前置条件：两台已联网、可 SSH 的 DGX Spark（系统 ≥ 2026-04 版本）、一根 QSFP112 DAC 线、
一台装有 NVIDIA Sync 的电脑（**Windows / macOS / Ubuntu 均可**，详见 04 章）。

```bash
# 0. 替换 VARIABLES.md 中的全部 <占位符>
# 1. 硬件：插线 → 系统升级 → SSH 免密（见 01–03 章）
# 2. 集群：NVIDIA Sync → Cluster Assistant（见 04 章）
# 3. NCCL：见 05 章
# 4. 模型：见 06 章（国内网络已适配；海外网络可直接用 hf 官方下载器）
# 5. 部署：见 07 章 → ./start-deepseek-v4-flash-dspark.sh（94baabf：自动应用 Issue #22/#21 hotfix）
# 6. 验证：curl http://<IP_MGMT_A>:8888/v1/models
```

## 四、目录结构

> 克隆后目录名 = 仓库名 `dgx-spark-2-deepseek-flash-0731`（git clone 会按仓库名建目录）。
> 当前实际树：

```text
dgx-spark-2-deepseek-flash-0731/
├── README.md                    # 本文件（含最终效果预览：监控面板截图）
├── LICENSE                      # MIT 许可
├── VARIABLES.md                 # 全部脱敏占位符对照表（先替换）
├── .gitignore                   # 忽略 .DS_Store / *.log
├── en/                          # 英文版整套文档（README + VARIABLES + docs/）
├── docs/
│   ├── DOWNLOADS.md             # ★ 下载清单：要下载什么、官方路径、大小、校验
│   ├── 01-hardware.md … 10-appendices.md   # 分章节教程
│   └── perf/                    # 效果实录配图（监控面板实时截图）
└── scripts/
    ├── dsv4-chunkdl.py          # 自研分块下载器（断点续传 + sha256 校验）
    ├── resume-downloads.sh      # 开机自恢复（下载/镜像）
    ├── repro-preflight.sh       # 复现前环境自检
    ├── .env.dspark.example      # vLLM 双机配置模板（脱敏）
    ├── dspark-vllm-start.sh     # systemd 自启包装脚本（head，脱敏模板）
    ├── dspark-vllm-stop.sh      # systemd 停止包装脚本（head，脱敏模板）
    ├── dspark-vllm-ensure.sh    # worker 容器守护脚本（脱敏模板）
    ├── dspark-vllm.service      # head systemd 单元
    ├── dspark-vllm-worker.service  # worker systemd 单元
    └── install-autostart.sh     # 一键安装双机自启
```

## 五、官方文档路径与下载物

**先读 [docs/DOWNLOADS.md](docs/DOWNLOADS.md)**——它列出了全部需要下载的东西（NVIDIA Sync、
系统 OTA、NCCL 源码、Anemll 镜像、166.9GB 模型、Python 工具、部署仓库），每项都带官方路径、
大小、下载位置和校验命令。

核心官方参考：

- [NVIDIA Sync 安装](https://docs.nvidia.com/sync/latest/getting-started.html)
- [Cluster Assistant](https://docs.nvidia.com/sync/latest/cluster-assistant.html)
- [DGX Spark 用户指南 / 首次启动](https://docs.nvidia.com/dgx/dgx-spark/first-boot.html)
- [NCCL playbook](https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/nccl/README.md)
- [vLLM playbook](https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/vllm/README.md)
- [模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731)
- [Anemll 镜像源码](https://github.com/Anemll/dspark-vllm-gx10)
- [MiaAI 部署仓库](https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark)

> **原始素材索引**：所有引用的仓库/网站/镜像/模型（含社区踩坑笔记、备选方案）以及
> "哪些随包提供、哪些仅引用"的完整对照，见 [10 附录 §10.2](docs/10-appendices.md)。
> 完整下载物清单见 [docs/DOWNLOADS.md](docs/DOWNLOADS.md)。

## 六、安全与脱敏说明

- 文档不含任何真实 IP、主机名、MAC、Wi-Fi/代理口令或 SSH 私钥。
- 部署中的 `sudo` 密码请自行设置，**不要**启用文档示例中的任何默认口令。
- 模型与镜像均来自官方/公开来源；镜像拉取时建议核对 manifest digest（见 06 章）。
- 若身处非中国网络，06 章中的镜像/下载源可替换为官方源（标注了替代方案）。
