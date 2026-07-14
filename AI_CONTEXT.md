# AI_CONTEXT.md


## Address discovery / documentation rule

Do not hard-code `0002` / `0003` as generic SANlight node addresses in user-facing documentation. They were the unicast addresses in Stefan's CDB only:

- `0x0002`: `3-60 1.5 Master Links`
- `0x0003`: `3-60 1.5 Rechts`

Other installations may use different unicast addresses and group addresses. Tell users to run:

```bash
python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json list-nodes
```

or `inspect` before using `get-live`, `set-max`, `set-time`, or `sync-now`.

This file is a compact technical context for continuing the SANlight Bluetooth Mesh PoC from the known-good point.

## Goal

Control two SANlight EVO dimmers from a Raspberry Pi through Bluetooth Mesh without the SANlight app, initially for:

- reading lamp time / live brightness (`get-live`),
- setting MaxBrightness in the safe range `20..100`,
- syncing the internal SANlight lamp clock after power loss (`sync-now`, `set-time`).

Future goal: minimal service / ioBroker integration.

## Working hardware / OS / BlueZ state

Known-good test state:

- Raspberry Pi 3 with internal Broadcom `BCM43438` Bluetooth controller on UART `hci0`.
- Raspberry Pi OS Lite 64-bit, Debian 13 `trixie`.
- Kernel observed in successful test: `6.18.34+rpt-rpi-v8`.
- BlueZ observed in successful test: `5.82`.
- `bluetooth-meshd` must be started with raw HCI I/O:

```bash
sudo /usr/libexec/bluetooth/bluetooth-meshd --io generic:hci0 --nodetach --debug
```

Important negative finding:

- Bookworm / BlueZ 5.66 / default MGMT I/O on the same Pi produced BlueZ `Mesh Send Complete` logs but no externally visible Mesh `2A` / `2B` packets on a Shelly scanner.
- The fix was not AppKey/opcode/TTL/source-address; the fix was using Trixie/BlueZ 5.82 plus `--io generic:hci0`.

## Mesh identities from CDB

The SANlight app CDB contains two relevant provisioners:

- Control/config identity: `SANlight Provisioner 1`, App-ID 1, unicast `0x2400`.
- Canonical sender identity: `SANlight Provisioner 2`, App-ID 2, unicast `0x2800`.

The PoC imports/attaches both. Application commands are sent from `0x2800`.

Known SANlight nodes:

- `0x0002` = `3-60 1.5 Master Links`
- `0x0003` = `3-60 1.5 Rechts`

Known groups from CDB:

- `0xC000` = `Rechts`
- `0xC001` = `Links`

Prefer unicast writes during testing.

## Vendor model and opcodes

SANlight Company ID:

- `0x0A8B`

Vendor model:

- Company `0x0A8B`, model `0x0001`

Validated opcodes:

- `0x06` Set Max Brightness, access PDU prefix `c6 8b 0a`, payload 1 byte percent.
- `0x07` Set Max Brightness Status, access PDU prefix `c7 8b 0a`.
- `0x0A` Set Uptime, access PDU prefix `ca 8b 0a`, payload uint32 little-endian milliseconds since local lamp day start.
- `0x0B` Set Uptime Status, access PDU prefix `cb 8b 0a`.
- `0x0C` Get Uptime and Brightness, access PDU `cc 8b 0a`.
- `0x0D` Get Uptime and Brightness Status, access PDU prefix `cd 8b 0a`.

Important correction:

- The SANlight SetUptime payload is milliseconds since day start, not seconds.
- CLI `set-uptime` accepts seconds and converts to milliseconds on the wire.
- `set-time` and `sync-now` compute milliseconds since local midnight.

## Validated command behavior

Setup:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json --iv-index 0 setup
```

Expected:

- control identity import/attach OK,
- canonical sender import/attach OK,
- AppKey 0 imported/bound,
- vendor model binding confirmed,
- Default TTL set to `5`,
- `SETUP OK`.

Read live state:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json get-live 0003
```

Validated response example:

- status opcode `0x0D` from `0x0003` to `0x2800`,
- first uint32 interpreted as milliseconds since lamp day start,
- uint16 interpreted as live/profile brightness-related value.

Set MaxBrightness:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json set-max 0003 68
```

Validated effect:

- `0003` changed App value to `Rechts 68%`.
- Setting both `0002` and `0003` to `68` resulted in App values `Mesh 68%, Rechts 68%, Links 68%`.

Set time manually:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json set-time all 10:38:30
```

Validated behavior:

- Sends `38310000 ms` (`10:38:30.000`) to both nodes.
- Both nodes returned SetUptime Status `0x0B` in the successful test.
- A following `get-live` showed about `38320124 ms`, i.e. the clock advanced plausibly.

Sync to current Pi time:

```bash
sudo python3 sanlight_canonical_sender_poc.py --cdb private/SANlightMesh.json sync-now
```

Validated behavior:

- Computes local system time as milliseconds since local midnight.
- Example: `17:00:58.301` -> `61258301 ms`.
- A following `get-live` from `0003` showed about `61265168 ms`, matching the expected passage of time.

## Runtime and files

Secrets and state:

- `private/SANlightMesh.json` contains NetKey/AppKey/DeviceKey material.
- `.sanlight-mesh-poc-provisioner-state.json` contains local BlueZ token/state.
- `.sanlight-mesh-poc-appid2-sender-state.json` contains local BlueZ token/state.
- `/var/lib/bluetooth/mesh` contains BlueZ local mesh node state.

Do not commit or share any of these.

Minimal files needed in the repository:

- `sanlight_canonical_sender_poc.py`
- `sanlight_protocol.py`
- `INSTRUCTIONS.md`
- `AI_CONTEXT.md`
- `.gitignore`
- `private/.gitkeep`
- optional `systemd/sanlight-meshd-generic.service.example`
- optional `scripts/start-meshd-generic.sh`

No logs, APKs, screenshots, pycache, backups, or CDB files belong in the repository.

## Open points / productization TODO

- Convert PoC into a small service/API rather than repeated CLI process startup.
- Add idempotent startup behavior: start mesh daemon, ensure setup, then expose commands.
- Add periodic `sync-now`, especially after power loss or gateway restart.
- Add MaxBrightness scaling logic for both nodes, bounded `20..100`.
- Add ioBroker integration or a simple local HTTP/MQTT bridge.
- Decide whether to preserve the DECT200 midnight hard-reset as fallback or replace it with `sync-now`.
- Add structured JSON output mode for automation consumers.
