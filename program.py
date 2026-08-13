#!/usr/bin/env python3
# =============================================================================
# program.py —— DeepSeek-V4-Flash 双机集群唯一实现（命令 → 函数分发）。
#
# 两种用法：
#   A. 管理与部署（head 上执行，经 deploy.sh 转发）：
#        install / uninstall / restart / live_check / chat_verify / doctor / help
#   B. 部署后运行支撑（双机本机，systemd 单元 ExecStart 直调）：
#        start / stop / ensure / status      —— 按本机 hostname 识别 head/worker 角色
#   另含工具命令 load-config / gen-env（install 内部复用 + 调试导出）；
#   chat_verify 为长上下文解码性能验证（原 scripts/longctx-verify.py，Issue #22）。
#
# 参数 SSOT：config.yaml（common/head/worker 分类）。install 把本文件与 config.yaml
#            部署到双机 /etc/dspark-vllm/；systemd 单元以绝对路径调用。
# 用法：
#   python3 program.py [--config <config.yaml>] <命令> [参数...]
#   --config 缺省 /etc/dspark-vllm/config.yaml（systemd 本机调用时）。
#
# 依赖 pyyaml；缺失时打印安装提示并以非 0 退出。
# =============================================================================
import argparse
import datetime
import hashlib
import json
import os
import pwd
import shlex
import socket
import subprocess
import sys
import time


# ---- 通用辅助（Fail-Fast） ----

class LogLevel:
    """日志级别常量（logtask 的 level 参数取值），避免字符串拼错。"""
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


def dotask(cmd, args=None, check=False, capture_output=True, text=True, shell=False, **kwargs):
    """以接近原生 shell 的字符串形式执行命令，无需拆成 argv 列表。

    cmd 为命令字符串（内部用 shlex 拆分为 argv）；args 追加需原样透传的尾部参数
    （含空格/引号/管道，如 ssh 的远端命令串）。默认捕获输出并解码为文本，
    返回 CompletedProcess。一次性命令直接 dotask(...) 调用即可，不必再包一层。
    shell=True 时 cmd 整体交由 /bin/sh（支持管道/重定向），此时忽略 args。
    """
    argv = cmd if shell else shlex.split(cmd) + list(args or [])
    # subprocess.run 禁止 capture_output 与 stdout/stderr 同时传入。
    if "stdout" in kwargs or "stderr" in kwargs:
        capture_output = False
    return subprocess.run(argv, check=check, capture_output=capture_output, text=text,
                          shell=shell, **kwargs)


def logtask(action, desc="", level=LogLevel.INFO):
    """统一日志：时间戳 + level + action[: desc]；ERROR 打印后退出应用（快速失败）。

    level 取 LogLevel.INFO / WARN / ERROR。过程日志统一走本函数；数据输出（.env 内容、
    load-config 导出行、chat_verify JSON 报告、doctor 检查清单）不经过本函数，
    保持纯 stdout 供管道捕获。ERROR 调用后进程以非 0 退出。
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {action}" + (f" — {desc}" if desc else "")
    # 过程日志必须与 gen-env/load-config/chat_verify 等机器可读 stdout 分离。
    print(line, file=sys.stderr, flush=True)
    if level == LogLevel.ERROR:
        sys.exit(1)


def parser_yaml(path):
    """读取 config.yaml；缺文件 / 缺 pyyaml 时快速失败。"""
    if not os.path.isfile(path):
        logtask(f"缺少 {path}（config.yaml 为参数 SSOT，install 时部署到双机 /etc/dspark-vllm/）", level=LogLevel.ERROR)
    try:
        import yaml
    except ImportError:
        logtask("pyyaml 缺失", "请先安装（head/worker 各一次）：python3 -m pip install pyyaml 或 sudo apt install -y python3-yaml",
                level=LogLevel.ERROR)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parser_constants(cfg):
    """从 config 派生集群常量（对应原 deploy.sh 顶部常量块）。"""
    common, head, worker = cfg["common"], cfg["head"], cfg["worker"]
    repo = common["repo"]
    runtime_repo = common["runtime_repo"]
    return {
        "user": common["user"],
        "repo": repo,
        "runtime_repo": runtime_repo,
        "project": common["project"],
        "container": common["container"],
        "model_lib": common["model_lib"],
        "model_links": common["model_links"],
        "default_model": common["default_model"],
        "image": common["vllm_image"],
        "image_tar": common.get("image_tar", ""),
        "api_url": common["api_url"],
        "api_key": common.get("api_key", ""),
        "env_file": f"{runtime_repo}/.env.dspark",
        "compose_file": f"{runtime_repo}/docker-compose.dspark.yml",
        "head_hostname": head["hostname"],
        "head_fabric_ip": head["fabric_ip"],
        "worker_hostname": worker["hostname"],
        "worker_ssh": worker["ssh"],
        "config_remote": "/etc/dspark-vllm/config.yaml",
        "program_remote": "/etc/dspark-vllm/program.py",
        "template_remote": "/etc/dspark-vllm/dspark.env.json",
    }


def ssh_task(ssh_target, command, check=False):
    """经 SSH 在远端执行命令（BatchMode 免密，命令整体作为单参传递）；返回 CompletedProcess。"""
    return dotask("ssh -o BatchMode=yes -o ConnectTimeout=10", [ssh_target, command], check=check)


def scp_task(ssh_target, paths, desc="/tmp/"):
    """分发文件到 worker（保留文件名）；远端目标目录缺省 /tmp/，可传 desc 覆盖。"""
    dotask("scp -q", paths + [f"{ssh_target}:{desc}"], check=True)


def sudo_install(src, dst, mode):
    """head 本地 sudo install（保留模式位）。"""
    dotask("sudo install", ["-m", mode, src, dst], check=True)


def node_role(consts):
    """按本机 hostname 识别 head/worker；不匹配则快速失败。"""
    hostname = socket.gethostname()
    if hostname == consts["head_hostname"]:
        return "head"
    if hostname == consts["worker_hostname"]:
        return "worker"
    logtask(f"本机 hostname({hostname}) 未匹配 config 的 head({consts['head_hostname']})/worker({consts['worker_hostname']})", level=LogLevel.ERROR)


def drop_privilege(consts, argv):
    """systemd 以 root 启动时降权到业务用户后重跑（对应原 dspark-vllm.sh 的 runuser）。"""
    current = pwd.getpwuid(os.geteuid()).pw_name
    if current == consts["user"]:
        return
    logtask("drop_privilege", f"降权到业务用户 {consts['user']}")
    os.execvp("runuser", ["runuser", "-u", consts["user"], "--", sys.executable] + argv)


def api_healthy(consts):
    """vLLM API 健康探测（curl common.api_url）。"""
    try:
        dotask("curl -fsS --max-time 5", [consts["api_url"]],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


def wait_for_api(consts, attempts=240, sec=5, timeout=None):
    """轮询等待 API 就绪（冷启动最长约 20 分钟）；超时返回 False。"""
    deadline = time.monotonic() + timeout if timeout is not None else None
    description = f"最长 {timeout}s" if timeout is not None else f"最长 {attempts}x{sec}s"
    logtask("wait_for_api", f"等待 vLLM API（{description}）")
    for _ in range(attempts):
        if api_healthy(consts):
            logtask("wait_for_api", "API 已健康")
            return True
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(sec, remaining))
        else:
            time.sleep(sec)
    logtask("wait_for_api", "超时，将由 systemd 重试", level=LogLevel.WARN)
    return False


def container_names_local():
    """本机全部容器名（含已停止）。"""
    r = dotask("docker ps -a --format '{{.Names}}'")
    return set(r.stdout.split())


def container_exists_local(consts):
    return consts["container"] in container_names_local()


def container_running_local(consts):
    """本机运行中的容器名（与原始 ensure 脚本的 docker ps 语义一致）。"""
    r = dotask("docker ps --format '{{.Names}}'")
    return consts["container"] in r.stdout.split()


def container_exists_remote(consts):
    r = ssh_task(consts["worker_ssh"],
                f"docker ps -a --format '{{{{.Names}}}}' 2>/dev/null | grep -qx {shlex.quote(consts['container'])}")
    return r.returncode == 0


def container_running_remote(consts):
    """查询远端运行中的容器；停止容器不能满足恢复条件。"""
    r = ssh_task(consts["worker_ssh"],
                f"docker ps --format '{{{{.Names}}}}' 2>/dev/null | grep -qx {shlex.quote(consts['container'])}")
    return r.returncode == 0


def runtime_repo_files(consts):
    """返回 MiaAI DSpark 子项目要求的启动、停止和 Compose 文件。"""
    runtime_repo = consts["runtime_repo"]
    return {
        "start": f"{runtime_repo}/start-deepseek-v4-flash-dspark.sh",
        "stop": f"{runtime_repo}/stop-deepseek-v4-flash-dspark.sh",
        "compose": consts["compose_file"],
    }


def runtime_source_drift(consts):
    """检查仓库内 dspark runtime 与实际执行目录是否一致，只告警不自动覆盖。"""
    source_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dspark")
    runtime_files = runtime_repo_files(consts)
    source_files = {
        "start": os.path.join(source_root, os.path.basename(runtime_files["start"])),
        "compose": os.path.join(source_root, os.path.basename(runtime_files["compose"])),
    }

    def digest(path):
        try:
            checksum = hashlib.sha256()
            with open(path, "rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    checksum.update(block)
            return checksum.hexdigest()
        except OSError:
            return None

    for key, source_path in source_files.items():
        source_hash = digest(source_path)
        runtime_hash = digest(runtime_files[key])
        if source_hash and runtime_hash and source_hash != runtime_hash:
            logtask("runtime_drift", f"本地 dspark/{os.path.basename(source_path)} 与实际 runtime {runtime_files[key]} 内容不同；install 不会自动同步 dspark/，将执行 runtime 版本", level=LogLevel.WARN)
        elif source_hash is None:
            logtask("runtime_drift", f"本地 runtime 源文件不存在，无法比较: {source_path}", level=LogLevel.WARN)


def model_required_files(model_dir):
    """DOWNLOADS.md 第 7 项要求的模型关键文件与 48 个权重分片。"""
    required = [
        "config.json",
        "configuration.json",
        "generation_config.json",
        "model.safetensors.index.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "encoding/encoding_dsv4.py",
    ]
    required.extend(f"model-{index:05d}-of-00048.safetensors" for index in range(1, 49))
    return [os.path.join(model_dir, relative) for relative in required]


def validate_runtime_repo(consts, worker=None):
    """部署前确认 head/worker 的 MiaAI runtime repo 均已就位。"""
    files = runtime_repo_files(consts)
    missing = [path for key, path in files.items()
               if (key == "compose" and not os.path.isfile(path)) or
               (key != "compose" and not os.access(path, os.X_OK))]
    if missing:
        logtask(
            "缺少 MiaAI 部署运行时文件",
            f"请按 docs/DOWNLOADS.md 第 9 项下载并固定 a4ce87a2f47f1be8fe64c297a0cf33a9a5e509aa，再将仓库放到 {consts['runtime_repo']}；模型目录 {consts['model_lib']} 只存模型文件。缺少: {missing}",
            level=LogLevel.ERROR,
        )
    if worker:
        labels = {"compose": "docker-compose.dspark.yml",
                  "start": "start-deepseek-v4-flash-dspark.sh",
                  "stop": "stop-deepseek-v4-flash-dspark.sh"}
        checks = " && ".join(
            f"[ {'-f' if key == 'compose' else '-x'} {shlex.quote(path)} ]"
            for key, path in files.items()
        )
        if ssh_task(worker, checks).returncode != 0:
            remote_missing = []
            for key, path in files.items():
                if ssh_task(worker, f"test {'-f' if key == 'compose' else '-x'} {shlex.quote(path)}").returncode != 0:
                    remote_missing.append(labels[key])
            logtask(
                "WORKER 缺少 MiaAI 部署运行时文件",
                f"请将本机 {consts['runtime_repo']} 同步到 worker 的相同路径 {consts['runtime_repo']}；缺少: {remote_missing}",
                level=LogLevel.ERROR,
            )


def compose_up(consts, env_override, service=None):
    """docker compose 拉起容器（对应原 dspark-vllm.sh 的 compose 段）。"""
    env = dict(os.environ)
    env.pop("NODE_RANK", None)
    env.pop("HEADLESS", None)
    env.update(env_override)
    env["COMPOSE_DISABLE_ENV_FILE"] = "1"
    dotask("docker compose",
           ["-p", consts["project"], "--env-file", consts["env_file"],
            "-f", consts["compose_file"], "up", "-d"] + ([service] if service else []),
           cwd=consts["runtime_repo"], env=env, check=True)


def recovery_env(consts):
    """复现 main start wrapper 在 head 恢复路径显式注入的 Compose 环境。"""
    values = {}
    try:
        with open(consts["env_file"], encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key and key.replace("_", "").isalnum():
                    values[key] = value
    except OSError:
        return {}
    selected = (
        "WORKER_HOST", "MASTER_ADDR", "MASTER_PORT", "NCCL_IB_HCA",
        "NCCL_SOCKET_IFNAME", "NCCL_IB_GID_INDEX", "VLLM_HOST", "VLLM_PORT",
        "VLLM_HOST_IP",
    )
    result = {key: values[key] for key in selected if key in values}
    result.setdefault("VLLM_HOST", "127.0.0.1")
    result.setdefault("VLLM_PORT", "8888")
    if result.get("MASTER_ADDR"):
        result.setdefault("VLLM_HOST_IP", result["MASTER_ADDR"])
    return result


# ---- 生产 .env 生成（main 分支最终参数全集，60+ 键） ----

def load_env_template():
    """读取 .env 参数模板 dspark.env.json（固定键值 + null 占位的变化键）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dspark.env.json")
    if not os.path.isfile(path):
        logtask(f"缺少 .env 参数模板 {path}（dspark.env.json 随仓库提供，install 会同步到双机）", level=LogLevel.ERROR)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def gen_env(cfg, model_dir, template=None):
    """从 dspark.env.json 模板 + config.yaml + 模型派生完整 .env.dspark。

    模板含固定参数（vLLM/b12x/NCCL 调优等）；null 占位的变化键（网络/模型/镜像）
    在此从 config 派生覆盖；模板中残留 null 即快速失败（Fail-Fast）。
    """
    common, head, worker = cfg["common"], cfg["head"], cfg["worker"]
    short = os.path.basename(model_dir.rstrip("/"))
    served = short.lower()
    if template is None:
        template = load_env_template()
    d = dict(template)
    d.update({
        # ---- HTTP 鉴权（config 派生；空串 = 不启用） ----
        "VLLM_API_KEY": common.get("api_key", ""),
        # ---- 集群（config 派生） ----
        "WORKER_HOST": worker["management_ip"],
        "MASTER_ADDR": head["fabric_ip"],
        "MASTER_PORT": str(common["master_port"]),
        # ---- head 的 RoCE ----
        "NCCL_IB_HCA": head["hca"],
        "NCCL_SOCKET_IFNAME": head["ifname"],
        "TP_SOCKET_IFNAME": head["ifname"],
        "GLOO_SOCKET_IFNAME": head["ifname"],
        # ---- worker 的 RoCE ----
        "WORKER_NCCL_IB_HCA": worker["hca"],
        "WORKER_NCCL_SOCKET_IFNAME": worker["ifname"],
        "WORKER_TP_SOCKET_IFNAME": worker["ifname"],
        "WORKER_GLOO_SOCKET_IFNAME": worker["ifname"],
        # ---- 模型缓存 ----
        "HF_CACHE": common["model_lib"],
        "DSPARK_MODEL_ID": model_dir,
        "DSPARK_MODEL_OFFICIAL": "/cache/huggingface/models/%s" % short,
        "DSPARK_ENCODING_FILE": "/cache/huggingface/models/%s/encoding/encoding_dsv4.py" % short,
        "SERVED_MODEL_NAME": served,
        "VLLM_HOST_IP": head["fabric_ip"],
        "WORKER_VLLM_HOST_IP": worker["fabric_ip"],
        # ---- 运行时镜像 ----
        "DSPARK_VLLM_IMAGE": common["vllm_image"],
    })
    missing = [key for key, val in d.items() if val is None and not key.startswith("_")]
    if missing:
        logtask(f".env 模板存在未填充的键: {missing}", level=LogLevel.ERROR)
    lines = ["# .env.dspark —— 由 program.py gen_env 从 dspark.env.json 模板 + config.yaml 派生，勿手工编辑"]
    lines += ["%s=%s" % (key, val) for key, val in d.items() if not key.startswith("_")]
    return "\n".join(lines) + "\n"


# ---- operation 命令（双机本机；systemd 直调） ----

def cmd_start(consts, cfg, rest):
    if node_role(consts) != "head":
        logtask(f"start 只能在 head({consts['head_hostname']}) 上执行", level=LogLevel.ERROR)
    logtask("start", f"启动集群（worker 先起，head 后起；冷启动最长约 20 分钟）；runtime_repo={consts['runtime_repo']} api={consts['api_url']}")
    files = runtime_repo_files(consts)
    start_script = files["start"]
    if not os.access(start_script, os.X_OK):
        logtask(f"缺少可执行的 {start_script}", level=LogLevel.ERROR)
    if api_healthy(consts):
        logtask("start", "API 已健康，跳过")
        return 0
    # head 容器缺失但 worker 已在：compose 拉起 head 并等待（上游 start 在 worker 已在时拒绝执行）
    if not container_exists_local(consts) and container_running_remote(consts):
        logtask("start", "worker 容器在、head 缺失：compose 拉起 head")
        env_override = recovery_env(consts)
        env_override.update({"NODE_RANK": "0", "HEADLESS": ""})
        compose_up(consts, env_override)
        return 0 if wait_for_api(consts) else 1
    logtask("start", "启动 DSpark vLLM 服务")
    try:
        # 上游脚本包含 GID/SSH/Compose 的现场诊断；必须透传 stdout/stderr，
        # 否则失败时只剩一个无上下文的 CalledProcessError 退出码。
        dotask(start_script, cwd=consts["runtime_repo"], stdout=None, stderr=None, check=True)
    except subprocess.CalledProcessError as exc:
        logtask("start", f"上游 DSpark 启动脚本失败（exit={exc.returncode}）：{start_script}", level=LogLevel.ERROR)
    return 0


def cmd_stop(consts, cfg, rest):
    if node_role(consts) != "head":
        logtask(f"stop 只能在 head({consts['head_hostname']}) 上执行", level=LogLevel.ERROR)
    logtask("stop", f"停止集群（head 先停，worker 后停；幂等）；runtime_repo={consts['runtime_repo']}")
    stop_script = runtime_repo_files(consts)["stop"]
    if not os.access(stop_script, os.X_OK):
        logtask(f"缺少可执行的 {stop_script}", level=LogLevel.ERROR)
    # install 在 stop 之后才生成 runtime .env.dspark；旧容器存在但该文件
    # 尚未生成时，仍必须能从 config.yaml 提供 stop 脚本所需的 worker 地址。
    stop_env = os.environ.copy()
    stop_env["WORKER_HOST"] = cfg["worker"]["management_ip"]
    try:
        dotask(stop_script, cwd=consts["runtime_repo"], env=stop_env,
               stdout=None, stderr=None, check=True)
    except subprocess.CalledProcessError as exc:
        logtask("stop", f"上游 DSpark 停止脚本失败（exit={exc.returncode}）：{stop_script}", level=LogLevel.ERROR)
    # 兜底：worker 容器若仍存活
    if container_running_remote(consts):
        logtask("stop", "worker 容器仍在，强制停止")
        ssh_task(consts["worker_ssh"],
                f"cd {shlex.quote(consts['runtime_repo'])} && "
                f"docker compose -p {shlex.quote(consts['project'])} --env-file {shlex.quote(consts['env_file'])} -f {shlex.quote(consts['compose_file'])} stop 2>/dev/null || "
                f"docker stop {shlex.quote(consts['container'])} 2>/dev/null || true")
    logtask("stop", "集群已停止")
    return 0


def cmd_ensure(consts, cfg, rest):
    if node_role(consts) != "worker":
        logtask(f"ensure 只能在 worker({consts['worker_hostname']}) 上执行", level=LogLevel.ERROR)
    logtask("ensure", f"worker 容器守护（幂等，systemd 开机调用）；container={consts['container']} runtime_repo={consts['runtime_repo']}")
    if container_running_local(consts):
        logtask("ensure", f"worker 容器 {consts['container']} 已在运行")
        return 0
    if not os.path.isfile(consts["compose_file"]) or not os.path.isfile(consts["env_file"]):
        logtask(f"worker 缺 compose/env: {consts['runtime_repo']}", level=LogLevel.ERROR)
    logtask("ensure", f"启动 worker 容器 {consts['container']}")
    compose_up(consts, {"NODE_RANK": "1", "HEADLESS": "1", "VLLM_HOST_IP": ""}, service="vllm-dspark")
    return 0


def cmd_status(consts, cfg, rest):
    logtask("status", f"双机容器与 API 状态；worker={consts['worker_ssh']} api={consts['api_url']}")
    if container_running_local(consts):
        head_state = "运行中"
    elif container_exists_local(consts):
        head_state = "已停止"
    else:
        head_state = "不存在"
    logtask("status", f"head({socket.gethostname()}): {consts['container']} {head_state}")
    r = ssh_task(consts["worker_ssh"],
                f"docker ps -a --format '{{{{.Names}}}}\t{{{{.Status}}}}' 2>/dev/null | grep {shlex.quote(consts['container'])} || echo '无 worker 容器'")
    logtask("status", f"worker({consts['worker_ssh']}): {r.stdout.strip() or '无 worker 容器'}")
    if api_healthy(consts):
        logtask("status", f"API 健康: {consts['api_url']}")
    else:
        logtask("status", "API 未就绪")
    return 0


def cmd_display(consts, cfg, args):
    """设置 head/worker 的 systemd 默认启动模式，不切换当前运行 target。"""
    if node_role(consts) != "head":
        logtask(f"display 只能在 head({consts['head_hostname']}) 上执行", level=LogLevel.ERROR)
    target = "graphical.target" if args.mode == "on" else "multi-user.target"
    mode_desc = "图形界面" if args.mode == "on" else "终端"
    logtask("display", f"设置双机默认启动模式为{mode_desc}（{target}）；仅重启后生效，不中断当前服务")
    dotask("sudo systemctl set-default", [target], check=True)
    ssh_task(consts["worker_ssh"], f"sudo systemctl set-default {shlex.quote(target)}", check=True)
    logtask("display", f"head({socket.gethostname()}) 与 worker({consts['worker_ssh']}) 已设置为 {target}")
    return 0


# ---- 编排命令（head 上，经 deploy.sh） ----

def deploy_ops(consts, cfg):
    """部署 program.py + dspark.env.json + config.yaml 到双机 /etc/dspark-vllm/（幂等）。"""
    program_local = os.path.abspath(__file__)
    template_local = os.path.join(os.path.dirname(program_local), "dspark.env.json")
    config_local = consts["config_local"]
    logtask("deploy_ops", "部署 program.py / dspark.env.json / config.yaml 到双机 /etc/dspark-vllm/")
    if not os.path.isfile(program_local):
        logtask(f"缺少 {program_local}（program.py 随仓库提供）", level=LogLevel.ERROR)
    if not os.path.isfile(template_local):
        logtask(f"缺少 .env 参数模板 {template_local}（dspark.env.json 随仓库提供）", level=LogLevel.ERROR)
    dotask("sudo install -d -m 0755 /etc/dspark-vllm", check=True)
    sudo_install(program_local, consts["program_remote"], "0755")
    sudo_install(template_local, consts["template_remote"], "0644")
    sudo_install(config_local, consts["config_remote"], "0644")
    scp_task(consts["worker_ssh"], [program_local, template_local, config_local])
    p_name, t_name, c_name = (os.path.basename(program_local), os.path.basename(template_local),
                              os.path.basename(config_local))
    ssh_task(consts["worker_ssh"],
            f"sudo install -d -m 0755 /etc/dspark-vllm && "
            f"sudo install -m 0755 /tmp/{shlex.quote(p_name)} {consts['program_remote']} && "
            f"sudo install -m 0644 /tmp/{shlex.quote(t_name)} {consts['template_remote']} && "
            f"sudo install -m 0644 /tmp/{shlex.quote(c_name)} {consts['config_remote']} && "
            f"rm -f /tmp/{shlex.quote(p_name)} /tmp/{shlex.quote(t_name)} /tmp/{shlex.quote(c_name)}",
             check=True)


def deploy_units(consts):
    """安装 systemd 单元到双机 /etc/systemd/system/（head 单元 / worker 单元）。"""
    systemd_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "systemd")
    head_unit = os.path.join(systemd_dir, "dspark-vllm-head.service")
    worker_unit = os.path.join(systemd_dir, "dspark-vllm-worker.service")
    if not os.path.isfile(head_unit) or not os.path.isfile(worker_unit):
        logtask(f"缺少 systemd 单元（{systemd_dir}）", level=LogLevel.ERROR)
    logtask("deploy_units", "安装 systemd 单元到双机 /etc/systemd/system/")
    sudo_install(head_unit, "/etc/systemd/system/dspark-vllm-head.service", "0644")
    dotask("sudo systemctl daemon-reload", check=True)
    dotask("sudo systemctl enable dspark-vllm-head.service", check=True)
    scp_task(consts["worker_ssh"], [worker_unit])
    ssh_task(consts["worker_ssh"],
            "sudo install -m 0644 /tmp/dspark-vllm-worker.service /etc/systemd/system/dspark-vllm-worker.service && "
            "rm -f /tmp/dspark-vllm-worker.service && sudo systemctl daemon-reload && "
            "sudo systemctl enable dspark-vllm-worker.service",
             check=True)


def resolve_model(consts, model_arg):
    """解析模型绝对路径：/opt/models/<org>/<model> 或 <org>/<model> 自动补前缀；缺省用 common.default_model。"""
    root = os.path.abspath(consts["model_lib"])
    candidate = model_arg or consts["default_model"]
    if not candidate:
        logtask("未配置模型路径", level=LogLevel.ERROR)
    if not os.path.isabs(candidate):
        candidate = os.path.join(root, candidate)
    model_dir = os.path.abspath(candidate.rstrip("/"))
    try:
        inside_root = os.path.commonpath([root, model_dir]) == root
    except ValueError:
        inside_root = False
    if not inside_root or model_dir == root:
        logtask(f"模型路径需位于 {root} 下: {candidate}", level=LogLevel.ERROR)
    return model_dir


def installed_model_name(consts):
    """读取 install 生成的服务名，避免切换模型后验证仍请求默认模型。"""
    try:
        with open(consts["env_file"], encoding="utf-8") as f:
            for line in f:
                if line.startswith("SERVED_MODEL_NAME="):
                    value = line.partition("=")[2].strip()
                    if value:
                        return value
    except OSError:
        pass
    return os.path.basename(consts["default_model"].rstrip("/")).lower()


def link_model(consts, model_dir):
    """双机注册模型 symlink：model_links/<short> -> 宿主 <model_lib>/<org>/<model>。

    容器内 /cache/huggingface/models/<short> 按单层 short 引用（对应 main 分支
    .env.dspark 模板 DSPARK_MODEL_OFFICIAL 约定），宿主侧以 model_links/<short> 单层
    symlink 指向真实的 <org>/<model> 模型目录（如 /opt/models/deepseek-ai/DeepSeek-V4-Flash-0731）。
    """
    short = os.path.basename(model_dir.rstrip("/"))
    dst = f"{consts['model_links']}/{short}"
    # Compose 将整个 model_lib 挂载到 /cache/huggingface；绝对宿主 symlink
    # 目标会在容器内仍指向 /opt/models，成为断链，必须使用相对目标。
    symlink_target = os.path.relpath(model_dir, os.path.dirname(dst))
    logtask("link_model", f"注册模型 {model_dir} -> {dst}（双机）")
    if not os.path.isfile(f"{model_dir}/config.json"):
        logtask(f"{model_dir}/config.json 不存在（检查模型目录）", level=LogLevel.ERROR)
    if not os.path.isfile(f"{model_dir}/encoding/encoding_dsv4.py"):
        logtask("link_model", f"{model_dir}/encoding/encoding_dsv4.py 不存在（变体若无 DSpark 编码将无法加载）", level=LogLevel.WARN)
    logtask("link_model", f"head {socket.gethostname()}: {dst} -> {model_dir}")
    if os.path.lexists(dst) and not os.path.islink(dst):
        logtask(f"{dst} 已存在且不是 symlink，请人工确认", level=LogLevel.ERROR)
    dotask("sudo mkdir -p", [consts["model_links"]], check=True)
    dotask("sudo ln -sfn", [symlink_target, dst], check=True)
    logtask("link_model", f"worker {consts['worker_ssh']}: {dst} -> {model_dir}")
    ssh_task(consts["worker_ssh"],
            f"set -e; "
            f"if [ ! -f {shlex.quote(model_dir)}/config.json ]; then echo '  [FAIL] config.json 不存在' >&2; exit 1; fi; "
            f"if [ -e {shlex.quote(dst)} ] && [ ! -L {shlex.quote(dst)} ]; then echo '  [FAIL] {dst} 已存在且不是 symlink' >&2; exit 1; fi; "
            f"sudo mkdir -p {shlex.quote(consts['model_links'])} && sudo ln -sfn {shlex.quote(symlink_target)} {shlex.quote(dst)}",
             check=True)
    logtask("link_model", f"双机 {dst} 已指向 {model_dir}")


def install_env(consts, cfg, model_dir):
    """安装生产 .env：gen_env 生成完整参数集 → 写 head $REPO/.env.dspark → 同步 worker。"""
    content = gen_env(cfg, model_dir)
    short = os.path.basename(model_dir.rstrip("/"))
    os.makedirs(os.path.dirname(consts["env_file"]), exist_ok=True)
    with open(consts["env_file"], "w", encoding="utf-8") as f:
        f.write(content)
    logtask("install_env", f"{consts['env_file']} 已生成（模型: {short}）")
    logtask("install_env", "同步 .env.dspark 到 worker")
    scp_task(consts["worker_ssh"], [consts["env_file"]])
    remote_env = shlex.quote(consts["env_file"])
    ssh_task(consts["worker_ssh"],
             f"sudo install -m 0644 /tmp/.env.dspark {remote_env} && rm -f /tmp/.env.dspark",
             check=True)


def activate_units(consts):
    """让 install 后的 systemd 单元进入 active 状态，确保后续 stop/Restart 生效。"""
    logtask("activate_units", "启动 worker/head systemd 单元并保持自恢复状态")
    ssh_task(consts["worker_ssh"], "sudo systemctl start dspark-vllm-worker.service", check=True)
    dotask("sudo systemctl start dspark-vllm-head.service", check=True)


def cmd_install(consts, cfg, args):
    model_arg = args.model
    logtask("install", f"安装/覆盖安装：部署 program.py+config 到双机、装 systemd 单元、注册模型、生成生产 .env、启动并等待 API；model={model_arg or consts['default_model']} config={consts['config_local']}")
    model_dir = resolve_model(consts, model_arg)
    if not os.path.isfile(f"{model_dir}/config.json"):
        logtask(f"{model_dir}/config.json 不存在（检查模型目录）", level=LogLevel.ERROR)
    validate_runtime_repo(consts, consts["worker_ssh"])
    runtime_source_drift(consts)
    deploy_ops(consts, cfg)
    deploy_units(consts)
    if container_exists_local(consts) or container_exists_remote(consts):
        logtask("install", "检测到现存容器，先停止")
        cmd_stop(consts, cfg, [])
    else:
        logtask("install", "未检测到现存容器，直接安装")
    short = os.path.basename(model_dir.rstrip("/"))
    logtask("install", f"模型: {model_dir} (served: {short.lower()})")
    link_model(consts, model_dir)
    install_env(consts, cfg, model_dir)
    cmd_start(consts, cfg, [])
    if not wait_for_api(consts):
        logtask("install 完成但 API 未就绪", level=LogLevel.ERROR)
    activate_units(consts)
    logtask("install", "完成")
    return 0


def cmd_uninstall(consts, cfg, rest):
    logtask("uninstall", f"清理部署：停容器、移除双机模型注册 symlink、禁用 systemd 自启；config={consts['config_local']}")
    cmd_stop(consts, cfg, [])
    logtask("uninstall", f"移除模型注册 {consts['model_links']}/*（双机，仅 symlink）")
    if os.path.isdir(consts["model_links"]):
        for name in os.listdir(consts["model_links"]):
            link = os.path.join(consts["model_links"], name)
            if os.path.islink(link):
                logtask("uninstall", f"rm {link}")
                dotask("sudo rm -f", [link])
    ssh_task(consts["worker_ssh"], f"sudo find {shlex.quote(consts['model_links'])} -maxdepth 1 -type l -delete 2>/dev/null || true")
    logtask("uninstall", "禁用 systemd 自启")
    dotask("sudo systemctl disable --now dspark-vllm-head.service",
           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ssh_task(consts["worker_ssh"], "sudo systemctl disable --now dspark-vllm-worker.service 2>/dev/null || true")
    logtask("uninstall", "完成")
    return 0


def cmd_restart(consts, cfg, rest):
    logtask("restart", f"重启集群（= stop + start，head 上）；config={consts['config_local']}")
    cmd_stop(consts, cfg, [])
    return cmd_start(consts, cfg, [])


def cmd_live_check(consts, cfg, args):
    wait = args.wait or 0
    logtask("live_check", f"API 健康检查；api={consts['api_url']} wait={wait or '一次'}")
    if wait > 0:
        return 0 if wait_for_api(consts, attempts=max(1, wait), sec=1, timeout=wait) else 1
    if api_healthy(consts):
        logtask("live_check", f"OK: {consts['api_url']}")
        return 0
    logtask("live_check", f"FAIL: {consts['api_url']}", level=LogLevel.ERROR)


def cmd_chat_verify(consts, cfg, args):
    """长上下文解码性能验证（原 scripts/longctx-verify.py，Issue #22）。

    构造 >=target tokens 的长 prompt 流式测速，按 decode tok/s(>=8) 判定
    是否走快速 fp8 路径。BASE/MODEL 从 config 派生（api_url / default_model）。
    """
    import json
    import urllib.request

    base = consts["api_url"][: consts["api_url"].rfind("/models")]
    model = installed_model_name(consts)
    target = args.target
    api_key = consts["api_key"]
    if target <= 0:
        logtask("chat_verify 的目标 tokens 必须大于 0", level=LogLevel.ERROR)
    logtask("chat_verify", f"长上下文解码性能验证（Issue #22）：构造长 prompt 流式测速，判定 fp8/bf16 路径；model={model} base={base} target={target} auth={'on' if api_key else 'off'}")

    def http_headers(api_key):
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def request_json(url, body, timeout=3600):
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers=http_headers(api_key))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def tokenize(prompt):
        return request_json(base.replace("/v1", "") + "/tokenize",
                            {"model": model, "prompt": prompt})["count"]

    # ---- 构造到目标长度的长 prompt ----
    unit = "benchmark context datum "
    text = "unique request longctx-verify " + unit * max(1, target // 3)
    while True:
        count = tokenize(text)
        logtask("chat_verify", f"prompt tokens so far: {count}")
        if count >= target:
            break
        text += unit * max(1, (target - count) // 3)
    logtask("chat_verify", f"final prompt tokens: {count}")

    # ---- 流式请求 ----
    body = {"model": model,
            "messages": [{"role": "user", "content": text + "\nReply with exactly: VERIFIED"}],
            "max_tokens": 64, "temperature": 0.2,
            "stream": True, "stream_options": {"include_usage": True}}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                 headers=http_headers(api_key))
    started = time.perf_counter()
    first = None
    usage = None
    with urllib.request.urlopen(req, timeout=3600) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            ev = json.loads(line[6:])
            ch = ev.get("choices") or []
            d = ch[0].get("delta", {}) if ch else {}
            if first is None and (d.get("content") or d.get("reasoning") or d.get("reasoning_content")):
                first = time.perf_counter()
                logtask("chat_verify", f"TTFT: {first - started:.2f}s")
            if ev.get("usage"):
                usage = ev["usage"]
    finished = time.perf_counter()
    pt = usage["prompt_tokens"] if usage else count
    ot = usage["completion_tokens"] if usage else 0
    decode_s = finished - (first or started)
    print(json.dumps({
        "prompt_tokens": pt,
        "completion_tokens": ot,
        "ttft_s": round((first or finished) - started, 2),
        "prefill_tok_s": round(pt / max(0.001, (first or finished) - started), 1),
        "decode_s": round(decode_s, 2),
        "output_tok_s": round(ot / max(0.001, decode_s), 1),
        "verdict": "FIX EFFECTIVE (fast fp8 path)" if ot / max(0.001, decode_s) >= 8 else "STILL SLOW (bf16 path)"
    }, indent=2))
    return 0


# ---- doctor 命令（head 上） ----

def doctor_check_node(consts, worker, ok, bad):
    """双机 GPU/CUDA/Docker/sudo 探测（head 本地 / worker 走 SSH）。"""
    probe = """printf "gpu=%s cuda=%s docker=%s sudo_nopasswd=%s" \
"$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)" \
"$(ls -d /usr/local/cuda*/bin/nvcc 2>/dev/null | head -1 >/dev/null && for n in /usr/local/cuda*/bin/nvcc; do [ -x "$n" ] && "$n" --version 2>/dev/null | grep release | sed "s/.*release //;s/,.*//" | head -1 && break; done)" \
"$(docker --version 2>/dev/null | awk '{print $3}')" \
"$(sudo -n true 2>/dev/null && echo yes || echo no)\""""
    for tag, target in (("HEAD", None), ("WORKER", worker)):
        if target:
            r = ssh_task(target, probe)
            out = r.stdout.strip()
        else:
            r = dotask(probe, shell=True)
            out = r.stdout.strip()
        if "gpu=NVIDIA" in out and "sudo_nopasswd=yes" in out:
            ok(f"{tag}: {out}")
        else:
            bad(f"{tag}: {out}")


def doctor_image(consts, worker, ok, bad):
    """双机运行时镜像存在（受限网络走离线包 docker load）。"""
    hint = f"（双机离线包 {consts['image_tar']}：docker load -i 导入并核对 tag）"
    for tag, target in (("HEAD", None), ("WORKER", worker)):
        if target:
            r = ssh_task(target, f"docker image inspect {shlex.quote(consts['image'])} >/dev/null 2>&1")
        else:
            r = dotask("docker image inspect", [consts["image"]],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            ok(f"{tag} 镜像存在")
        else:
            bad(f"{tag} 缺镜像 {consts['image']} {hint}")


def doctor_runtime_repo(consts, worker, ok, bad):
    """逐项检查 DOWNLOADS.md 第 9 项所需的 MiaAI 部署仓库文件。"""
    files = runtime_repo_files(consts)
    labels = {"compose": "docker-compose.dspark.yml", "start": "start-deepseek-v4-flash-dspark.sh",
              "stop": "stop-deepseek-v4-flash-dspark.sh"}
    missing_local = [labels[key] for key, path in files.items()
                     if not (os.path.isfile(path) if key == "compose" else os.access(path, os.X_OK))]
    if missing_local:
        for name in missing_local:
            bad(f"HEAD 缺少 runtime 文件: {consts['runtime_repo']}/{name}")
    else:
        ok(f"HEAD runtime repo 就绪: {consts['runtime_repo']}")
    checks = " && ".join(
        f"[ {'-f' if key == 'compose' else '-x'} {shlex.quote(path)} ]"
        for key, path in files.items()
    )
    result = ssh_task(worker, checks)
    if result.returncode != 0:
        for name in labels.values():
            remote_path = f"{consts['runtime_repo']}/{name}"
            remote = ssh_task(worker, f"test {'-f' if name == labels['compose'] else '-x'} {shlex.quote(remote_path)}")
            if remote.returncode != 0:
                bad(f"WORKER 缺少 runtime 文件: {consts['runtime_repo']}/{name}")
    else:
        ok(f"WORKER runtime repo 就绪: {consts['runtime_repo']}")
    if missing_local or result.returncode != 0:
        bad("请按 docs/DOWNLOADS.md 第 9 项从 https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark 下载，固定到 a4ce87a2f47f1be8fe64c297a0cf33a9a5e509aa，再将仓库内容放入 common.runtime_repo")


def doctor_model(consts, worker, ok, bad):
    """逐项检查 DOWNLOADS.md 第 7 项模型文件，并检查总大小。"""
    model_path = consts["default_model"]
    required = model_required_files(model_path)
    missing_local = [path for path in required if not os.path.isfile(path)]
    if missing_local:
        for path in missing_local:
            bad(f"HEAD 缺少模型文件: {path}")
        bad("请按 docs/DOWNLOADS.md 第 7 项准备 DeepSeek-V4-Flash-0731 模型；模型官方地址: https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731")
    else:
        ok(f"HEAD 模型关键文件齐全: {model_path}")
    for tag, target in (("HEAD", None), ("WORKER", worker)):
        if target:
            checks = " && ".join(f"[ -f {shlex.quote(path)} ]" for path in required)
            result = ssh_task(target, checks)
            if result.returncode != 0:
                for path in required:
                    if ssh_task(target, f"test -f {shlex.quote(path)}").returncode != 0:
                        bad(f"WORKER 缺少模型文件: {path}")
                bad("请按 docs/DOWNLOADS.md 第 7 项将完整模型同步到 worker 的相同路径")
            else:
                ok(f"WORKER 模型关键文件齐全: {model_path}")
            r = ssh_task(target, f"du -sb {shlex.quote(model_path)} 2>/dev/null | cut -f1")
            size = r.stdout.strip()
        else:
            r = dotask(f"du -sb {shlex.quote(model_path)} 2>/dev/null | cut -f1", shell=True)
            size = r.stdout.strip()
        if size.isdigit() and int(size) > 160_000_000_000:
            ok(f"{tag} 模型缓存 {int(size) / 1e9:.1f} GB")
        else:
            bad(f"{tag} 模型缓存不足 ({size})")


def doctor_roce(consts, worker, ok, bad):
    """双机 RoCE 链路 ACTIVE 计数。"""
    cmd = 'rdma link show 2>/dev/null | grep -c "state ACTIVE physical_state LINK_UP"'
    for tag, target in (("HEAD", None), ("WORKER", worker)):
        if target:
            r = ssh_task(target, cmd)
        else:
            r = dotask(cmd, shell=True)
        out = r.stdout.strip()
        if out.isdigit() and int(out) >= 1:
            ok(f"{tag} RoCE ACTIVE x{out}")
        else:
            bad(f"{tag} 无 ACTIVE RoCE 链路")


def cmd_doctor(consts, cfg, args):
    worker = args.worker or consts["worker_ssh"]
    logtask("doctor", f"双机环境自检（SSH/GPU/CUDA/镜像/模型/RoCE/端口）；worker={worker} config={consts['config_local']}")
    fails = [0]

    def ok(msg):
        print(f"[OK] {msg}")

    def bad(msg):
        print(f"[FAIL] {msg}")
        fails[0] += 1

    print(f"=== head: {socket.gethostname()} / worker: {worker} ===")
    if ssh_task(worker, "echo ok").returncode == 0:
        ok(f"SSH {worker}")
    else:
        bad(f"SSH {worker} 不通")
    doctor_check_node(consts, worker, ok, bad)
    doctor_image(consts, worker, ok, bad)
    doctor_runtime_repo(consts, worker, ok, bad)
    doctor_model(consts, worker, ok, bad)
    doctor_roce(consts, worker, ok, bad)
    # 8888 端口空闲（head 本机）
    r = dotask('ss -ltn "( sport = :8888 )" 2>/dev/null | tail -n +2 | grep -q .', shell=True)
    if r.returncode == 0:
        bad("HEAD 8888 已被占用")
    else:
        ok("HEAD 8888 空闲")
    print()
    if fails[0] == 0:
        logtask("doctor", "全部通过，可以开始部署")
        return 0
    logtask("doctor", f"存在 {fails[0]} 项失败，请先修复", level=LogLevel.WARN)
    return 1


# ---- 工具命令（install 内部复用 + 调试导出） ----

def cmd_load_config(consts, cfg, args):
    """输出 SECTION_KEY='value'（shell 可 eval；调试导出用）。"""
    sections = args.sections or ["common", "head", "worker"]
    logtask("load-config", f"导出 SECTION_KEY='value'（调试导出）；sections={' '.join(sections)}")
    for sec in sections:
        for key, val in (cfg.get(sec) or {}).items():
            safe = str(val).replace("'", "'\\''")
            print(f"{sec.upper()}_{key.upper()}='{safe}'")
    return 0


def cmd_gen_env(consts, cfg, args):
    """从 config + 模型生成完整 .env.dspark（--output 写文件，缺省 stdout）。"""
    model_arg = args.model or cfg.get("common", {}).get("default_model", "")
    output = args.output
    if not model_arg:
        return logtask("gen-env 需要 --model <模型绝对路径> 或 config 的 common.default_model", level=LogLevel.ERROR)
    model_dir = resolve_model(consts, model_arg)
    logtask("gen-env", f"生成完整 .env.dspark（生产 .env 由 install 内部复用本逻辑）；model={model_dir} output={output or 'stdout'}")
    content = gen_env(cfg, model_dir)
    if output:
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        sys.stdout.write(content)
    return 0


# ---- 帮助与入口 ----

def cmd_help(consts=None, cfg=None, rest=None):
    print("""用法: python3 program.py [--config <config.yaml>] <命令> [参数]
  --config 缺省 /etc/dspark-vllm/config.yaml（systemd 本机调用时）

管理/部署（head 上，经 deploy.sh）:
  install [模型路径]        安装/覆盖安装（缺省用 common.default_model）
  uninstall                清理部署（停容器+移除模型注册+禁用自启）
  restart                  重启集群（= stop + start）
  display off|on            设置双机默认终端/图形启动模式（重启后生效）
  live_check [--wait <秒>]  API 健康检查（--wait 轮询）
  chat_verify [目标tokens]  长上下文解码性能验证（Issue #22，默认 620000）
  doctor [worker目标]       双机环境自检

运行支撑（双机本机，systemd 单元直调）:
  start / stop             仅 head（worker 编排顺序）
  ensure                   仅 worker（容器守护）
  status                   双机容器与 API 状态

工具:
  load-config              导出 SECTION_KEY='value'（调试导出）
  gen-env --model <路径> [--output <文件>]   生成完整 .env.dspark
  help                     本帮助""")
    return 0


def non_negative_int(value):
    """argparse 类型：允许 0，拒绝负数等待时间。"""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("必须是非负整数")
    return parsed


def positive_int(value):
    """argparse 类型：拒绝会导致空循环的非正 token 目标。"""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return parsed


def build_parser():
    """argparse 子命令 CLI：全局 --config + 各子命令参数。"""
    parser = argparse.ArgumentParser(
        prog="program.py",
        description="DeepSeek-V4-Flash 双机集群唯一实现（命令 → 函数分发）。",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="/etc/dspark-vllm/config.yaml", metavar="<config.yaml>",
                        help="config.yaml 路径（缺省 /etc/dspark-vllm/config.yaml，systemd 本机调用）")
    sub = parser.add_subparsers(dest="command", metavar="<命令>")
    # 管理与部署（head，经 deploy.sh）
    pm = sub.add_parser("install", help="安装/覆盖安装")
    pm.add_argument("model", nargs="?", help="模型绝对路径（缺省 common.default_model）")
    sub.add_parser("uninstall", help="清理部署")
    sub.add_parser("restart", help="重启集群（= stop + start）")
    pm = sub.add_parser("display", help="设置双机默认终端/图形启动模式")
    pm.add_argument("mode", choices=("off", "on"), help="off=终端模式，on=图形界面模式")
    pm = sub.add_parser("live_check", help="API 健康检查")
    pm.add_argument("--wait", type=non_negative_int, metavar="<秒>", help="轮询等待秒数（缺省一次检查）")
    pm = sub.add_parser("chat_verify", help="长上下文解码性能验证（Issue #22）")
    pm.add_argument("target", nargs="?", type=positive_int, default=620000, metavar="<tokens>",
                   help="目标 prompt tokens（默认 620000）")
    pm = sub.add_parser("doctor", help="双机环境自检")
    pm.add_argument("worker", nargs="?", help="worker SSH 目标（缺省 config worker.ssh）")
    # 运行支撑（双机本机，systemd 直调）
    sub.add_parser("start", help="启动集群（head；worker 先起，head 后起）")
    sub.add_parser("stop", help="停止集群（head；head 先停，worker 后停）")
    sub.add_parser("ensure", help="worker 容器守护（worker）")
    sub.add_parser("status", help="双机容器与 API 状态")
    # 工具
    pm = sub.add_parser("load-config", help="导出 SECTION_KEY='value'（调试导出）")
    pm.add_argument("sections", nargs="*", default=["common", "head", "worker"], help="配置节（缺省全部）")
    pm = sub.add_parser("gen-env", help="生成完整 .env.dspark")
    pm.add_argument("--model", help="模型绝对路径（缺省 common.default_model）")
    pm.add_argument("--output", help="写入文件（缺省 stdout）")
    sub.add_parser("help", help="本帮助")
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv[1:])
    cmd = args.command
    if cmd in (None, "help"):
        return cmd_help()
    config = parser_yaml(args.config)
    consts = parser_constants(config)
    consts["config_local"] = args.config
    drop_privilege(consts, argv)
    dispatch = {
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "restart": cmd_restart,
        "display": cmd_display,
        "live_check": cmd_live_check,
        "chat_verify": cmd_chat_verify,
        "doctor": cmd_doctor,
        "start": cmd_start,
        "stop": cmd_stop,
        "ensure": cmd_ensure,
        "status": cmd_status,
        "load-config": cmd_load_config,
        "gen-env": cmd_gen_env,
    }
    return dispatch[cmd](consts, config, args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
