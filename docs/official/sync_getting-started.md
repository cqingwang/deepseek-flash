<!-- source: https://docs.nvidia.com/sync/latest/getting-started.html -->

# Getting Started[#](#getting-started "Link to this heading")

## General Use Pattern[#](#general-use-pattern "Link to this heading")

The general use pattern for NVIDIA Sync is:

1. Add or import a remote device to NVIDIA Sync.
2. Connect to the device through NVIDIA Sync.
3. One-click launch an IDE or application on the device.
4. Add a custom application to the device and launch it.
5. Use NVIDIA Sync to stop applications running on the device.
6. Disconnect from the device through NVIDIA Sync.

## Installation and Onboarding[#](#installation-and-onboarding "Link to this heading")

### Installation[#](#installation "Link to this heading")

**For Windows:**

1. Download the [Windows installer](https://build.nvidia.com/spark/connect-to-your-spark/sync).
2. Double-click the installer `.exe` file.
3. Accept the license agreement.
4. Complete the installation.

**For Mac:**

1. Download the [Mac application](https://build.nvidia.com/spark/connect-to-your-spark/sync).
2. Drag and drop the application into your Applications folder.
3. Open NVIDIA Sync from the Applications folder.

**For Ubuntu:**

1. Configure the package repository:

   ```
   curl -fsSL https://workbench.download.nvidia.com/stable/linux/gpgkey | sudo tee -a /etc/apt/trusted.gpg.d/ai-workbench-desktop-key.asc
   echo "deb https://workbench.download.nvidia.com/stable/linux/debian default proprietary" | sudo tee -a /etc/apt/sources.list
   ```
2. Update package lists:

   ```
   sudo apt update
   ```
3. Install NVIDIA Sync:

   ```
   sudo apt install nvidia-sync
   ```

### Onboarding Flow[#](#onboarding-flow "Link to this heading")

The application opens after installation completes. If it does not, double-click the desktop icon to open it.

The onboarding flow has five steps:

1. Read and agree to the EULA.
2. Select local IDEs you want NVIDIA Sync to launch and manage on your remote devices.
3. Add your first remote Linux device to NVIDIA Sync.
4. Connect to that device through NVIDIA Sync.
5. Launch an application on the device.

## Next Steps[#](#next-steps "Link to this heading")

After onboarding, continue with:

- [Direct Connections](direct-connections.html#nvidia-sync-direct-connections) — Add devices on your LAN, import SSH aliases, and connect.
- [Applications](applications.html#nvidia-sync-applications) — Launch IDEs, custom scripts, and the DGX Dashboard.
