# SANlight Mesh BlueZ PoC

Control SANlight Evo Bluetooth Mesh dimmers from a Raspberry Pi using BlueZ and Python.

![Visual overview of SANlight Bluetooth mesh control via Raspberry Pi](docs/sanlight_mesh_steuerung_ueber_raspberry_pi.png)

## What this project does

This project is a minimal proof of concept for controlling SANlight Bluetooth Mesh dimmers from Linux/BlueZ.

Validated capabilities:

- read current lamp time and brightness
- synchronize the internal lamp clock to Raspberry Pi local time
- set SANlight MaxBrightness, for example `68%`, without using the SANlight app

The SANlight app remains useful as a reference view, but the Raspberry Pi can send the validated Bluetooth Mesh commands directly.

## Setup

For a fresh Raspberry Pi setup, follow:

[SETUP.md](SETUP.md)

The short version after preparing the Raspberry Pi and copying your CDB file is:

```bash
sudo bash ./scripts/setup-all.sh
```

## Important

`private/SANlightMesh.json` is exported from the SANlight smartphone app and contains Bluetooth Mesh secrets. Never commit it, publish it, or paste it into issues.

## Requirements at a glance

The validated path is:

- Raspberry Pi OS Lite 64-bit / Debian 13 `trixie`
- BlueZ `5.82`
- Raspberry Pi 3 internal Bluetooth controller `BCM43438`
- `bluetooth-meshd` started with raw HCI I/O: `--io generic:hci0`

Read [SETUP.md](SETUP.md) before installing. More detailed notes and troubleshooting live in [INSTRUCTIONS.md](INSTRUCTIONS.md).

## Quick usage after setup

List your own lamp node addresses first:

```bash
python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json list-nodes
```

Read lamp time and brightness from a unicast node:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json get-live <NODE>
```

Sync all detected SANlight lamp clocks to Raspberry Pi local time:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json sync-now
```

Set MaxBrightness for one lamp. Values `0` and `1..19` are rejected for safety:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json set-max <NODE> 68
```

## Documentation

- [SETUP.md](SETUP.md) — minimal first-time Raspberry Pi setup
- [INSTRUCTIONS.md](INSTRUCTIONS.md) — detailed installation notes, options, and troubleshooting
- [AI_CONTEXT.md](AI_CONTEXT.md) — technical context for future debugging and AI-assisted continuation
