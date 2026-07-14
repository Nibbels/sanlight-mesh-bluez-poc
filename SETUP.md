# SETUP

This is the minimal first-time setup path for a fresh Raspberry Pi.

The goal is: install the required system packages, put the required project files in place, run one setup script, and send one safe test command.

## 1. Install Raspberry Pi OS and required packages

Use Raspberry Pi Imager and flash:

```text
Raspberry Pi OS Lite 64-bit
Debian 13 trixie
```

Boot the Raspberry Pi, log in via SSH, then install the required packages:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y bluez bluez-meshd python3-dbus python3-gi rfkill git
sudo reboot
```

After reboot, log in again and check the important versions:

```bash
bluetoothd --version
uname -a
```

Validated working reference:

```text
BlueZ 5.82
Raspberry Pi OS Lite 64-bit / Debian 13 trixie
```

## 2. Get the project and SANlightMesh.json in place

Clone the repository:

```bash
cd ~
git clone https://github.com/Nibbels/sanlight-mesh-bluez-poc.git
cd ~/sanlight-mesh-bluez-poc
```

Create the private config directory:

```bash
mkdir -p private
chmod 700 private
```

Export `SANlightMesh.json` from the SANlight smartphone app and copy it to:

```text
~/sanlight-mesh-bluez-poc/private/SANlightMesh.json
```

Then protect the file:

```bash
chmod 600 private/SANlightMesh.json
```

Important: `private/SANlightMesh.json` contains Bluetooth Mesh secrets. Do not commit it, publish it, or paste it into issues.

## 3. Run the complete setup

Run:

```bash
sudo bash ./scripts/setup-all.sh
```

This setup script prepares the local Raspberry Pi state, installs and starts the BlueZ mesh service, imports the SANlight mesh data from `private/SANlightMesh.json`, and prints the detected lamp node addresses.

Expected final result:

```text
Setup complete.
```

## 4. Send one safe test command

List the detected node addresses:

```bash
python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json list-nodes
```

Then read status from one detected unicast lamp node:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json get-live <NODE>
```

Replace `<NODE>` with one of the unicast node addresses printed by `list-nodes`, for example `0002` in one specific installation.

This command only reads lamp time and brightness. It does not change brightness or lamp time.

## More information

For service repair, detailed options, known-good versions, and troubleshooting, read:

[INSTRUCTIONS.md](INSTRUCTIONS.md)

For validated opcodes, architecture notes, and continuation/debug context, read:

[AI_CONTEXT.md](AI_CONTEXT.md)
