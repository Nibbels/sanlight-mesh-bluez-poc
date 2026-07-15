# End-to-end installation

This is the normal installation path for a clean **Raspberry Pi OS Lite 64-bit / Debian 13 trixie** host and for an existing host whose protected project `.state/` is missing.

The installer configures both local BlueZ identities and the always-on MQTT gateway. It does **not** change lamp time or brightness.

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

The wizard asks only for deployment-specific MQTT values: gateway ID, broker address, credentials, TLS choice and read-only refresh interval. App-ID 1, App-ID 2, repository path and the default `.state/` directory are internal invariants and are not normal prompts.

### IV Index handling

The installer accepts the IV Index from any mutually consistent trusted source:

- the private CDB;
- an existing validated BlueZ `node.json` identity;
- existing protected project state;
- an explicitly supplied `--iv-index` value.

If this is a genuinely fresh import and none of those sources contains the value, provide an independently verified value:

```bash
sudo bash scripts/install-gateway.sh --iv-index VERIFIED_IV_INDEX
```

Do not guess and do not assume `0` for another Mesh.

### Existing BlueZ identities with missing `.state/`

The installer stops the project services, derives each exact BlueZ path from the CDB provisioner UUID, validates DeviceKey, unicast address, token format and IV Index, and then reconstructs the normal mode-`0600` project state atomically. Optional fields such as `appKeys` are ignored.

It aborts instead of guessing when state is incomplete or inconsistent. It does not reset, copy or manually edit BlueZ databases.

## 4. Verify

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

Replace `NODE_ADDRESS` with a four-digit unicast address printed by `list-nodes`.

## Updates

Reuse the existing protected MQTT configuration and identity state:

```bash
git pull --ff-only
./scripts/run-tests.sh
sudo bash scripts/install-gateway.sh --reuse-existing
```

Do not use `--reset-mesh-state` for an update. That option is intentionally destructive and belongs only to a deliberate complete local reset documented in [INSTRUCTIONS.md](INSTRUCTIONS.md).
