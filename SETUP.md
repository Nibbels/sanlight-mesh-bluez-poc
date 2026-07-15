# End-to-end installation

This is the normal installation path for a clean **Raspberry Pi OS Lite 64-bit /
Debian 13 trixie** lamp-side host and for an existing host whose protected
project `.state/` is missing.

The single installer configures:

- both local BlueZ Mesh identities;
- the persistent SANlight MQTT gateway;
- a local authenticated Mosquitto broker;
- separate gateway and ioBroker MQTT users with gateway-scoped ACLs.

It does **not** change lamp time or brightness.

## 1. Clone the repository

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/Nibbels/sanlight-mesh-mqtt-gateway.git
cd sanlight-mesh-mqtt-gateway
git switch main
git pull --ff-only
```

## 2. Copy the private SANlight export

Export the private Mesh file in the SANlight app and copy it to:

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

Never publish this file. It contains Mesh keys and DeviceKeys.

## 3. Run the complete installer

```bash
sudo bash scripts/install-gateway.sh
```

The wizard asks only for:

- a stable gateway ID, such as `room-a` or `sanlight-pi`;
- the read-only refresh interval.

The broker is installed on this SANlight gateway Pi. The gateway automatically
uses `127.0.0.1:1883`; no separate broker host, username, password or TLS prompt
is required for the normal setup.

The installer prints the remote ioBroker settings when it finishes. The
ioBroker password remains in a protected root-only file and can be displayed
with the exact command printed by the installer.

### IV Index handling

The installer accepts the IV Index from any mutually consistent trusted source:

- the private CDB;
- an existing validated BlueZ `node.json` identity;
- existing protected project state;
- an explicitly supplied `--iv-index` value.

If this is a genuinely fresh import and none of those sources contains the
value, provide an independently verified value:

```bash
sudo bash scripts/install-gateway.sh --iv-index VERIFIED_IV_INDEX
```

Do not guess and do not assume `0` for another Mesh.

## 4. Configure ioBroker

In ioBroker Admin, use **Install from custom URL** with:

```text
https://github.com/Nibbels/ioBroker.sanlightmesh
```

Then create one `ioBroker.sanlightmesh` adapter instance for this physical
gateway. The generic ioBroker MQTT adapter is not required. Configure the native
instance with:

- broker host: a stable LAN IP or hostname of this SANlight gateway Pi;
- broker port: `1883`;
- username and password printed/referenced by the installer;
- gateway ID entered during installation.

For another SANlight gateway Pi, create another ioBroker adapter instance.
Do not combine multiple physical gateways in one adapter instance.

See [docs/IOBROKER_INTEGRATION.md](docs/IOBROKER_INTEGRATION.md).

## 5. Verify

```bash
sudo sanlight-gateway doctor
sudo sanlight-gateway status
```

List CDB-derived lamp addresses:

```bash
python3 sanlight_canonical_sender_poc.py \
  --cdb private/SANlightMesh.json \
  list-nodes
```

An explicit read-only lamp query remains available:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
  --cdb private/SANlightMesh.json \
  get-live NODE_ADDRESS
```

Replace `NODE_ADDRESS` with a four-digit unicast address printed by
`list-nodes`.

## Updates

Reuse the existing protected CDB, broker credentials, MQTT configuration and
identity state:

```bash
git pull --ff-only
./scripts/run-tests.sh
sudo bash scripts/install-gateway.sh --reuse-existing
```

The normal public installer never resets Mesh state. Destructive reset options
exist only in lower-level maintenance helpers documented in
[INSTRUCTIONS.md](INSTRUCTIONS.md).

### Migration from the former external-broker setup

Running the update command against an older gateway TOML that points to a broker
on the ioBroker host automatically preserves the gateway ID, CDB/state paths and
refresh interval, but migrates MQTT to the local broker and generates new
credentials. After installation, replace the ioBroker adapter's former broker
host and credentials with the settings printed by the gateway installer.
