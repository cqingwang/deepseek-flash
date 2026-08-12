# DeepSeek-V4-Flash 双机部署方案（program.py 单一实现）

> 本文件记录**当前实现**的最终方案：`program.py` 是唯一实现（一个文件完成所有功能），
> `deploy.sh` 是命令解析薄层，systemd 单元直接调用 `program.py`。
> 参数 SSOT：`config.yaml`（common/head/worker 分类）+ `dspark.env.json`（.env 固定参数模板）。
> 参数全集以 main 分支原始实现 `scripts/.env.dspark` 的最终参数为准（61 键）。

---

## 一、文件结构（当前实际）

```
deploy.sh             薄层（≈30 行）：剥 "--" 前缀 + 注入 config 路径 → 转发 program.py
program.py            唯一实现（纯 stdlib + pyyaml）：命令 → 函数分发
config.yaml           集群参数 SSOT（common/head/worker）
dspark.env.json       .env.dspark 固定参数模板（固定键值 + null 占位变化键）
systemd/
  dspark-vllm-head.service      head 单元：ExecStart=program.py start / ExecStop=... stop
  dspark-vllm-worker.service    worker 单元：ExecStart=program.py ensure
docs/                 分章节教程（07 部署 / 08 验证 / 09 运维 / 10 附录）
```

部署布局（install 自动完成）：
- `program.py` / `config.yaml` / `dspark.env.json` → 双机 `/etc/dspark-vllm/`
- systemd 单元 → 双机 `/etc/systemd/system/`
- 生产 `.env.dspark` → 双机 `$REPO/.env.dspark`（`/opt/deepseek-flash/`，不入 git）

已删除：`scripts/` 目录全部旧脚本（启动、安装、自检、长上下文验证、`.env` 模板等——功能均已并入
`program.py` / `dspark.env.json`）。

---

## 二、架构与两种用法

```
用法一：管理与部署 / 自检（head 上执行）
   ./deploy.sh --install [模型] / --uninstall / --restart / --live_check / --chat_verify / --doctor
        │  剥掉 "--" 前缀 + 注入 config.yaml 路径（薄层，无业务逻辑）
        ▼
   python3 program.py --config <config.yaml> <命令> [参数]

用法二：部署后运行支撑（双机本机，systemd 单元 ExecStart 直调）
   [head ] systemctl start dspark-vllm-head.service     → program.py start / stop
   [worker] systemctl start dspark-vllm-worker.service  → program.py ensure
```

**职责划分**：
- `program.py` 按本机 hostname 识别 head/worker 角色：head 上 `start` 先检查 API；head 缺失且
  worker 已运行时直接 compose 拉起 head，否则交给上游 start 脚本完成完整启动；head 上 `stop`=
  head 先停 → worker 后停（幂等）；worker 上 `ensure`=拉起 worker 容器（systemd 开机守护，幂等）。
- 上游容器编排仍调用 MiaAI 仓库 `start/stop-deepseek-v4-flash-dspark.sh`（94baabf，含
  Issue #22 hotfix）；program.py 只做编排与兜底 compose 拉起，不重复实现上游逻辑。
- 上游 start 脚本在 worker 容器已在时会拒绝执行，故 head 缺失 + worker 在时由 program.py
  直接 `compose_up` 拉起 head 并等待 API。

---

## 三、命令全集与 CLI（argparse）

入口统一：`python3 program.py [--config <config.yaml>] <命令> [参数]`（--config 缺省
`/etc/dspark-vllm/config.yaml`，systemd 本机调用时免传）。未知命令由 argparse 报错。

| 分组 | 命令 | 说明 |
|---|---|---|
| 管理与部署（head，经 deploy.sh） | `install [模型]` | 部署 program.py+dspark.env.json+config 到双机、装 systemd 单元、停旧容器、注册双机模型 symlink、生成并安装生产 .env、同步 worker、start + 等 API |
| | `uninstall` | stop → 移除双机模型 symlink → 禁用 systemd 自启 |
| | `restart` | = stop + start（head 上） |
| | `live_check [--wait 秒]` | curl `common.api_url` 健康检查；--wait 轮询（install 内部复用） |
| | `chat_verify [目标tokens]` | 长上下文解码性能验证（Issue #22，默认 620000；原 longctx-verify.py） |
| 自检（head） | `doctor [worker目标]` | 双机环境自检：SSH/GPU/CUDA/镜像/模型/RoCE/端口，FAIL 计数决定退出码 |
| 运行支撑（双机，systemd 直调） | `start` / `stop` | 仅 head（角色校验） |
| | `ensure` | 仅 worker（容器守护） |
| | `status` | 双机容器与 API 状态 |
| 工具 | `load-config [节...]` | 导出 `SECTION_KEY='value'`（调试导出） |
| | `gen-env --model 路径 [--output 文件]` | 生成完整 .env.dspark（install 内部复用） |
| | `help` | 打印用法 |

---

## 四、关键设计

### 4.1 统一日志（logtask）

```python
def logtask(action, desc="", level=LogLevel.INFO):
    """统一日志：时间戳 + level + action[: desc]；ERROR 打印后退出应用（快速失败）。"""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {action}" + (f" — {desc}" if desc else "")
    print(line, file=sys.stderr, flush=True)
    if level == LogLevel.ERROR:
        sys.exit(1)
```

- level：`LogLevel.INFO / WARN / ERROR`；ERROR 打印后进程以非 0 退出。
- **过程日志**（动作/进度/警告/错误）统一走 logtask（写 stderr）；**数据输出**（gen-env 的 .env 内容、
  load-config 导出行、chat_verify JSON 报告、doctor `[OK]/[FAIL]` 清单、help 文本）
  保持纯 stdout 不进日志，供管道捕获。

### 4.2 生产 .env 派生（gen-env + dspark.env.json）

- `dspark.env.json`：61 键模板。固定调优参数（vLLM/b12x/NCCL 等）直接写值；**19 个变化键
  用 `null` 占位**（网络 IP/RoCE/模型路径/镜像）。
- `gen_env(cfg, model_dir)`：读模板 → 从 config+模型覆盖 19 个变化键 → 模板残留 `null`
  即快速失败（Fail-Fast）。`install_env` 写入 `$REPO/.env.dspark` 并同步 worker。

### 4.3 安全与角色

- `drop_privilege`：systemd 以 root 启动时 `exec runuser -u common.user` 降权重跑。
- `node_role`：hostname 匹配 head/worker；不匹配或越权（如 worker 上跑 start）报 ERROR 退出。

### 4.4 常用辅助函数

`parser_yaml`（pyyaml 缺失提示）/ `parser_constants`（派生常量）/ `ssh_task` / `scp_task` /
`sudo_install` / `api_healthy` / `wait_for_api`（240×5s 冷启动）/ `compose_up`（NODE_RANK/
HEADLESS 注入 + `COMPOSE_DISABLE_ENV_FILE=1`）/ `container_exists_{local,remote}`。

---

## 五、运维用法速查（head 上）

```bash
./deploy.sh --doctor                   # 部署前自检（FAIL=0 才可部署）
./deploy.sh --install [模型路径]         # 安装/覆盖安装（默认 common.default_model）
./deploy.sh --live_check                # API 健康检查
./deploy.sh --chat_verify [目标tokens]   # 长上下文解码性能验证
./deploy.sh --restart | --stop          # 重启 / 停止
./deploy.sh --uninstall                 # 清理部署

# 双机 systemd（开机自启 + 崩溃自愈）
sudo systemctl start/stop dspark-vllm-head.service      # head
sudo systemctl status dspark-vllm-worker.service         # worker
```

---

## 六、已验证项

- 语法：`python3 -m py_compile program.py`、`bash -n deploy.sh`
- 命令分发：`--help` / `--doctor` / 无前缀命令 / 未知命令报错
- gen-env 参数核对：61 键与 main 原始 `.env.dspark` 全集一致（仅新增 `DSPARK_MODEL_ID`）
- 日志：时间戳 + level 格式；ERROR 打印后退出（live_check FAIL / 角色校验）
- 实机双机集成（install → live_check → restart → stop → uninstall）待实机验证
