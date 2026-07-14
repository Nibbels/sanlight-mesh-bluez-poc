# Detailed instructions

For the minimal first-time setup, start with [SETUP.md](SETUP.md).

This file contains additional operational details, options, and troubleshooting notes.

## Known-good target

Validated working setup:

- Raspberry Pi OS Lite 64-bit / Debian 13 `trixie`
- BlueZ `5.82`
- Raspberry Pi 3 internal Bluetooth controller `BCM43438`
- `bluetooth-meshd` started with raw HCI I/O: `--io generic:hci0`

Known-bad / avoid for now:

- Raspberry Pi OS Bookworm 32-bit with BlueZ `5.66` and the default MGMT mesh I/O path.
- In that setup, BlueZ logged `Mesh Send Complete`, but an external BLE scanner did not see the Pi-originated Mesh `0x2A` / `0x2B` advertisements.

## Required files

The project expects the SANlight CDB at:

```text
private/SANlightMesh.json
```

This file is exported from the SANlight smartphone app and contains Bluetooth Mesh secrets. It is intentionally ignored by Git.

Recommended permissions:

```bash
mkdir -p private
chmod 700 private
chmod 600 private/SANlightMesh.json
```

## First-time setup script

The preferred setup command is:

```bash
sudo bash ./scripts/setup-all.sh
```

Default behavior is a clean **local** setup on the Raspberry Pi:

- checks that `private/SANlightMesh.json` exists
- checks Python syntax
- clears `/var/lib/bluetooth/mesh/*`
- removes `.sanlight-mesh-poc-*-state.json`
- installs and starts `sanlight-meshd-generic.service`
- runs the Python `setup`
- prints detected node addresses

This does **not** reset, unprovision, or modify the actual SANlight lamps. It only rebuilds the Raspberry Pi local BlueZ/Python import state from `private/SANlightMesh.json`.

Keep current local state instead:

```bash
sudo bash ./scripts/setup-all.sh --keep-state
```

Use a different Bluetooth controller:

```bash
sudo bash ./scripts/setup-all.sh --hci hci1
```

## Service-only installation or repair

Install or repair only the systemd service without running the Python mesh import/setup:

```bash
sudo bash ./scripts/install-service.sh
```

Force a local BlueZ/Python state reset during service installation:

```bash
sudo bash ./scripts/install-service.sh --reset-mesh-state
```

Use a different Bluetooth controller:

```bash
sudo bash ./scripts/install-service.sh --hci hci1
```

Install the service but do not start it:

```bash
sudo bash ./scripts/install-service.sh --no-start
```

The generated service runs:

```text
/usr/libexec/bluetooth/bluetooth-meshd --io generic:hci0 --nodetach
```

The service unit is intentionally minimal. Bluetooth cleanup happens in `install-service.sh` before service start, not inside `ExecStartPre`, because helper commands such as `hciconfig` or `btmgmt` can block under systemd.

## Service checks

Check whether the service is running:

```bash
systemctl status sanlight-meshd-generic.service
```

Check whether BlueZ Mesh is visible on D-Bus:

```bash
busctl tree org.bluez.mesh
```

Expected:

```text
/org/bluez/mesh
```

Follow logs:

```bash
journalctl -u sanlight-meshd-generic.service -f
```

Run an environment summary:

```bash
bash ./scripts/sanlight-env-check.sh
```

## Python setup command

Normally `setup-all.sh` runs this for you. Manual command:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
  --cdb private/SANlightMesh.json \
  --iv-index 0 \
  setup
```

If you reset `/var/lib/bluetooth/mesh/*`, also remove the local PoC state tokens:

```bash
rm -f .sanlight-mesh-poc-*-state.json
```

Otherwise BlueZ may reject old tokens with:

```text
org.bluez.mesh.Error.NotFound: Attach failed
```

## Node address discovery

Addresses are installation-specific. Do not assume that `0002`, `0003`, `C000`, or `C001` exist in another SANlight mesh.

Use:

```bash
python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json list-nodes
```

This prints:

- SANlight lamp node unicast addresses detected from the CDB vendor model
- CDB groups
- example commands using the first detected lamp node

The generic JSON summary is also available:

```bash
python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json inspect
```

## Commands after setup

Read lamp time/brightness from a unicast lamp node:

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

Synchronize all detected SANlight lamp clocks to current local Raspberry Pi time:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json sync-now
```

Manual seconds since local midnight:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json set-uptime all 61258
```

The CLI accepts seconds. The script sends milliseconds on the wire because SANlight expects milliseconds since the lamp day start.

## Manual daemon start for debugging

The two-terminal foreground daemon mode is a debug fallback only.

Stop services and start the daemon in foreground:

```bash
sudo systemctl stop bluetooth.service
sudo systemctl stop bluetooth-mesh.service
sudo systemctl stop sanlight-meshd-generic.service
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

Use another terminal for Python commands while this debug daemon is running.

## Development notes

Make shell scripts executable in Git:

```bash
git update-index --chmod=+x scripts/install-service.sh
git update-index --chmod=+x scripts/setup-all.sh
git update-index --chmod=+x scripts/sanlight-env-check.sh
```

The repository also includes:

```gitattributes
*.sh text eol=lf
```

This avoids Windows CRLF line-ending problems in shell scripts.
