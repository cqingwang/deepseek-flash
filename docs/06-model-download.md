# 06 模型下载与完整性（适配受限网络）

本仓库通过 `deploy.sh --fetch <org>/<model>` 提供模型下载入口。模型下载到
`config.yaml` 的 `common.model_lib/<org>/<model>`，例如：

```bash
./deploy.sh --fetch deepseek-ai/DeepSeek-V4-Flash-0731
```

`--fetch` 在当前 head 节点执行，使用 main 分支同源的分块下载逻辑：20 并发、8 MiB HTTP
Range、每块重试、`.chunks.json` 断点记录、文件级 SHA-256 校验和失败文件重下；模型下载完成后
仍需按本章 6.5–6.6 节同步到 worker 并校验。下载器实现位于 `scripts/model-fetch.py`。

## 6.1 事实清单

- 模型：`deepseek-ai/DeepSeek-V4-Flash-0731`（官方 0731 GA，I8/FP4 量化）
- 大小：**166.9 GB** / 74 个文件 / 48 个 safetensors 分片
- 授权：**非门控**（无需 HF token；匿名下载即可，登录可提升限速）
- 网络实测（中国大陆）：hf.co 直连不通、代理约 0 MB/s、Xet 协议被拒；
  **hf-mirror.com 直连可用**（单连接 ~27 MB/s）。海外网络直接用官方源。

## 6.2 准备清单与工具（head）

```bash
# venv 与工具（一次性）
python3 -m venv ~/hf-venv
~/hf-venv/bin/pip install -U huggingface_hub hf_xet httpx
```

下载时可通过 `HF_ENDPOINT` 选择源；中国大陆可使用：

```bash
HF_ENDPOINT=https://hf-mirror.com ./deploy.sh --fetch deepseek-ai/DeepSeek-V4-Flash-0731
```

也可用 `HF_TOKEN` 提供 Hugging Face token。模型已经存在时再次执行 `--fetch` 会复用本地
目录继续下载，不会因为目录存在而跳过缺失文件。

## 6.3 生成官方 sha256 清单

清单 = 每个文件的 `path / size / sha256`，其中 sha256 来自 HF 官方 API 的 **LFS oid**。
保存为 `~/dsv4-files.json`（下载器与校验器都依赖它）：

```bash
env -u all_proxy -u ALL_PROXY \
  http_proxy=http://127.0.0.1:1087 https_proxy=http://127.0.0.1:1087 \
  HF_ENDPOINT=https://huggingface.co \
  ~/hf-venv/bin/python - <<'PY'
import json
from huggingface_hub import HfApi
api = HfApi()
files = list(api.list_repo_tree("deepseek-ai/DeepSeek-V4-Flash-0731", recursive=True, expand=True))
out = [{"path": f.path, "size": f.size,
        "sha256": (f.lfs.sha256 if getattr(f, "lfs", None) else None)} for f in files]
json.dump(out, open("/tmp/dsv4-files.json", "w"), indent=1)
print("files:", len(out), "total GB: %.2f" % (sum(x["size"] for x in out) / 1e9))
PY
cp /tmp/dsv4-files.json ~/dsv4-files.json
```

预期输出：`files: 74  total GB: 166.90`，48 个分片均有 sha256。

## 6.4 下载模型（head，前台或后台）

`deploy.sh --fetch` 先从 Hugging Face API 生成当前模型的官方文件清单，再使用 20 个下载
worker 分块下载到配置的模型库。每个文件使用 `<file>.chunks.json` 保存已完成的 chunk 偏移，
中断后重新执行同一命令会继续未完成的块。每个块 120 秒超时、最多重试 8 次；单文件最多
处理 10 轮失败重试。

```bash
# 前台看进度；模型目录由 config.yaml 的 common.model_lib 决定
env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  ./deploy.sh --fetch deepseek-ai/DeepSeek-V4-Flash-0731

# 或脱离 SSH 会话后台运行（防断连中断）
nohup setsid env -u http_proxy -u https_proxy -u all_proxy \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  ./deploy.sh --fetch deepseek-ai/DeepSeek-V4-Flash-0731 \
  >> ~/model-fetch.log 2>&1 < /dev/null &
# 验证已脱离：ps -eo pid,ppid,sid,tty,cmd | grep 'deploy.sh --fetch' → PPID=1, TTY=?
```

成功标志：日志出现 `ALL_DOWNLOADED` 和 `[verify] ... failures: 0`，且目标目录包含
`config.json`。如果进程中断，重复执行同一命令即可继续。下载过程中的清单保存在目标目录
`.fetch-files.json`，成功的文件会删除对应的 `.chunks.json`。

`--fetch` 已包含全量完整性校验，不会把模型自动注册为当前服务模型，也不会自动重启服务。

> 实测：hf-mirror 直连 + 20 并发约 **30–40 MB/s**，166.9 GB 约 1.5–2.5 小时。
> 若遇速度归零假死，下载器会按块超时重试，无需人工干预。

## 6.5 同步到 worker（200G 内网）

模型必须双机各一份（TP=2 每个 rank 都要读全部权重）。用 fabric IP 走 200G 链路 rsync：

```bash
# head 上执行（脱离会话）
nohup setsid rsync -a --partial --info=progress2 \
  -e "ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null" \
  /opt/models/ <USER>@<IP_FABRIC_B>:/opt/models/ \
  > ~/model-rsync.log 2>&1 < /dev/null &
```

实测约 **450–500 MB/s**，166.9 GB 约 6 分钟。

## 6.6 worker 全量校验

把下载器复制到 worker 后，使用相同模型名和目标路径执行 `--verify-only`：

```bash
scp scripts/model-fetch.py <USER>@<IP_MGMT_B>:~/model-fetch.py
ssh <USER>@<IP_MGMT_B> \
  'HF_ENDPOINT=https://hf-mirror.com ~/hf-venv/bin/python ~/model-fetch.py \
   --repo-id deepseek-ai/DeepSeek-V4-Flash-0731 \
   --destination /opt/models/deepseek-ai/DeepSeek-V4-Flash-0731 \
   --verify-only >> ~/dsv4-verify.log 2>&1'
```

期望：`[verify] checked 74/74 files, failures: 0`。

## 6.7 数据完整性要点（踩过的坑）

1. **官方清单来自 HF API 的 LFS oid**，是权威 sha256；不要信任任何第三方 SHA256SUMS。
2. 下载器曾有一个真实 bug：服务器忽略 Range 返回 200 时，把文件头部字节写到了错误偏移；
   当前实现只允许 `offset=0` 的首块接受 200，其余块必须返回 206。
3. 损坏文件会以 `[hash-fail]` 报出并自动重下；`--verify-only` 可随时复核整库。
4. `--fetch` 默认使用 `https://hf-mirror.com`，并设置 `HF_HUB_DISABLE_XET=1`；可通过
   `HF_ENDPOINT=https://huggingface.co` 切回官方源。长任务要挂 `nohup setsid` 防断连。
