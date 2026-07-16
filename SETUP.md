# Gateway installation

This is the normal first-time installation path for one SANlight gateway
Raspberry Pi. It stops after the gateway and its local MQTT broker are healthy.
The companion adapter is installed separately on the ioBroker host.

The installer does **not** change lamp brightness or lamp time.

## Before you start

You need:

- a Raspberry Pi near the SANlight lamps;
- Raspberry Pi OS Lite 64-bit / Debian 13 `trixie`;
- the private `SANlightMesh.json` exported from the SANlight app;
- an ioBroker installation reachable over the same trusted LAN;
- a stable DHCP reservation or hostname for the gateway Pi.

The default installation uses authenticated MQTT without TLS on port `1883`.
Use it only on a trusted private LAN or VLAN. Do not expose the port to the
internet.

## 1. Clone the repository

On the SANlight gateway Pi:

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/Nibbels/sanlight-mesh-mqtt-gateway.git
cd sanlight-mesh-mqtt-gateway
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

## 3. Run the installer

```bash
sudo bash scripts/install-gateway.sh
```

For a normal installation, choose:

- a stable gateway ID, such as `sanlight-pi`, `room-a` or `greenhouse`;
- a read-only refresh interval, normally `1800` seconds.

The installer validates the private export, runs the offline tests, prepares the
BlueZ identities, installs the services, configures the local broker, creates
scoped credentials and runs read-only diagnostics.

A successful installation ends with:

```text
Doctor result: healthy
```

### When an IV Index is requested

An existing working BlueZ identity normally supplies the trusted IV Index. A
new export may also contain it. If no trusted source exists, the installer stops
and requires an independently verified value:

```bash
sudo bash scripts/install-gateway.sh --iv-index VERIFIED_IV_INDEX
```

Do not guess the value. See [INSTRUCTIONS.md](INSTRUCTIONS.md) for the identity
state matrix and recovery rules.

## 4. Save the ioBroker connection data

The installer prints the gateway address, broker port, generated ioBroker
username, gateway ID, topic root and the command for reading the protected
password.

Display the password only while entering it into ioBroker:

```bash
sudo cat /etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt
```

Do not paste the password into chat, logs or issues. Delete temporary notes after
configuration.

## 5. Continue on the ioBroker host

Install and configure the native adapter using:

```text
https://github.com/Nibbels/ioBroker.sanlightmesh
```

Follow that repository's README. It owns the adapter configuration and the
first read-only end-to-end test. The generic ioBroker MQTT adapter is not
required for this integration.

## Verify the gateway later

```bash
sudo sanlight-gateway doctor
sudo sanlight-gateway status
```

Updates, service commands, CLI operations and recovery procedures are documented
in [INSTRUCTIONS.md](INSTRUCTIONS.md).
