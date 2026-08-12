# 06 模型下载与完整性（适配受限网络）

> ⚠️ **本仓库已移除下载脚本**：`scripts/dsv4-chunkdl.py` 与 `scripts/resume-downloads.sh` 不再随仓库提供
> （模型已在 `/opt/models` 平铺就位，无需下载流程）。本章保留作为历史复现参考；
> 模型已就位时可跳过本章，直接进入 [07 章](07-deploy.md)。

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

## 6.4 运行分块下载器（head，后台）

下载器 `scripts/dsv4-chunkdl.py` 特点：20 并发 × 8MB 分块、每块 120s 超时 + 8 次重试、
断点续传（`.chunks.json`）、文件级 sha256 校验、失败自动重下、`--verify-only` 全量复核。

```bash
# 前台看进度
env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  ~/hf-venv/bin/python ~/dsv4-chunkdl.py

# 或脱离 SSH 会话后台运行（防断连中断）
nohup setsid env -u http_proxy -u https_proxy -u all_proxy \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  ~/hf-venv/bin/python ~/dsv4-chunkdl.py >> ~/dsv4-chunkdl.log 2>&1 < /dev/null &
# 验证已脱离：ps -eo pid,ppid,sid,tty,cmd | grep dsv4-chunkdl  → PPID=1, TTY=?
```

成功标志（日志末尾）：

```text
ALL_DOWNLOADED
[verify] checked 74/74 files, failures: 0
```

> 实测：hf-mirror 直连 + 20 并发约 **30–40 MB/s**，166.9 GB 约 1.5–2.5 小时。
> 若遇速度归零假死，下载器会按块超时重试，无需人工干预。

## 6.5 同步到 worker（200G 内网）

模型必须双机各一份（TP=2 每个 rank 都要读全部权重）。用 fabric IP 走 200G 链路 rsync：

```bash
# head 上执行（脱离会话）
nohup setsid rsync -a --partial --info=progress2 \
  -e "ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null" \
  ~/.cache/huggingface/models/ <USER>@<IP_FABRIC_B>:~/.cache/huggingface/models/ \
  > ~/model-rsync.log 2>&1 < /dev/null &
```

实测约 **450–500 MB/s**，166.9 GB 约 6 分钟。

## 6.6 worker 全量校验

把清单与下载器复制到 worker 后跑 `--verify-only`：

```bash
scp ~/dsv4-files.json ~/dsv4-chunkdl.py <USER>@<IP_MGMT_B>:~/
ssh <USER>@<IP_MGMT_B> \
  'nohup setsid env -u http_proxy -u https_proxy -u all_proxy \
   -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
   ~/hf-venv/bin/python ~/dsv4-chunkdl.py --verify-only >> ~/dsv4-verify.log 2>&1 < /dev/null &'
```

期望：`[verify] checked 74/74 files, failures: 0`。

## 6.7 数据完整性要点（踩过的坑）

1. **官方清单来自 HF API 的 LFS oid**，是权威 sha256；不要信任任何第三方 SHA256SUMS。
2. 下载器曾有一个真实 bug：服务器忽略 Range 返回 200 时，把文件头部字节写到了错误偏移，
   导致文件 hash 不一致——已修复（200 只允许 off=0）并用 200MB 对照测试验证。
3. 损坏文件会以 `[hash-fail]` 报出并自动重下；`--verify-only` 可随时复核整库。
4. 若使用官方 `hf download`（非本脚本）：务必 `HF_HUB_DISABLE_XET=1`，否则 Xet 协议在受限网络
   直接 403/假死；且下载进程要挂 `nohup setsid` 防断连。

