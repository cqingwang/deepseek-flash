<!-- source: https://docs.nvidia.com/sync/latest/direct-connections.html -->

# Direct Connections[#](#direct-connections "Link to this heading")

## Overview and Prerequisites[#](#overview-and-prerequisites "Link to this heading")

NVIDIA Sync allows you to add any remote Linux device for which you have SSH access directly over the network. A direct connection requires your laptop to be on the same network as the device and for Sync to have the required SSH information (for example, IP address, hostname, username and password, or key).

Direct connections will work only if your laptop is on the same network as the remote device, or the remote device is accessible from the internet (for example, a cloud VM). A typical example is working with a device on a LAN, such as a home or corporate network.

If you are not on the same network as your remote device, you may be able to connect using the Tailscale integration. For more information, see [Working with Tailscale Connections](tailscale.html#nvidia-sync-tailscale).

## Adding a Device for a Direct Connection[#](#adding-a-device-for-a-direct-connection "Link to this heading")

There are a few different scenarios for adding a device for a direct connection.

### Adding a DGX Spark or a GB10 Device with Device Name[#](#adding-a-dgx-spark-or-a-gb10-device-with-device-name "Link to this heading")

After initial setup, the system broadcasts its hostname using [multicast DNS (mDNS)](https://en.wikipedia.org/wiki/Multicast_DNS) so you can find and add it without the IP address.

If you are on a network that does not support mDNS, you will need the device IP address on the network.

1. Open the Settings window by clicking the gear icon in the top left corner.
2. Select the **Devices** tab, then click **Add Device**.
3. The device discovery modal opens to show the device name.
4. Select the device and fill in the fields in the configuration modal:

   - **Name:** Enter a name to identify this device.
   - **Hostname or IP:** Pre-populated with the device name you selected.
   - **Port number:** The default is 22.
   - **Username:** Enter your username for accessing the device.
   - **Password:** Enter your password for accessing the device.
5. Confirm the details by clicking **Add**.

If the details are correct, the device will be added and you can then directly connect to it using Sync.

### Adding with Known IP Address[#](#adding-with-known-ip-address "Link to this heading")

If the device is not broadcasting its name with mDNS or you are on a network that suppresses mDNS, you need to use a known IP address.

1. Open the NVIDIA Sync app and select **Add Device**.
2. Select **Add a device manually** at the bottom of the broadcast modal.
3. Fill in the fields in the configuration modal:

   - **Name:** Enter a name to identify this device.
   - **Hostname or IP:** Enter the IP address for the device on the network.
   - **Port number:** The default is 22.
   - **Username:** Enter your username for accessing the device.
   - **Password:** Enter your password for accessing the device.
4. Confirm the details by clicking **Add**.

If the details are correct, the device will be added and you can then directly connect to it using Sync.

### Importing an Existing SSH Configuration[#](#importing-an-existing-ssh-configuration "Link to this heading")

NVIDIA Sync can also add a device that is already aliased in your main SSH configuration file. On Mac and Linux this file is `~/.ssh/config`, and on Windows it is `C:\Users\<user-name>\.ssh\config`.

Entries from that file are used as-is and must use key-based access to the remote device. Ensure the SSH alias is valid and working before importing the device into Sync.

1. Open the NVIDIA Sync app and select **Add Device**.
2. Select **Add a device manually** at the bottom of the broadcast modal.
3. Entries from the main SSH configuration file are shown.
4. Select the appropriate alias.
5. Confirm the import by clicking **Add**.

## Using a Directly Connected Device[#](#using-a-directly-connected-device "Link to this heading")

Once you have added a device to NVIDIA Sync, you can connect to it as long as you are on the appropriate network. To connect from anywhere, configure the Tailscale integration. For more information, see [Working with Tailscale Connections](tailscale.html#nvidia-sync-tailscale).

### Connecting and Disconnecting[#](#connecting-and-disconnecting "Link to this heading")

To connect to a device that you have added:

1. Ensure you are on the same network as the device.
2. Open the NVIDIA Sync app.
3. Select the device name in the drop-down menu in the top left corner.
4. Click **Connect**.

To disconnect from a currently connected device:

1. Open the NVIDIA Sync pop-up window.
2. Click **Disconnect**.
