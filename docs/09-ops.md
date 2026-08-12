# 09 运维、自恢复与故障排查

## 9.1 日常命令

```bash
cd ~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark
./deploy.sh status                              # 双机容器与 API 状态
docker compose --env-file /opt/deepseek-flash/dspark/.env.dspark \
  -f /opt/deepseek-flash/dspark/docker-compose.dspark.yml logs --tail=200
./deploy.sh stop                                # 停止（先停 head 后停 worker）
docker compose --env-file /opt/deepseek-flash/dspark/.env.dspark \
  -f /opt/deepseek-flash/dspark/docker-compose.dspark.yml ps
```

## 9.2 开机自恢复（下载类任务）

> ⚠️ `scripts/resume-downloads.sh` 已从仓库移除（模型已在 `/opt/models` 就位，无需下载自恢复）。
> 如下为历史记录，仅供理解恢复思路：

```bash
chmod +x ~/resume-downloads.sh
( crontab -l 2>/dev/null | grep -v resume-downloads.sh; \
  echo "@reboot $HOME/resume-downloads.sh" ) | crontab -
```

重启后自动：续传未完成的模型下载、补拉缺失的镜像。所有长任务都应
`nohup setsid ... < /dev/null &` 脱离 SSH 会话（PPID=1、TTY=? 即成功）。

## 9.2b 推理服务开机自启（systemd，推荐）

仅靠上游 `start-deepseek-v4-flash-dspark.sh` 手动启动时，**机器重启后服务不会自动恢复**。
本方案在 head/worker 各装一个 systemd 单元实现开机自启 + 崩溃自愈（单元 ExecStart
直接调用 `program.py`）：

| 节点 | 单元 | 行为 |
|---|---|---|
| head | `dspark-vllm-head.service` | ExecStart=`program.py start`：API 已健康→跳过；worker 容器在而 head 缺失→compose 拉起 head 并等待；双缺→执行 `./start-...`。`Restart=on-failure`（60s 间隔，600s 内最多 5 次） |
| worker | `dspark-vllm-worker.service` | ExecStart=`program.py ensure`：开机确保 worker 容器在（幂等） |
| 双机 | 容器 `deepseek-v4-flash-vllm-dspark-1` | `restart: unless-stopped`（compose 已配置，见 07 章） |

安装（在 head 上执行 `./deploy.sh --install`，自动把 program.py + config.yaml 与
systemd 单元部署到双机）：

```bash
./deploy.sh --install
# 验证（两台都应输出 enabled）
systemctl is-enabled dspark-vllm-head.service        # head
systemctl is-enabled dspark-vllm-worker.service # worker
```

日常启动/停止/重启（与手动脚本等价，且 head 会连带编排 worker）：

```bash
sudo systemctl start dspark-vllm-head.service     # 幂等；冷启动会等待 API 就绪（最长约 20 分钟）
sudo systemctl stop dspark-vllm-head.service      # 停双机容器
sudo systemctl restart dspark-vllm-head.service
sudo systemctl status dspark-vllm-head.service
sudo journalctl -u dspark-vllm-head.service -f
```

> `systemctl stop` 会通过 ExecStop 调用 `program.py stop`（head+worker 一起停）；
> 若想彻底停用自启：`sudo systemctl disable dspark-vllm-head.service`（worker 同理）。

## 9.3 内核与内存加固

```bash
echo vm.compaction_proactiveness=0 | sudo tee /etc/sysctl.d/99-dsv4.conf
sudo sysctl -w vm.compaction_proactiveness=0
```

社区记录过：高负载下 `kcompactd` soft-lockup + NVIDIA `mstflint` 轮询触发内核 NULL-deref，
导致整机重启；`vm.compaction_proactiveness=0` 是防御手段。另注意 `mlx5_core insufficient power 27W`
日志是 GB10 集成 CX-7 的正常现象，不是故障。

## 9.4 常见故障排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| 集群测速 25G | 网络计划未生效 | 直接重启两台（线保持插着）后 Run Test Again；重启才是关键，反复插拔线缆无效 |
| `nvidia-smi` failed | 升级后未重启 | 重启 |
| NCCL `ibv_modify_qp` / GID 错误 | RoCEv2 GID 索引漂移 | 保持 `NCCL_IB_GID_AUTO=1`；或按 05 章逐台查 GID 表 |
| mpirun 卡住 | SSH 免密/主机密钥问题 | 先最小 `mpirun hostname` 验证 |
| 模型下载 hash-fail | 下载器旧 bug / 脏 sidecar | 用本包脚本（已修复）；删除 `*.chunks.json` 后重下 |
| 下载速度归零 | 单连接被限速/假死 | 分块下载器自动超时重试；检查网络源（见 06 章） |
| ghcr 镜像拉不动 | blob CDN 被限速 | 用 ghcr.nju.edu.cn 镜像 + digest 校验 |
| 服务起不来 / 端口占用 | 上次未正常停止 | `./deploy.sh stop` 后重试 |
| 单请求输出数万 token 不停 | `DEFAULT_THINKING=max` + 开放提示词 | 请求加 `thinking:false`；压测改 `low/off` |
| 600K+ 上下文 decode 慢（~1 tok/s） | 旧版本 Issue #22：`nvfp4_ds_mla` 走了慢速 bf16 kernel | 升级到 94baabf（start 自动应用 hotfix）；验证 `flashmla_sparse.py:880` 为 `in ("fp8_ds_mla", "nvfp4_ds_mla")` |
| 多轮 tool call 历史被污染 | 旧版 Issue #21：encoding 对 dict arguments 误 `json.loads` | 94baabf 自动应用 `hotfix-encoding-dsv4-issue21.py`；日志见 `[OK] Issue #21 patch applied` |
| 高并发下内存涨 | vLLM prefix-cache 老版本泄漏 | 使用 Anemll 0.1.1 镜像（已修复） |
| SSH 断连后下载中断 | 进程挂在会话上 | 一律 `nohup setsid` + `@reboot` 自恢复 |

## 9.5 升级与回滚

### 升级到 94baabf（2026-08-11 实测）

> 本手册对应 MiaAI 部署仓库 **94baabf**（text-only 0731 默认）。旧版（≤ `a4ce87a`）
> 升级步骤如下，已实测通过。

```bash
cd ~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark   # head 上
# 1) 丢弃本地对 compose 的手工修改（如不再需要）
git checkout -- docker-compose.dspark.yml
git pull origin main                          # a4ce87a..94baabf（7 commits）
# 2) .env 迁移（新版变量约定）：
#    - DSPARK_MODEL=…        → 删掉，改设 DSPARK_MODEL_OFFICIAL=…（同路径）
#    - GPU_MEMORY_UTILIZATION → 删掉，改设 GPU_MEMORY_UTILIZATION_TEXT=0.835
#    - 新增 ABLITERATED=0、ENABLE_VL_SIDECAR=0
#    - DSPARK_REVISION 留空即可（自动 pin；本地路径模型不受影响）
# 3) 完整重启（start 自动同步 worker 并应用 Issue #22/#21 hotfix）
./stop-deepseek-v4-flash-dspark.sh
./start-deepseek-v4-flash-dspark.sh
```

升级内容摘要（`a4ce87a` → `94baabf`，7 commits）：

| 提交 | 内容 | 影响 |
|---|---|---|
| `6c42a7a` | **Issue #22**：`nvfp4_ds_mla` 长上下文解码回归修复（600K+ 时 16x 减速） | ⭐ 核心：start 自动 hotfix，长上下文 decode 恢复 70+ tok/s |
| `e4e8368` | MoonViT 原生视觉多图（后随 94baabf 删除） | 无 |
| `4dceb4c`/`d084c94`/`50d8f57` | VL sidecar 视觉实验路径 + MCP | 默认关闭（`ENABLE_VL_SIDECAR=0`） |
| `801db32` | `ABLITERATED` 开关 + text/vision profile 拆分 | `.env` 迁移：`GPU_MEMORY_UTILIZATION_TEXT`/`_VISION` |
| `94baabf` | **text-only 0731 默认**；Issue #21 encoding 修复；Issue #19 revision pin | 删除 MoonViT 视觉整条线（~11,700 行）；KV 池随 util 0.835 升至 ≈230 万 token |

实测效果：620K/780K 上下文 decode 70–73 tok/s（见 08 章 §8.7）；KV 池 17.02+16.64 GiB。

> ⚠️ 旧版曾以 base64 内嵌方式自研过 toolcall-guard 补丁（chat_utils.py 畸形 JSON 容错）。
> 升级时已整体丢弃——官方 Issue #21 hotfix 覆盖同类问题，且 94baabf 的 compose 不再含该段。

- 换镜像：改 `.env.dspark` 的 `DSPARK_VLLM_IMAGE` → 双机 `docker pull` → 重启。
- 换模型版本：重下模型缓存 → 更新 `DSPARK_MODEL_OFFICIAL` 与 `DSPARK_ENCODING_FILE` → 重启。
- 回滚网络：删除集群会清掉双机 SSH 与网络计划（Sync → Settings → Clusters → Delete），
  网络计划文件：`/etc/netplan/99-nvidia-sync-cluster.yaml`。
- 回滚部署仓库：`git checkout <旧 commit>` 后恢复旧版 `.env` 变量（`DSPARK_MODEL`、`GPU_MEMORY_UTILIZATION`），再 stop/start。
