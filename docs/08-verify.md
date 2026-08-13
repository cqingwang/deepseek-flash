# 08 验证与性能

## 8.1 API 健康检查

```bash
curl http://<IP_MGMT_A>:8888/health          # 期望 200
curl http://<IP_MGMT_A>:8888/v1/models       # 期望 max_model_len: 1048576
```

## 8.2 最小对话

```bash
curl http://<IP_MGMT_A>:8888/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash-0731",
       "messages":[{"role":"user","content":"计算 17*23 等于多少，只回答数字"}],
       "temperature":0,"max_tokens":200,
       "chat_template_kwargs":{"thinking":false}}'
```

期望：`391`，秒级返回。若需模型思考（reasoning），去掉 `thinking:false` 或保持默认 `max`。

## 8.3 仓库自带脚本（Annotation 1：冒烟测试）

当前简化部署入口统一为 `deploy.sh`；上游 compose 的日志和状态仍可直接通过 Docker 查看：

```bash
cd ~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark
./deploy.sh status
docker compose --env-file /opt/deepseek-flash/dspark/.env.dspark \
  -f /opt/deepseek-flash/dspark/docker-compose.dspark.yml ps
docker compose --env-file /opt/deepseek-flash/dspark/.env.dspark \
  -f /opt/deepseek-flash/dspark/docker-compose.dspark.yml logs --tail=200
```

实测结果：**6/6 请求全部成功**。

## 8.4 基准压测（注意思考级别）

```bash
cd ~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark
python3 scripts/benchmark-0731.py \
  --base-url http://127.0.0.1:8888/v1 \
  --model deepseek-v4-flash-0731 \
  --prompt-lengths 256,2048,8192 --concurrency 1,3,6 \
  --output results/benchmark-smoke.json
```

> **重要坑**：`DEFAULT_THINKING=max` 时模型会产生超长推理链（单个请求可生成数万 token），
> 一个用例要 10–20+ 分钟甚至跑飞。**压测前请把 `.env.dspark` 的 `DEFAULT_THINKING` 改为
> `low` 或 `off` 并重启服务**，否则结果不可用。

## 8.5 性能预期

本方案实测（DSpark MTP5、NVFP4 DS-MLA、TP=2）：

| 指标 | 实测/预期 |
|---|---|
| 单流 decode（含推理） | ~60–80 tok/s（热机 78–80） |
| prefill | 372 token 提示 ~99 tok/s；短提示可达 ~2000 tok/s |
| DSpark 投机接受率 | ~91%（平均接受长度 5.5+） |
| GPU 利用率 | ~95% |
| KV 池 | 双机 **~230 万 token**（94baabf + `GPU_MEMORY_UTILIZATION_TEXT=0.835` 实测 17.02+16.64 GiB；旧版 0.80 约 183 万） |
| 高并发聚合（社区，thinking=off） | 最高约 340 tok/s @ c32 |

KV 池是共享的：总在线 token ≤ ~2.3M，长上下文与高并发互斥（详见 [09 章](09-ops.md)）。

## 8.6 实测效果：Agent 长跑 / Vibe Coding 实录
> 在双 DGX Spark 上连续多轮跑 Agent（Vibe Coding 一个双机监控面板 + 长会话对话）之后的真实体验，
> 附带自建监控面板的实时截图。

**结论先行**：这套「双 DGX Spark × DeepSeek-V4-Flash-0731」**完全能用，使用体验不错**——
不是“能跑起来”的演示水平，而是可以当主力开发机稳定干活的那一档。

| 维度 | 实测 | 说明 |
|---|---|---|
| 解码速度 | **60–70 tok/s（单会话）** | 比预想更好：长对话、多轮 Agent 协作下几乎感觉不到等待 |
| 稳定性 | **连续数小时不崩溃** | 无 OOM、无 NCCL 抖动，Vibe Coding 长跑全程一次都没断过 |
| GPU 温度 | **约 70°C**（跑 Agent 过程中） | 离热墙（90°C+）余量充足，风扇/功耗平稳安静 |
| 上手成本 | Node 脚本 + 面板几分钟起 | 服务本就常驻，直接当本地推理后端用 |

> 审美结论没有歧义：**两台 DGX Spark 刚好能拿捏 deepseek v4 flash 0731**，
> 单流 60–70 tok/s 的体验足以覆盖日常 vibe coding；花的力气主要在首次部署上，日常使用零维护。

配套的监控面板（同一套 vibe coding 产物，独立仓库 [`dgx-spark-2-deepseek-flash-dashboard`](https://github.com/maliubiao/dgx-spark-2-deepseek-flash-dashboard)）
实时展示 GPU 利用率/温度/功耗、decode 吞吐、投机解码接受率、KV cache 与 prefix 命中率，
方便随时确认“机器是否在稳定工作”。下面三张为面板实时截图：

![面板截图 1——实时概览](perf/vibe-panel-1.png)

![面板截图 2——GPU/主机与吞吐](perf/vibe-panel-2.png)

![面板截图 3——性能详情](perf/vibe-panel-3.png)

> 截图来自实际运行中的环境；各页详情与重新生成方法见监控面板仓库的 README/PREVIEWS。

## 8.7 长上下文验证（Issue #22 修复，2026-08-11 实测）

> 94baabf 起，start 脚本自动应用 Issue #22 hotfix：`nvfp4_ds_mla` 在 600K+ 上下文时不再走
> 慢速 bf16 kernel（~1.0 tok/s），改走快速 fp8 kernel。验证方法：`/tokenize` 校准 prompt 到目标
> 长度后流式请求，测 TTFT 与 decode tok/s（执行 `./deploy.sh --perf on|off [目标tokens]`）；性能测试会从 `config.yaml` 的 `head.management_ip` 访问 API，因此可在 Mac 上执行。

| 测试 | prompt tokens | TTFT | prefill tok/s | decode tok/s |
|---|---|---|---|---|
| 基线（短上下文） | 8,299 | 9.1 s | 908 | **71.6** |
| 长上下文 #1 | 620,107 | 502.9 s（冷启动） | 1,233 | **73.0** |
| 长上下文 #2 | 780,109 | 201.8 s（热态） | 3,867 | **70.2** |

**结论**：>600K 上下文 decode 稳定在 70–73 tok/s，与短上下文基线一致，确认修复有效
（修复前同场景 ~1.0 tok/s，16 倍减速）。首次请求 TTFT 偏长是 FlashInfer autotune 缓存加载
+ GPU 预热，后续即热态。
