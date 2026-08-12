# 02 系统初始化、OTA 升级与固件

## 2.1 首次启动

1. 接电源、显示器/键盘，或接好网络后用 SSH 登录（用户名在首启向导中创建，建议两台统一 `<USER>`）。
2. 完成 NVIDIA 首启向导（同意 EULA、配置网络）。
3. 确认系统版本满足要求：

```bash
cat /etc/dgx-release 2>/dev/null; cat /etc/os-release | head -2
```

> DGX Spark 用 `/etc/dgx-release` 确认系统/OTA 版本：出厂镜像只写 `DGX_SWBUILD_VERSION`
> （如 7.2.3），**应用 OTA 之后才会出现 `DGX_OTA_VERSION`**（如 7.5.0）；
> 没有 Jetson 的 `/etc/nv_tegra_release`。是否 ≥ 2026-04 以 `dgx-spark-ota-update-meta`
> 包的版本为准（见 2.2 步骤 2）。

## 2.2 系统软件 OTA 升级

> **先认清顺序（常见误区）**：DGX Spark 的 OTA 只有一条官方通道——**DGX Dashboard 系统更新**，
> 或官方文档给出的手工命令（apt + fwupd）。**`nvidia-spark-ota-check` 不是升级工具，
> 也不是出厂自带命令**——它是 OTA 升级过程中随 `nvidia-spark-ota-check` 软件包**一并装进系统**
> 的**校验工具**。因此必须先执行官方 OTA 升级，**升级到包含该包的版本后这个命令才存在**；
> 在未升级的机器上直接执行它是 `command not found`，拿它当升级命令更是不存在。

### 步骤 1：执行官方 OTA 升级

- **图形界面（推荐）**：DGX Dashboard → Updates / 系统更新，点更新即可。Dashboard 实际
  执行的就是下面这套手工命令（apt 全量升级 + fwupd 固件 + 自动重启），由
  `nvidia-spark-run-apt-upgrade` 软件包提供的 systemd 服务
  （`nvidia-spark-run-apt-upgrade-once.service`）触发，无需手动干预。
- **命令行（无显示器环境）**——官方文档（OS and Component Update Guide）的原始步骤：

```bash
sudo apt update
sudo apt dist-upgrade                  # 官方是 dist-upgrade，不是 apt upgrade
sudo fwupdmgr refresh
sudo fwupdmgr upgrade
sudo reboot
```

> ⚠️ 不要用普通 `sudo apt upgrade` 代替 `apt dist-upgrade`。社区有人用 `apt upgrade`
> 拉入了与 OTA2607 固件不配对的驱动 580.173.02，重启后 `nvidia-smi` 报
> “No devices found”（`nvidia-spark-ota-check torn-score` 报 torn: 1，唯一失败项是 driver）。
> 系统软件升级请始终走官方路径（Dashboard 或上面这套命令）。

### 步骤 2：重启后确认系统版本 ≥ 2026-04

Cluster Assistant 要求系统软件 ≥ 2026-04（April 2026）。官方/生态用
`dgx-spark-ota-update-meta` 这个“OTA 版本标记”包来判断——NVIDIA Sync 的 Cluster
Assistant 就是通过 SSH 解析该包的版本（`Installed:` 行 ≥ `26.04.1` 即 ≥ 2026-04）：

```bash
cat /etc/dgx-release                    # OTA 应用后才有 DGX_OTA_VERSION（如 7.5.0）
LC_ALL=C apt-cache policy dgx-spark-ota-update-meta   # Installed 行 ≥ 26.04.1
# 等价写法：dpkg-query -W -f='${Version}' dgx-spark-ota-update-meta
```

### 步骤 3（可选）：用 `nvidia-spark-ota-check` 做深度校验

**前置条件**：该工具是随 OTA 推送到系统的软件包，只有升级到包含它的版本后才存在。
若提示 `command not found`，说明这个包还没随 OTA 装上——**直接回到步骤 1 继续升级**，
它不是升级手段：

```bash
command -v nvidia-spark-ota-check       # 不存在 = 工具包未随 OTA 安装（正常，先升级）
apt-cache policy nvidia-spark-ota-check # 查看该包是否已装

sudo nvidia-spark-ota-check summary        # detected_ota OTA2607, torn: 0.0, match 100%
sudo nvidia-spark-ota-check torn-score     # { "name": "OTA2607", "torn": 0 }
sudo nvidia-spark-ota-check installed-name # installed-name 与当前 OTA 100% 匹配
```

> **命令来源（更正）**：`nvidia-spark-ota-check` 由同名软件包提供（本机路径
> `/usr/bin/nvidia-spark-ota-check`，代码在 `/opt/nvidia/spark-ota-check/`），
> **随 OTA 升级一起安装**，并非工厂预装。NVIDIA 官方文档（OS and Component Update Guide）
> **从不以它作为升级入口**（官方只推荐 Dashboard 或 apt+fwupd 手工命令）；它主要见于
> NVIDIA 开发者论坛，用于诊断 OTA 是否完整（torn-score）、校验 installed-name 与当前 OTA
> 的匹配度。各版本更新内容与发布说明见官方 release notes：
> <https://docs.nvidia.com/dgx/dgx-spark/release-notes.html>

> **务必重启，并在重启后重复步骤 2/3 确认没有残留升级项**。曾经遇到过：驱动模块编译期
> 与当前内核不一致导致 `nvidia-smi` 报 failed，重启后即恢复。

验证：

```bash
nvidia-smi                                # 期望 NVIDIA GB10, 驱动 580.x
/usr/local/cuda-13.0/bin/nvcc --version   # 期望 CUDA 13.0（nvcc 默认不在 PATH）
nproc                                     # 20
free -g | head -2                         # 期望 ~121 Gi
df -h /home | tail -1                     # 模型需要 ≥ 400 GB 空闲
```

## 2.3 ConnectX-7 / USBPD 固件（可选但推荐）

```bash
sudo fwupdmgr refresh
sudo fwupdmgr update -y                # 会刷固件并重启
# 重启后验证（本系统无 USBPD 设备；重点看 ConnectX-7 与 UEFI 固件）
fwupdmgr get-devices | grep -A2 "MT2910"   # ConnectX-7 固件（如 28.45.4028）
sudo nvidia-spark-ota-check summary        # torn-score: 0（若该包未随 OTA 安装则跳过）
```

## 2.4 Docker 与用户组

```bash
docker --version                       # 系统自带 Docker
sudo usermod -aG docker $USER          # 免 sudo 用 docker；新 SSH 会话生效
```

> 说明：`newgrp docker` 只对当前 shell 生效；新建 SSH 会话即可直接 `docker ps`。

## 官方参考

- [DGX Spark 首次启动](https://docs.nvidia.com/dgx/dgx-spark/first-boot.html)
- [DGX Spark 用户指南（软件更新）](https://docs.nvidia.com/dgx/dgx-spark/)
- [DGX Spark：OS and Component Update Guide](https://docs.nvidia.com/dgx/dgx-spark/os-and-component-update.html)
- [DGX Spark Release Notes（OTA 内容）](https://docs.nvidia.com/dgx/dgx-spark/release-notes.html)
- [Cluster Assistant（系统版本要求 ≥ 2026-04）](https://docs.nvidia.com/sync/latest/cluster-assistant.html)
