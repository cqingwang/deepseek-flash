<!-- source: https://docs.nvidia.com/dgx/dgx-spark/os-and-component-update.html -->

# OS and Component Update Guide[#](#os-and-component-update-guide "Link to this heading")

This section provides guidance for updating the operating system, software components, and firmware on your DGX Spark. The DGX Spark runs on NVIDIA DGX OS, which is an Ubuntu-based Linux distribution optimized for AI workloads.

Note

**Founders Edition Only**: The update information in this guide applies only to the DGX Spark Founders Edition. Devices from other manufacturers might have different update procedures.

## Ubuntu Support[#](#ubuntu-support "Link to this heading")

The Ubuntu Pro OS license in DGX Spark includes 10-year OS support from Canonical.

## Update Methods[#](#update-methods "Link to this heading")

**We strongly recommend using the DGX Dashboard for all system updates on your |spark|.** The dashboard ensures your system stays up to date with the latest NVIDIA-optimized components and configurations. While standard Ubuntu package management methods will work, the dashboard provides the most reliable and tested update path for your DGX system.

## Using DGX Dashboard for Updates[#](#using-dgx-dashboard-for-updates "Link to this heading")

The DGX Dashboard is the **primary and recommended** way to perform system updates on your DGX Spark. It provides a centralized interface for:

- Viewing available system updates
- Installing security patches and system updates
- Managing NVIDIA driver updates
- Managing firmware updates
- Monitoring update status and progress

For detailed information about using the DGX Dashboard, including how to access it and perform updates, see [DGX Dashboard](dgx-dashboard.html#spark-dgx-dashboard).

Warning

Before performing any system or firmware updates:

- Ensure your system is connected to a stable power source
- Close all running applications and save your work
- Have a recovery plan in place
- Schedule updates during maintenance windows when possible

## Manual System Updates[#](#manual-system-updates "Link to this heading")

**Note:** While manual updates using standard Ubuntu package management commands will work, we strongly recommend using the DGX Dashboard for all updates to ensure optimal system performance and compatibility.

For advanced users or when the DGX Dashboard is not available, you can perform system updates manually using the following steps:

1. Open a remote or local terminal on the DGX Spark device.
2. Run the following commands:

   ```
   sudo apt update
   sudo apt dist-upgrade
   sudo fwupdmgr refresh
   sudo fwupdmgr upgrade
   sudo reboot
   ```

These commands will:

- Update the package lists and upgrade all installed packages (including OS components and drivers)
- Refresh the firmware metadata and upgrade all firmware components
- Reboot the system to apply updates

## Update Best Practices[#](#update-best-practices "Link to this heading")

- **Use the DGX Dashboard**: Always prefer the DGX Dashboard for system updates to ensure compatibility and optimal performance
- **Regular updates**: Check for updates regularly, especially security patches
- **Backup before major updates**: Always backup critical data before major system changes
- **Stable power**: Ensure your system has a stable power supply during updates
- **Maintenance windows**: Schedule updates during planned maintenance windows when possible
