<!-- source: https://docs.nvidia.com/dgx/dgx-spark/release-notes.html -->

# DGX Spark Release Notes[#](#spark-release-notes "Link to this heading")

This section provides release notes for the DGX Spark, including information about
new features, known issues, and software version updates.

## Current Software Versions[#](#current-software-versions "Link to this heading")

The following table shows the current version information for the DGX Spark
software stack.

| Component | Version |
| --- | --- |
| NVIDIA DGX OS | 7.5.0 |
| NVIDIA GPU Driver | 580.159.03 |
| NVIDIA CUDA Toolkit | 13.0.2 |
| Canonical Kernel | 6.17 |
| UEFI | 1.110.13 |
| Embedded Controller (EC) | 3.5.8 |
| USB Power Delivery (USB PD) | 0.5.22 |
| Trusted Platform Module (TPM) | 7.516.1 |
| System on Chip (SoC) | 2.155.11 |

Note

These release versions apply only to the DGX Spark Founders Edition. GB10-based partner systems may not receive updates at the same time.

### July 2026 Release[#](#july-2026-release "Link to this heading")

#### What’s New[#](#what-s-new "Link to this heading")

- **Improved Memory Management**: The included driver enhances Out-of-Memory (OOM) handling with GB10’s unified memory architecture. User feedback is now available when the system encounters memory pressure, which improves robustness and reliability when operating larger models.
- **Adjustable Display Reserved Memory**: The Display Reserved Memory can now be toggled between 2GB (default) and 4GB through the system BIOS. Workflows that require displaying many applications and windows will benefit from the larger display memory carveout. Users in appliance mode do not need to change default settings.
- **Enterprise Management Feature Enhancements**: The cloud-init initialization framework and image customization include the following updates. Refer to [Cloud-init for DGX Spark](https://docs.nvidia.com/dgx/dgx-spark/enterprise-fleet-lifecycle.html#spark-efl-cloud-init) for more information.

  - **Cloud-init Network Protocol Support**: In addition to direct USB connections, Cloud-init now supports DHCP, HTTP, and TFTP.
  - **FastOS Recovery Image Customization**: In addition to already supporting the customization of DGX OS, Cloud-init adds support to customize the NVIDIA-provided FastOS recovery image for the DGX Spark Founders Edition.

#### Fixed Issues[#](#fixed-issues "Link to this heading")

- **System and Display Instability When Hot-Plugging Displays**: Addressed system and display instability when hot-plugging displays.

### June 2026 Release[#](#june-2026-release "Link to this heading")

#### What’s New[#](#id2 "Link to this heading")

- **Out-of-Box-Experience (OOBE) Enhancements**: Updates to the OOBE that enable faster initial device setup time and easier navigation to discover and install local AI agents, including:

  - **Over-the-Air (OTA) Updates**: OTA updates are not installed by default during initial setup, allowing users to start using their system sooner. Users can download and install OTA updates after initial system setup.
  - **NemoClaw Playbook**: After initial system boot, the DGX Spark playbook site opens, where the NemoClaw playbook is prominently displayed for streamlined setup of a sandboxed local agent.
- **New Application and Library Features**: NVIDIA Sync and NVIDIA Collective Communications Library (NCCL) include the following updates:

  - **NVIDIA Sync Cluster Assistant**: The Cluster Assistant is now available on the **Settings** page in the NVIDIA Sync application. The Cluster Assistant helps users connect up to three devices without a network switch, and up to four devices using a switch.
  - **NCCL**: NCCL (Version 2.30u1) has updated support for connecting three DGX Spark systems in a ring topology.

### April 2026 Release[#](#april-2026-release "Link to this heading")

#### What’s New[#](#id3 "Link to this heading")

- **Enterprise Features**: Support for tools and capabilities designed to facilitate system management in enterprise environments, including:

  - **Enterprise Management Guide**: Enables IT administrators to plan, configure, and manage DGX Spark deployments at scale with a dedicated reference covering workflows, provisioning, update procedures, and system lifecycle management across fleets. For more information, refer to [Enterprise Manageability](enterprise-manageability.html#spark-enterprise-manageability).
  - **Skip the Automated OOBE for IT Administrator Provisioning**: Allows IT administrators to bypass the OOBE entirely during provisioning, reducing manual per-device setup steps and minimizing touch while deploying across multiple DGX Spark units.
  - **USB and Local Repository Support for Installations and Updates**: Allows IT administrators to deliver OS installations and software updates through USB drives or internal local package repositories, removing the dependency on cloud connectivity for software distribution and patch management, and allowing administrators to control when new releases are installed.
  - **Support for Air Gapped Deployment and Updates**: Enables IT administrators to deploy and operate DGX Spark systems on isolated networks with no external internet access, suitable for strict security, compliance, and data sovereignty requirements.
  - **Customized Enterprise ISOs Through cloud-init**: Allows IT administrators to embed site-specific configurations (users, network settings, software, and policies) directly into custom DGX OS images using cloud-init, ensuring every unit arrives pre-configured to enterprise standards on first boot.
- **DGX Dashboard Enhancements**: Release highlights are now provided for software releases, enabling users to determine the urgency of applying updates.

#### Fixed Issues[#](#id4 "Link to this heading")

- **Bluetooth Keyboard Pairing**: Addressed an issue where the Bluetooth keyboard pairing modal did not appear in some instances when a keyboard was plugged in.
- **Unable to Detect Network During System Setup**: Addressed Wi-Fi and Ethernet connectivity issues reported during system setup.

### March 2026 Release[#](#march-2026-release "Link to this heading")

#### What’s New[#](#id5 "Link to this heading")

- **Partner Factory Updates**: Firmware update to facilitate GB10 partner factory updates.

### February 2026 Release[#](#february-2026-release "Link to this heading")

#### Fixed Issues[#](#id6 "Link to this heading")

- **Improved Performance with Multiple DGX Spark Systems**: Addressed performance regression noted by some users with multiple connected DGX Spark systems after updating to DGX OS 7.4.0.

### January 2026 Release[#](#january-2026-release "Link to this heading")

#### What’s New[#](#id7 "Link to this heading")

- **Power Management**: Added hot plug support for the ConnectX-7 network adapter, saving up to 18W of power when the adapter is not in use.
- **Bluetooth Audio Support**: Support for Bluetooth audio devices, including headphones and headsets, is now available.
- **Additional Security Controls**: Wi-Fi and Bluetooth can now be disabled in the Unified Extensible Firmware Interface (UEFI) for environments requiring additional security.

#### Fixed Issues[#](#id8 "Link to this heading")

- **Improved Monitor Support**: Better compatibility with TVs and monitors, including multi-monitor configurations and the use of non-native resolutions and refresh rates.
- **Improved Peripheral Setup**: Smoother and more complete OOBE navigation.

### November 2025 Release[#](#november-2025-release "Link to this heading")

#### What’s New[#](#id9 "Link to this heading")

- **New DGX OS kernel**: The operating system now incorporates the Ubuntu 6.14 Hardware Enablement (HWE) kernel stack. The new kernel brings ongoing performance gains, enhanced stability, broader hardware compatibility, and the latest security updates for a more secure operating environment.
- **JupyterLab updated to latest CUDA and PyTorch**: Updated JupyterLab to CUDA 13.0.2 and the latest PyTorch version, enabling users to work with updated frameworks immediately without extra downloads.

#### Fixed Issues[#](#id10 "Link to this heading")

- **Improved memory reporting in DGX Dashboard**: Addressed the issue with memory reporting differences with unified memory architecture. The readout is now consistent with CUDA guidance for unified memory systems. For more information, refer to [CUDA unified memory guidance](https://nvidia.custhelp.com/app/answers/detail/a_id/5728).
- **Image Generation in JupyterLab**: Resolved the inability to generate images in Stable Diffusion XL Playbook example. Users can now run end-to-end example workflow inside JupyterLab.
- **Improved Peripheral Interoperability**: Better compatibility with USB-C devices, monitors, Bluetooth peripherals, and Wi-Fi access points.
- **Improved recovery image reliability**: The recovery image now installs correctly on macOS and also when multiple external USB-C drives are connected.
- **Keyboard accessibility improvements**: Smoother and more complete OOBE navigation, including the ability to complete entire system setup process using only keyboard.

## Known Issues[#](#known-issues "Link to this heading")

For an updated list of known issues, refer to [Known Issues](known-issues.html#spark-known-issues).
