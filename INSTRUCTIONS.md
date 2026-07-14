# Minimal setup instructions

## 1. Known-good target

Validated working setup:

- Raspberry Pi 3 internal Bluetooth controller, `BCM43438`, UART `hci0`.
- Raspberry Pi OS Lite 64-bit, Debian 13 `trixie`.
- Kernel seen in the successful test: `6.18.34+rpt-rpi-v8`.
- BlueZ seen in the successful test: `5.82`.
- `bluez-meshd` started explicitly with raw HCI I/O: `--io generic:hci0`.

Known-bad / avoid for now:

- Raspberry Pi OS Bookworm 32-bit with BlueZ `5.66` and the default MGMT mesh I/O path.
- In that setup, BlueZ logged `Mesh Send Complete`, but an external Shelly BLE scanner did not see the Pi-originated Mesh `0x2A` / `0x2B` advertisements.

## 2. Install OS and packages

Flash Raspberry Pi OS Lite 64-bit / Debian 13 `trixie` with Raspberry Pi Imager. Enable SSH in the Imager settings.

After first login:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y bluez bluez-meshd python3-dbus python3-gi rfkill
sudo reboot
```

Check versions and controller state:

```bash
uname -a
bluetoothd --version
hciconfig -a
btmgmt info
rfkill list all
```

Expected: one Bluetooth controller, usually `hci0`, not hard-blocked.

## 3. Clone/copy repository

```bash
cd ~
git clone <your-repo-url> sanlight-mesh-bluez-poc
cd ~/sanlight-mesh-bluez-poc
```

No `pip install` is required for the current PoC. The required Python bindings come from Debian packages:

```text
python3-dbus
python3-gi
```

A compile check is optional but useful:

```bash
python3 -m py_compile sanlight_protocol.py sanlight_canonical_sender_poc.py
```

## 4. Add SANlight CDB file

Export `SANlightMesh.json` from the SANlight app and copy it to:

```text
~/sanlight-mesh-bluez-poc/private/SANlightMesh.json
```

Set restrictive permissions:

```bash
cd ~/sanlight-mesh-bluez-poc
mkdir -p private
chmod 700 private
chmod 600 private/SANlightMesh.json
```

Important: `SANlightMesh.json` contains NetKey/AppKey/DeviceKey material. Never commit it and never share it publicly.

## 5. Inspect your node addresses

Addresses are installation-specific. Do not assume that `0002`, `0003`, `C000` or `C001` exist in another SANlight mesh.

Use:

```bash
python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json list-nodes
```

This prints:

- SANlight lamp node unicast addresses detected from the CDB vendor model.
- CDB groups.
- Example commands using the first detected lamp node.

The generic JSON summary is also available:

```bash
python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json inspect
```

In the original test installation, the CDB happened to contain:

```text
0x0002  3-60 1.5 Master Links
0x0003  3-60 1.5 Rechts
0xC000  Rechts
0xC001  Links
```

Those values are examples only.

## 6. Install and start the mesh daemon service

For normal use, do not keep `bluetooth-meshd` running in a second terminal. Install it as a systemd service:

```bash
sudo ./scripts/install-service.sh
```

For a fresh device or a deliberate development reset, also clear old BlueZ mesh state:

```bash
sudo ./scripts/install-service.sh --reset-mesh-state
```

What the script does:

- stops `bluetooth.service`, `bluetooth-mesh.service`, and old `bluetooth-meshd` processes
- unblocks Bluetooth with `rfkill`
- prepares `hci0`
- resolves the absolute paths of `rfkill`, `hciconfig`, `btmgmt`, and `bluetooth-meshd`
- installs `/etc/systemd/system/sanlight-meshd-generic.service`
- starts `bluetooth-meshd --io generic:hci0 --nodetach`
- does not put `hciconfig` or `btmgmt` into `ExecStartPre`, because these helpers can block under systemd
- enables the service for reboot
- checks whether `org.bluez.mesh` appears on D-Bus

Check service state:

```bash
systemctl status sanlight-meshd-generic.service
busctl tree org.bluez.mesh
journalctl -u sanlight-meshd-generic.service -f
```

Expected:

```text
/org/bluez/mesh
```

## 7. Manual daemon start, only for debugging

The manual two-terminal mode is still useful when debugging BlueZ itself.

Terminal 1:

```bash
sudo systemctl stop bluetooth.service
sudo systemctl stop bluetooth-mesh.service
sudo pkill -x bluetoothd 2>/dev/null || true
sudo pkill -x bluetooth-meshd 2>/dev/null || true

sudo rfkill unblock bluetooth
sudo rfkill unblock all
sudo hciconfig hci0 down 2>/dev/null || true
sudo btmgmt --index 0 power off 2>/dev/null || true

sudo /usr/libexec/bluetooth/bluetooth-meshd \
  --io generic:hci0 \
  --nodetach \
  --debug
```

Expected useful log lines:

```text
mesh-io-generic.c:hci_init() Started mesh on hci 0
mesh_ready_callback
Added Network Interface on /org/bluez/mesh
```

Keep this terminal running only for debug sessions.

## 8. Import/configure local mesh identities

Open Terminal 2:

```bash
cd ~/sanlight-mesh-bluez-poc

sudo python3 sanlight_canonical_sender_poc.py \
  --cdb private/SANlightMesh.json \
  --iv-index 0 \
  setup
```

Expected end result:

```text
SETUP OK
```

This creates local state files such as:

```text
.sanlight-mesh-poc-provisioner-state.json
.sanlight-mesh-poc-appid2-sender-state.json
```

These files also must not be committed or shared.

## 9. First functional tests

First list addresses from your CDB:

```bash
python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json list-nodes
```

Read lamp time/brightness from a unicast lamp node reported by `list-nodes`:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json get-live <NODE>
```

Set MaxBrightness for one lamp. The script rejects `0` and values below `20` for safety:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json set-max <NODE> 68
```

Set all detected SANlight lamp clocks manually:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json set-time all 10:38:30
```

Synchronize all detected SANlight lamp clocks to current local Pi time:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json sync-now
```

Manual seconds since local midnight also works. The CLI accepts seconds; the script sends milliseconds on the wire because SANlight expects milliseconds:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json set-uptime all 61258
```

## 10. Optional systemd service for the mesh daemon

For manual development, keep Terminal 1 running. For a later always-on setup, copy and adapt the example service:

```bash
sudo cp systemd/sanlight-meshd-generic.service.example /etc/systemd/system/sanlight-meshd-generic.service
sudo systemctl daemon-reload
sudo systemctl enable sanlight-meshd-generic.service
sudo systemctl start sanlight-meshd-generic.service
journalctl -u sanlight-meshd-generic.service -f
```

Run `setup` once after the daemon is running.

## 11. Reset procedure

Only for development resets:

```bash
sudo systemctl stop sanlight-meshd-generic.service bluetooth.service bluetooth-mesh.service
sudo pkill -x bluetoothd 2>/dev/null || true
sudo pkill -x bluetooth-meshd 2>/dev/null || true
sudo rm -rf /var/lib/bluetooth/mesh/*
rm -f .sanlight-mesh-poc-*-state.json
```

Then restart the mesh daemon and run `setup` again.
