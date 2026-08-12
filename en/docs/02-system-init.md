# 02 System Initialization, OTA Upgrade and Firmware

## 2.1 First Boot

1. Connect power and a display/keyboard, or connect to the network and SSH in (the username is
   created during the first-boot wizard; use the same `<USER>` on both machines).
2. Complete the NVIDIA first-boot wizard (accept the EULA, configure networking).
3. Confirm the system version:

```bash
cat /etc/dgx-release 2>/dev/null; cat /etc/os-release | head -2
```

> DGX Spark uses `/etc/dgx-release` for the system/OTA version: the factory image only carries
> `DGX_SWBUILD_VERSION` (e.g. 7.2.3); **`DGX_OTA_VERSION` (e.g. 7.5.0) appears only after an OTA has
> been applied**. There is no Jetson-style `/etc/nv_tegra_release`. Whether the system is ≥ 2026-04
> is judged by the `dgx-spark-ota-update-meta` package version (see 2.2 step 2).

## 2.2 System Software OTA Upgrade

> **Know the order first (common misconception)**: DGX Spark has only ONE official OTA path —
> **DGX Dashboard → system update**, or the official manual commands (apt + fwupd).
> **`nvidia-spark-ota-check` is NOT the upgrade tool and it does NOT ship on the factory image** —
> it is a *verification* tool whose `nvidia-spark-ota-check` package is **installed together with
> the OTA update**. So you must first run the official OTA upgrade; **only after the system has been
> upgraded to a release that includes that package does the command exist**. On an un-upgraded
> unit it is `command not found`, and there is no such thing as using it to apply an update.

### Step 1: Run the official OTA upgrade

- **GUI (recommended)**: DGX Dashboard → Updates; click update. The Dashboard runs exactly the
  manual sequence below (full apt upgrade + fwupd firmware + automatic reboot), triggered by the
  systemd service `nvidia-spark-run-apt-upgrade-once.service` (provided by the
  `nvidia-spark-run-apt-upgrade` package) — no manual intervention needed.
- **CLI (headless environment)** — the exact steps from the official OS and Component Update Guide:

```bash
sudo apt update
sudo apt dist-upgrade                  # official step is dist-upgrade, not apt upgrade
sudo fwupdmgr refresh
sudo fwupdmgr upgrade
sudo reboot
```

> ⚠️ Do NOT substitute a plain `sudo apt upgrade` for `apt dist-upgrade`. In the community,
> `apt upgrade` pulled in driver 580.173.02 that is not paired with the OTA2607 firmware, and after
> reboot `nvidia-smi` reported “No devices found” (`nvidia-spark-ota-check torn-score` → torn: 1,
> with driver the only failing item). Always use the official path for system software.

### Step 2: After reboot, confirm the system is ≥ 2026-04

Cluster Assistant requires system software ≥ 2026-04 (April 2026). The official/ecosystem way to
check is the **OTA version-marker package** `dgx-spark-ota-update-meta` — NVIDIA Sync's Cluster
Assistant itself reads its version over SSH (`Installed:` ≥ `26.04.1` means ≥ 2026-04):

```bash
cat /etc/dgx-release                    # DGX_OTA_VERSION (e.g. 7.5.0) appears only after an OTA
LC_ALL=C apt-cache policy dgx-spark-ota-update-meta   # Installed line ≥ 26.04.1
# equivalent: dpkg-query -W -f='${Version}' dgx-spark-ota-update-meta
```

### Step 3 (optional): deep verification with `nvidia-spark-ota-check`

**Prerequisite**: this tool's package is delivered via the OTA stream — it exists only after an OTA
that includes it has been applied. If you get `command not found`, the package has not been
installed with your OTA yet — **go back to Step 1 and keep upgrading**; it is not an upgrade
mechanism:

```bash
command -v nvidia-spark-ota-check       # missing = package not shipped by your OTA yet (normal)
apt-cache policy nvidia-spark-ota-check # inspect whether the package is installed

sudo nvidia-spark-ota-check summary        # detected_ota OTA2607, torn: 0.0, match 100%
sudo nvidia-spark-ota-check torn-score     # { "name": "OTA2607", "torn": 0 }
sudo nvidia-spark-ota-check installed-name # installed-name matches current OTA 100%
```

> **Where this command comes from (corrected)**: `nvidia-spark-ota-check` is provided by the
> package of the same name (`/usr/bin/nvidia-spark-ota-check`; sources under
> `/opt/nvidia/spark-ota-check/`), **installed together with the OTA**, not preinstalled at the
> factory. The official OS and Component Update Guide **never uses it as an update entry point**
> (the official paths are Dashboard or the manual apt+fwupd commands); it appears mainly on the
> NVIDIA developer forums as a diagnostics tool for checking that an OTA is complete (torn-score)
> and that installed-name matches the current OTA. Per-release contents are listed in the official
> release notes: <https://docs.nvidia.com/dgx/dgx-spark/release-notes.html>

> **Reboot, then re-run Steps 2/3 to confirm nothing is left pending.** A known symptom: after
> upgrading, `nvidia-smi` reports failure because the driver modules were built for the new kernel;
> a reboot resolves it.

Verify:

```bash
nvidia-smi                                # expect NVIDIA GB10, driver 580.x
/usr/local/cuda-13.0/bin/nvcc --version   # expect CUDA 13.0 (nvcc not on default PATH)
nproc                                     # 20
free -g | head -2                         # expect ~121 Gi
df -h /home | tail -1                     # need ≥ 400 GB free for the model
```

## 2.3 ConnectX-7 / USBPD Firmware (optional but recommended)

```bash
sudo fwupdmgr refresh
sudo fwupdmgr update -y                # flashes firmware and reboots
# after reboot (no USBPD device on this system; check ConnectX-7 and UEFI instead)
fwupdmgr get-devices | grep -A2 "MT2910"   # ConnectX-7 firmware (e.g. 28.45.4028)
sudo nvidia-spark-ota-check summary        # torn-score: 0 (skip if the package is not yet shipped)
```

## 2.4 Docker and User Group

```bash
docker --version                       # Docker ships with the system
sudo usermod -aG docker $USER          # run docker without sudo; takes effect on new SSH sessions
```

> Note: `newgrp docker` only affects the current shell; a new SSH session can run `docker ps` directly.

## Official References

- [DGX Spark First Boot](https://docs.nvidia.com/dgx/dgx-spark/first-boot.html)
- [DGX Spark User Guide (software updates)](https://docs.nvidia.com/dgx/dgx-spark/)
- [DGX Spark: OS and Component Update Guide](https://docs.nvidia.com/dgx/dgx-spark/os-and-component-update.html)
- [DGX Spark Release Notes (OTA contents)](https://docs.nvidia.com/dgx/dgx-spark/release-notes.html)
- [Cluster Assistant (system version ≥ 2026-04)](https://docs.nvidia.com/sync/latest/cluster-assistant.html)
