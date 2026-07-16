# End-to-end installation

This is the normal installation path. It creates one self-contained SANlight
gateway Raspberry Pi and connects it to one native ioBroker adapter instance.

The installer does **not** change lamp brightness or lamp time.

## Before you start

You need:

- a Raspberry Pi near the SANlight lamps;
- Raspberry Pi OS Lite 64-bit / Debian 13 `trixie`;
- the private `SANlightMesh.json` exported from the SANlight app;
- an ioBroker installation reachable over the same trusted LAN;
- a stable DHCP reservation or hostname for the gateway Pi.

Do not expose MQTT port `1883` to the internet. The default installation uses
username/password authentication without TLS and is intended for a trusted
private LAN or VLAN.

## 1. Clone the gateway repository

On the SANlight gateway Pi:

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/Nibbels/sanlight-mesh-mqtt-gateway.git
cd sanlight-mesh-mqtt-gateway
git switch main
git pull --ff-only
```

## 2. Add the private SANlight export

Copy the export to:

```text
private/SANlightMesh.json
```

![How to export the private SANlightMesh.json from the SANlight app](docs/export_private_sanlightmesh_json_from_app.png)

Protect it:

```bash
mkdir -p private
chmod 700 private
chmod 600 private/SANlightMesh.json
```

Never commit or publish this file. It contains Mesh keys and DeviceKeys.

## 3. Run the single gateway installer

```bash
sudo bash scripts/install-gateway.sh
```

For a normal installation, accept or enter:

- a stable gateway ID, for example `sanlight-pi`, `room-a` or `greenhouse`;
- a read-only refresh interval, normally `1800` seconds.

The installer then:

- installs BlueZ, Python, Paho MQTT, Mosquitto and MQTT client tools;
- validates the private CDB and runs the offline test suite;
- prepares or safely adopts the two local BlueZ identities;
- installs the exclusive `generic:hci0` Mesh service;
- configures a local authenticated Mosquitto broker;
- creates separate credentials for the gateway and ioBroker;
- installs and starts the MQTT gateway;
- prints the ioBroker connection settings;
- runs `sanlight-gateway doctor`.

A successful installation ends with:

```text
Doctor result: healthy
```

### IV Index prompt

An existing working BlueZ identity normally supplies the trusted IV Index. A
new CDB may also contain it.

If a genuinely fresh import has no trusted IV Index source, the installer stops
and requires an independently verified value:

```bash
sudo bash scripts/install-gateway.sh --iv-index VERIFIED_IV_INDEX
```

Do not guess the value. Detailed identity recovery rules are in
[INSTRUCTIONS.md](INSTRUCTIONS.md).

## 4. Save the ioBroker connection data

At the end, the installer prints:

- the gateway Pi LAN address;
- broker port `1883`;
- the generated ioBroker username;
- the gateway ID;
- the topic prefix/root;
- the command used to display the protected ioBroker password.

Display the password only when entering it into ioBroker:

```bash
sudo cat /etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt
```

Do not paste the password into chat, logs or issues. Delete temporary notes after
configuration.

## 5. Install the native ioBroker adapter

In ioBroker Admin:

1. Open **Adapters**.
2. Choose **Install from custom URL**.
3. Enter:

```text
https://github.com/Nibbels/ioBroker.sanlightmesh
```

4. Install the adapter.
5. Create one `sanlightmesh` instance for this gateway.

The generic ioBroker MQTT adapter is not required and should not be installed
for this integration.

## 6. Configure the adapter instance

Use the values printed by the gateway installer:

| Setting | Normal value |
|---|---|
| MQTT broker host | stable IP/hostname of the SANlight gateway Pi |
| MQTT broker port | `1883` |
| Use MQTT TLS | disabled for the documented trusted-LAN setup |
| MQTT username | generated `sanlight-iobroker-...` username |
| MQTT password | value from the protected password file |
| Topic prefix | `sanlightmesh/v1` |
| Gateway ID | exactly the ID chosen during gateway installation |
| Command lifetime | `30` seconds |
| Brightness debounce | `1000` ms |
| Explicit blackout | disabled initially |

Save the configuration and start the instance.

For another physical SANlight gateway, create another adapter instance and use
that gateway Pi's address, credentials and gateway ID.

## 7. Verify without changing brightness

On the gateway Pi:

```bash
sudo sanlight-gateway doctor
sudo sanlight-gateway status
```

In ioBroker, these states should become `true`:

```text
sanlightmesh.0.info.mqttConnected
sanlightmesh.0.info.gatewayOnline
sanlightmesh.0.info.protocolCompatible
sanlightmesh.0.info.connection
```

Detected lamps appear below:

```text
sanlightmesh.0.lamps
```

Use a lamp's `control.refresh` button for a read-only end-to-end test. A
successful result reports:

```text
command.lastStatus = verified
```

Only after the read path works should you test a small reversible brightness
change within `20..100`, then restore the original value.

## Updating an installed gateway

On the gateway Pi:

```bash
cd /path/to/sanlight-mesh-mqtt-gateway
git switch main
git pull --ff-only
git status --short
./scripts/run-tests.sh
sudo bash scripts/install-gateway.sh --reuse-existing
```

This keeps the CDB, BlueZ identity state, gateway ID, broker credentials and
refresh interval. The normal public installer never resets Mesh state.

Update the ioBroker adapter separately through its GitHub custom-URL installation
path. See that repository's `INSTRUCTIONS.md` for adapter updates and diagnostics.
