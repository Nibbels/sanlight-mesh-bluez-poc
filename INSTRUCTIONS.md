# Detailed instructions

## Scope and safety model

The project imports two provisioner identities from the private SANlight CDB:

- App-ID 1: local Configuration Client
- App-ID 2: canonical sender with SIG Configuration Client and SANlight vendor model `0x0A8B/0x0001`

The local setup configures BlueZ state, imports NetKey/AppKey material, binds AppKey 0 to the sender vendor model and sets sender Default TTL 5. It does **not** send a lamp time or brightness command.

The `set-max` command has two independent range checks. Only integer values `20..100` are accepted. `0`, `1..19`, negative values and values above `100` are rejected before D-Bus and again while building the access PDU.

`0xFFFF` is always rejected. Destinations must exist in `SANlightMesh.json`; read and time commands require unicast lamp nodes where documented.

## Validated environment

- Raspberry Pi OS Lite 64-bit / Debian 13 `trixie`
- BlueZ `5.82`
- `bluetooth-meshd --io generic:hci0`
- exclusive use of `hci0` by the custom Mesh daemon
- Python 3 with `dbus` and `gi.repository.GLib`

Run the environment check:

```bash
sudo ./scripts/sanlight-env-check.sh
```

The unsupported-platform override exists for development only:

```bash
sudo ./scripts/sanlight-env-check.sh --allow-unsupported
```

## Installation behavior

The complete setup performs these stages in order:

1. secure and semantically validate the CDB;
2. require an IV Index when the CDB omits it;
3. compile Python and run offline tests;
4. install Debian packages, including `rfkill`;
5. verify trixie, 64-bit ARM, BlueZ 5.82, `hci0`, D-Bus and GLib;
6. install and start `sanlight-meshd-generic.service`;
7. configure the local control and sender identities;
8. print only read-only verification guidance.

No state is reset by default. On a clean image, use the normal setup command. An explicit reset is reserved for repairing inconsistent local BlueZ state:

```bash
sudo bash ./scripts/setup-all.sh \
    --iv-index 0 \
    --reset-mesh-state
```

The CDB and offline tests complete before this reset occurs.

## Local state and secrets

The following material is private:

- `private/SANlightMesh.json`
- NetKey, AppKey and every DeviceKey
- `.state/control-provisioner.json`
- `.state/canonical-sender.json`
- BlueZ Mesh database under `/var/lib/bluetooth/mesh`

The project state directory is mode `0700`; state files are atomically written with mode `0600`. Tokens are never printed during import or attach. A mode-`0600` runtime lock rejects concurrent commands that would compete for the same D-Bus object paths. The files are ignored by Git.

Check that no private file is staged:

```bash
git status --short
git check-ignore -v private/SANlightMesh.json .state/canonical-sender.json
```

## Read-only commands

List CDB-derived unicast and group addresses:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    list-nodes
```

The first column of the lamp table is named `NODE_ADDRESS`. It is the four-digit unicast address used by commands such as `get-live`, for example `0002` or `0003`. Group addresses such as `C000` are listed separately and cannot be used by read-only node commands.

Read lamp time and brightness from one unicast lamp node:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    get-live <NODE_ADDRESS>
```

Read the Bluetooth Mesh Config Network Transmit setting from one unicast node:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    get-net-tx <NODE_ADDRESS>
```

Show the canonical sender's live non-secret BlueZ state after attaching it:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    show-sender-state
```

This prints only sender addresses, IV Index, IV Update flag, Sequence Number,
remaining 24-bit sequence space, and seconds since Mesh traffic was last heard.
It does not read `node.json` while the daemon is running and does not print keys
or state tokens.

## Writing commands

These commands intentionally change lamp state. They are never run by setup.

Set MaxBrightness for one CDB node or group:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    set-max <NODE_OR_GROUP_ADDRESS> 68
```

Set one lamp clock to an explicit local clock value:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    set-time <NODE_ADDRESS> 10:38:30
```

Set all detected SANlight lamp nodes to an explicit clock value:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    set-time all 10:38:30
```

Synchronize all detected SANlight lamp clocks to Raspberry Pi local time:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    sync-now
```

Synchronize one node with an optional timing offset:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    sync-now <NODE_ADDRESS> --offset-ms 250
```

The Raspberry Pi timezone must be correct before `sync-now`:

```bash
timedatectl
sudo raspi-config
```

## Service operation

Status:

```bash
sudo systemctl status sanlight-meshd-generic.service
```

Recent logs:

```bash
sudo journalctl -u sanlight-meshd-generic.service -n 100 --no-pager
```

Follow logs:

```bash
sudo journalctl -fu sanlight-meshd-generic.service
```

Restart:

```bash
sudo systemctl restart sanlight-meshd-generic.service
```

Verify the D-Bus object:

```bash
busctl introspect org.bluez.mesh /org/bluez/mesh org.bluez.mesh.Network1
```

The service launcher discovers `rfkill` through `PATH`; it does not assume the incorrect `/usr/bin/rfkill` path. On Debian trixie, the package is installed by `setup-all.sh`.

## Updating the project

Before updating, make sure the CDB and state files remain ignored:

```bash
git status --short
git pull --ff-only
./scripts/run-tests.sh
```

Reinstall the service definition after changes to `scripts/` or `systemd/`:

```bash
sudo ./scripts/install-service.sh
```

This does not reset Mesh state unless `--reset-mesh-state` is explicitly supplied.

## Removing only the canonical sender

This removes the local App-ID-2 sender and its project state file. It does not reset lamps or the control identity:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    leave-sender
```

Run setup again to recreate it.

## Troubleshooting

### `rfkill: No such file or directory`

The revised setup installs the `rfkill` package and resolves the binary through `PATH`. Confirm:

```bash
command -v rfkill
```

Then reinstall the service:

```bash
sudo ./scripts/install-service.sh
```

### `org.bluez.mesh` is unavailable

Inspect service status and logs:

```bash
sudo systemctl status sanlight-meshd-generic.service
sudo journalctl -u sanlight-meshd-generic.service -n 100 --no-pager
```

Confirm that `hci0` exists:

```bash
ls -l /sys/class/bluetooth/hci0
rfkill list bluetooth
```

The installer disables the competing `bluetooth.service` and `bluetooth-mesh.service` because the validated `generic:hci0` path requires exclusive controller access.

### State identity mismatch

A state file belongs to a different CDB identity, App-ID or unicast address. Do not edit its token. On a disposable fresh installation, re-run the full setup with an explicit reset:

```bash
sudo bash ./scripts/setup-all.sh \
    --iv-index <VERIFIED_IV_INDEX> \
    --reset-mesh-state
```

### CDB has no `ivIndex`

Obtain the current IV Index from the known working Mesh context. Do not guess. Pass it explicitly:

```bash
sudo bash ./scripts/setup-all.sh --iv-index <VERIFIED_IV_INDEX>
```

### Replay protection after a fresh SD card

Bluetooth Mesh uses a **24-bit Sequence Number** (`0..0xFFFFFF`) together with
the network-wide **32-bit IV Index**. The Sequence Number does not safely wrap
to zero. Before it is exhausted, a standards-compliant Mesh performs an IV
Update; after the network completes that procedure, nodes can use Sequence
Number zero again under the new IV Index. This project does not initiate IV
Update because that is a network-wide operation that has not yet been validated
against SANlight dimmers.

A fresh Raspberry Pi or deleted `/var/lib/bluetooth/mesh` state can recreate the
same canonical sender unicast address with a low Sequence Number. Lamps that
have already accepted higher values from that address may silently reject the
new messages as replayed traffic. Power-cycling a lamp is not a reliable fix: a
Mesh Replay Protection List is security state and is expected to survive power
cycles. Losing the SANlight lamp clock after power loss is unrelated.

Run the combined read-only diagnosis with one detected lamp node:

```bash
sudo bash ./scripts/diagnose-replay.sh 0002
```

The script performs two Config Network Transmit Gets:

- control identity responds and canonical sender does not: likely reused-sender
  replay state;
- both respond: sender sequence state is accepted;
- neither responds: investigate RF, IV Index, keys, service, and controller
  ownership instead.

The exact highest Sequence Number stored inside a lamp cannot be queried through
a standard Bluetooth Mesh model or read from an ordinary BLE advertisement. A
packet capture with Mesh keys can reveal the Sequence Number carried by a
specific transmitted Network PDU, but not the receiver's internal replay limit.
Do not expose Mesh keys merely to inspect this.

#### Explicit local sequence recovery

Only use this after the diagnostic reports that the control identity works while
the canonical sender does not. Recovery advances the local sender to an
**absolute minimum**; it never decrements or resets the value and never changes
lamp time or brightness. The tested recovery target for this project is
`0x100000`:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    recover-sequence \
    --minimum 0x100000 \
    --confirm-replay-recovery
```

The command:

1. requires root and the validated Mesh service to be active;
2. takes the exclusive project runtime lock;
3. stops `bluetooth-meshd` before reading or writing its database;
4. verifies the CDB sender UUID and unicast address;
5. creates a mode-`0600` backup under
   `/root/sanlight-mesh-sequence-backups`;
6. atomically advances `sequenceNumber` only when the existing value is lower;
7. restarts the service even when recovery fails.

The protocol maximum is `0xFFFFFF`, not a 32-bit or 64-bit counter. A value such
as `2^64 - 5` cannot be represented in a Bluetooth Mesh Network PDU, and the
recovery parser rejects it before any service or file is touched. Sequence Number
must never overflow to zero under the same IV Index. As an additional project
policy, recovery refuses targets above `0xBFFFFF`, leaving the final range
untouched for a proper IV Update or a Mesh rebuild. Repeating the same
`--minimum` does not add the value again; it is an absolute lower bound. Do not
keep guessing progressively larger targets: use the tested `0x100000` once, then
stop and investigate if the sender is still rejected. Never edit `node.json` while
`bluetooth-meshd` is running.

The protected backup contains the complete local BlueZ node database, including
private Mesh material. Do not display, copy into a chat, commit, or publish it.

After recovery, verify with:

```bash
sudo bash ./scripts/diagnose-replay.sh 0002

sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    get-live 0002
```

#### Destructive reset to a fresh sequence space

There is no safe local-only command that resets the same sender to Sequence
Number zero under the same IV Index while receivers retain their replay state.
The standards-based non-destructive solution is a proper network-wide IV Update.
If a broken or compromised sender has already caused receivers to remember
`0xFFFFFF`, no larger 24-bit value exists: local sequence advancement cannot
recover that condition. Stop the offending sender, then perform a coordinated IV
Update or rebuild the Mesh. This project deliberately does not fake an IV Index
change or wrap the counter.

Until IV Update is validated for SANlight, the final recovery path is to rebuild
the SANlight Mesh.

SANlight's official Bluetooth Dimmer manual documents a factory reset by holding
the **red side of the magnetic key** against the dimmer's flat surface for at
least **15 seconds**. The reset removes that dimmer from the SANlight Mesh; it
becomes visible again and cannot dim the lamp until paired. The app also offers a
reset while connected. See the official manual:

<https://www.sanlight.com/wp-content/uploads/2023/03/sanlight-bt-dimmer-manual-2023-en.pdf>

Resetting only one dimmer clears only that device's local state. It does not make
Sequence Number zero safe for other lamps that still remember the old sender.
For a complete fresh sequence space, reset and reprovision every lamp that has
accepted traffic from the reused sender, create/pair a new Mesh in the SANlight
app, export a new `SANlightMesh.json`, replace the private CDB on the Pi, and then
perform an explicit local BlueZ state reset during setup. This is destructive:
old groups, schedules, addresses, keys, CDB data, and Pi state are no longer
authoritative. Back up the existing SANlight export and local state before
starting. A normal lamp power cycle is not a factory reset.

Authoritative references:

- [Bluetooth Mesh Protocol specification](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/MshPRT_v1.1/out/en/index-en.html)
- [Bluetooth Mesh Security Overview](https://www.bluetooth.com/wp-content/uploads/2025/04/MeshSecurityOverview_INFO_v1.0-1.pdf)
- [BlueZ Mesh D-Bus API](https://github.com/bluez/bluez/blob/master/doc/mesh-api.txt)
- [SANlight Bluetooth Dimmer operating instructions](https://www.sanlight.com/wp-content/uploads/2023/03/sanlight-bt-dimmer-manual-2023-en.pdf)

### A command transmits but no status is received

Bluetooth Mesh status replies are not guaranteed. Check:

- lamp power and distance;
- that the destination is a detected unicast node;
- service logs for controller or advertising errors;
- repeated `get-live` results;
- Config Network Transmit using `get-net-tx`.

`get-live` performs two attempts with a ten-second response window each. A missing status is reported without inventing a result.

## Offline verification

Run all tests without Mesh hardware:

```bash
./scripts/run-tests.sh
```

The suite checks protocol bytes, brightness safety, CDB consistency, destination restrictions, state permissions and atomic writes, redacted output, CLI prevalidation, replay-diagnostic safety, 24-bit sequence bounds, forward-only recovery, protected backups and token-output patterns.
