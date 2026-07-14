# First-time setup

This is the minimal installation path for a clean **Raspberry Pi OS Lite 64-bit / Debian 13 trixie** image. It installs the validated BlueZ 5.82 `generic:hci0` service and configures the two local Mesh identities.

**Setup does not change lamp time or brightness.** It only prepares local BlueZ identities, binds AppKey 0 to the SANlight vendor model and sets the local sender's Default TTL to 5.

## 1. Install Git and clone the repository

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/Nibbels/sanlight-mesh-bluez-poc.git
cd sanlight-mesh-bluez-poc
```

## 2. Copy the private SANlight CDB

Copy the SANlight app export to:

```text
private/SANlightMesh.json
```

Then protect it:

```bash
chmod 700 private
chmod 600 private/SANlightMesh.json
```

Never commit or publish this file. It contains the Mesh keys and DeviceKeys.

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

At the end, setup prints a table of detected SANlight lamp nodes. For example:

```text
Detected SANlight lamp nodes (unicast targets):
  NODE_ADDRESS  HEX_ADDRESS  NAME
  0002          0x0002       Example lamp
```

`NODE_ADDRESS` means the four-digit unicast address in the first column. It is not the literal word `NODE_ADDRESS`. Choose one address printed by your own setup, such as `0002` or `0003`. Do not use a group address such as `C000` or `C001` with `get-live`.

For example, when your table contains node address `0002`, run:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    get-live 0002
```

Replace `0002` with the `NODE_ADDRESS` shown for the lamp you want to read. This command is read-only and does not change lamp time or brightness.

A successful response reports SANlight status opcode `0x0D`, lamp milliseconds since midnight and the raw brightness-related value.

For all writing commands, service operation and troubleshooting, continue with [INSTRUCTIONS.md](INSTRUCTIONS.md).
