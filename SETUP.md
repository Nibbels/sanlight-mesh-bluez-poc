# First-time setup

This is the minimal installation path for a clean **Raspberry Pi OS Lite 64-bit / Debian 13 trixie** image. It installs the validated BlueZ 5.82 `generic:hci0` service and configures the two local Mesh identities.

**Setup does not change lamp time or brightness.** It only prepares local BlueZ identities, binds AppKey 0 to the SANlight vendor model and sets the local sender's Default TTL to 5.

## 1. Install Git and clone the repository

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/Nibbels/sanlight-mesh-bluez-poc.git
cd sanlight-mesh-bluez-poc
git switch main
git pull --ff-only
```

## 2. Export and copy the private SANlight CDB

In the SANlight app, export the private Mesh file and then copy it to:

```text
private/SANlightMesh.json
```

Export path in the SANlight app:

![How to export the private SANlightMesh.json from the SANlight app](docs/export_private_sanlightmesh_json_from_app.png)

Summary:

1. Open the menu and tap **Einstellungen** (**Settings**).
2. In **Mesh Wartung**, tap **Mesh exportieren**.
3. Copy the exported file to `private/SANlightMesh.json` in this repository.

Then protect it:

```bash
mkdir -p private
chmod 700 private
chmod 600 private/SANlightMesh.json
```

Never commit or publish this file. It contains private Mesh keys and DeviceKeys. Also never share MQTT passwords, BlueZ state tokens or files from `.state/` or `/var/lib/bluetooth/mesh`.

## 3. Run the complete setup

First inspect the CDB without printing secrets:

```bash
python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    inspect
```

When the output contains an `ivIndexInCdb` value, run:

```bash
sudo bash ./scripts/setup-all.sh
```

When the output says that the CDB has no `ivIndex`, pass the independently verified current Mesh IV Index. The Mesh validated during development used `0`:

```bash
sudo bash ./scripts/setup-all.sh --iv-index 0
```

Do not assume `0` for a different Mesh. The setup aborts before changing services when the required value is missing.

## 4. Perform a read-only verification

List the node addresses detected from your own CDB:

```bash
python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    list-nodes
```

Choose one four-digit **unicast** address from the SANlight lamp table. Do not use the literal placeholder below and do not use a group address.

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    get-live NODE_ADDRESS
```

Replace `NODE_ADDRESS` with the value printed by `list-nodes`. This command is read-only and does not change lamp time or brightness.

A successful response reports SANlight status opcode `0x0D`, lamp milliseconds since midnight and the raw brightness-related value.

If a clean SD-card installation transmits but receives no status, do not factory-reset lamps or edit BlueZ files immediately. Continue with the read-only replay-protection diagnosis in [INSTRUCTIONS.md](INSTRUCTIONS.md#replay-protection-after-a-fresh-sd-card). A reused sender identity can be rejected when its fresh local Sequence Number is lower than the value remembered by the lamps.

## 5. Optional MQTT gateway

The command-line setup above is sufficient for direct operation on the lamp-side Raspberry Pi. For an always-on LAN gateway and ioBroker integration, continue with:

- [docs/MQTT_GATEWAY.md](docs/MQTT_GATEWAY.md)
- [docs/IOBROKER_INTEGRATION.md](docs/IOBROKER_INTEGRATION.md)

For all writing commands, service operation and troubleshooting, continue with [INSTRUCTIONS.md](INSTRUCTIONS.md).
