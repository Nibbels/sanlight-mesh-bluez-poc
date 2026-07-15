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
- `.state/blackout-*.json` restore snapshots
- `.state/brightness-write-rate.json` safety state
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

The first column of the lamp table is named `NODE_ADDRESS`. It is the four-digit unicast address used by commands such as `get-live`. Addresses are installation-specific. Group addresses are listed separately and cannot be used by read-only node commands.

Read lamp time and the still-partially-understood brightness-related raw field from one unicast lamp node:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    get-live NODE_ADDRESS
```

Read the configured MaxBrightness percentage from one unicast lamp node:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    get-max NODE_ADDRESS
```

`get-max` sends SANlight GetMaxBrightness (`C8 8B 0A`) and requires a matching
status (`C9 8B 0A <PERCENT>`). It accepts only the requested source node, the
expected AppKey and a response addressed back to the canonical sender. The
status must contain exactly one byte in the reportable `0..100` range. `0` is
displayed as **off**; values `1..19` are preserved as unexpected diagnostics
instead of being silently discarded. A missing or malformed response is retried
once and never changes lamp state. The ordinary `set-max` command still rejects
`0` and accepts only `20..100`.

Read the Bluetooth Mesh Config Network Transmit setting from one unicast node:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    get-net-tx NODE_ADDRESS
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
or state tokens. It also shows rough sequence-budget estimates for high-frequency
control.

## Traffic frequency and Sequence Number budget

Every **new outgoing Bluetooth Mesh message** from the canonical sender consumes
one value from its 24-bit Sequence Number space (`0..0xFFFFFF`, 16,777,216
values per IV Index). This includes read-only queries such as `get-max` and
`get-live`; read-only does not mean sequence-free. Network retransmissions of the
same PDU are handled by the Mesh stack, but each new application query or retry
is a new message.

A successfully verified unicast `set-max` normally uses at least two outgoing
messages: the write and its GetMaxBrightness readback. With both bounded retries,
it can use up to four. At one verified update every second, the complete 24-bit
space would last only about **49 to 97 days** from zero. A 90-day cultivation run
at that rate can therefore exhaust the sender even without a software bug. The
Bluetooth SIG specifies IV Update as the standards-based way to obtain a fresh
sequence space, but this project does not initiate or automate a network-wide IV
Update. See the [Bluetooth Mesh Security Overview](https://www.bluetooth.com/wp-content/uploads/2025/04/MeshSecurityOverview_INFO_v1.0-1.pdf).

Project policy:

- use event-driven control and send only when the requested value meaningfully
  changes;
- do not poll `get-max` or `get-live` every second;
- for routine MaxBrightness automation, use **one minute or slower** unless a
  carefully reviewed use case requires otherwise;
- a one-minute verified update cadence over 90 days consumes roughly 259,200 to
  518,400 sequence values (about 1.5% to 3.1% of the full space);
- the CLI enforces a persistent **10-second minimum interval** between separate
  brightness-changing commands. This is an emergency guard against accidental
  tight loops, not a recommended control cadence;
- `--allow-fast-control` bypasses that guard and must only be used deliberately.

The lamp-side daily schedule should remain the primary fine-grained lighting
profile. Pi-side MaxBrightness control should adjust a coarse limit only when
there is a meaningful reason to do so.

## Writing commands

These commands intentionally change lamp state. They are never run by setup.

Set MaxBrightness for one CDB node or group:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    set-max DESTINATION_ADDRESS 68
```

For a unicast node, `set-max` uses two independent response layers:

1. It waits up to four seconds for a matching SANlight `0x07` acknowledgement.
   The acknowledgement counts only when source node, AppKey and response
   destination match the active transaction. If it is lost, the exact same
   idempotent value is sent one more time after a one-second delay.
2. Whether or not `0x07` was observed, the command then performs a read-only
   GetMaxBrightness query and compares the reported percentage with the
   requested value. A missing query response or a transient mismatch is queried
   once more. The write itself is never repeated because of a readback mismatch.

Successful unicast output ends with:

```text
SET-MAX VERIFIED. Node 0x1234 reports MaxBrightness 48% as requested.
```

The final exit status is:

- `0`: readback matched the requested percentage;
- `1`: local BlueZ/D-Bus failure;
- `2`: invalid command, destination or unsafe value;
- `3`: the write was sent but no valid readback could confirm it;
- `4`: the lamp replied with a valid but different MaxBrightness percentage on
  both readback attempts.

Exit code `3` does not prove that the write failed. Exit code `4` is a real
readback mismatch and must not be hidden by further automatic writes. Fully
closing and reconnecting the SANlight app remains a useful independent check;
the app may display a cached value until it reconnects.

A Mesh group write is sent only once. Responses from individual group members
cannot prove that every member applied the value, so group output is explicitly
reported as group-wide unconfirmed even when one or more statuses are observed.

### Explicit blackout and restoration

`set-max` intentionally never accepts zero. An intentional 0% output state uses
a separate, strongly confirmed command:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    blackout NODE_ADDRESS --confirm-blackout
```

Black out every detected SANlight lamp node individually:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    blackout all --confirm-blackout
```

Before sending any 0% command, `blackout` reads every selected node. It aborts
without writing when a current value cannot be read safely. It creates a
mode-`0600` restore snapshot under `.state/` containing **only nodes that this
invocation will actually change**, then sends 0% to those nodes and requires
`get-max = 0` from every changed node. Nodes that already report 0% are skipped
and are not added to the new snapshot. If every selected node is already off,
no write and no snapshot are created. The snapshot contains addresses and prior
percentages, not Mesh keys or state tokens. Keep it private because it still
describes the installation.

The blackout implementation serializes preflight reads, writes, acknowledgements,
and verification reads. Completed readback transactions invalidate their pending
timeouts before the next phase starts, preventing an old preflight retry from
overlapping a 0% write.

The official SANlight Bluetooth dimmer manual states that 0% (off) is supported
by EVO, EVO COMPACT, and STIXX dimmers, while Q-Series Gen2 dimmers have a 20%
minimum. `--confirm-blackout` means the operator has verified that the connected
dimmer series supports 0%. A blackout means zero commanded light output; it is
not electrical isolation from mains power. See the [SANlight Bluetooth Dimmer
manual](https://www.sanlight.com/wp-content/uploads/2023/03/sanlight-bt-dimmer-manual-2023-en.pdf).

Restore the newest snapshot:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    restore-blackout latest --confirm-restore
```

Or provide the exact protected snapshot path printed by `blackout`. Restoration
validates Mesh UUID, sender identity, CDB node membership, and every stored
percentage. It skips nodes that already match and verifies every value it writes.

Snapshots act as an undo stack. After a successful restore, the snapshot is
atomically marked completed but retained for audit. A later `restore-blackout
latest` selects the newest **active** snapshot instead of replaying one that was
already restored. Repeating `restore-blackout latest` therefore unwinds multiple
blackout operations in reverse order. An exact snapshot path can still be
reapplied deliberately; the CLI prints that it was previously completed.

This matters when blackouts overlap. Example: black out one node, then run
`blackout all`. The second snapshot contains only the other nodes that changed.
Restoring `latest` first undoes the second operation; running it again restores
that node from the earlier snapshot. Remove old snapshot files manually only
after the lamps have been independently checked.

Compatibility note: snapshots created by the older blackout implementation may
contain entries whose stored value is `0`. Those files are ambiguous undo steps
and are intentionally skipped by `restore-blackout latest`; they remain usable
only through an exact path. This prevents a legacy no-op snapshot from silently
turning a restored lamp off again.

A recent brightness write may trigger the 10-second safety guard. Wait for the
reported remaining interval. Use `--allow-fast-control` only for a deliberate
hardware test, not as normal automation.

Set one lamp clock to an explicit local clock value:

```bash
sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    set-time NODE_ADDRESS 10:38:30
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
    sync-now NODE_ADDRESS --offset-ms 250
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

Use the merged `main` branch for installed systems:

```bash
git switch main
git fetch --prune origin
git pull --ff-only
git status --short
./scripts/run-tests.sh
```

Reinstall the BlueZ service definition after relevant changes to `scripts/` or `systemd/`:

```bash
sudo ./scripts/install-service.sh
```

When the MQTT gateway is installed, also reinstall its unit after gateway, installer or systemd changes:

```bash
sudo bash ./scripts/install-mqtt-gateway.sh \
    --config private/sanlight-gateway.toml
```

Neither installer resets Mesh state unless a reset option is explicitly supplied.

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
    --iv-index VERIFIED_IV_INDEX \
    --reset-mesh-state
```

### CDB has no `ivIndex`

Obtain the current IV Index from the known working Mesh context. Do not guess. Pass it explicitly:

```bash
sudo bash ./scripts/setup-all.sh --iv-index VERIFIED_IV_INDEX
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
sudo bash ./scripts/diagnose-replay.sh NODE_ADDRESS
```

The script probes both identities and gives each path up to two attempts. It also
pauses briefly between the short-lived D-Bus application processes. A single
missing Config Status reply is **not** classified as replay protection because a
valid Bluetooth Mesh response can occasionally be lost or arrive outside the
10-second observation window.

Interpret the result only after the retries:

- control identity responds and canonical sender does not after both attempts:
  likely reused-sender replay state;
- both respond: sender sequence state is accepted;
- neither responds after both attempts: investigate RF, IV Index, keys, service,
  and controller ownership instead.

A negative result remains a strong diagnostic indication, not mathematical
proof. The script prints a restricted, non-secret summary of failed attempts so
that a transient timeout is visible before any recovery is considered.

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
sudo bash ./scripts/diagnose-replay.sh NODE_ADDRESS

sudo python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    get-live NODE_ADDRESS
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

- [Bluetooth Mesh Protocol specification](https://www.bluetooth.com/specifications/specs/mesh-protocol-1-1-1/)
- [Bluetooth Mesh Security Overview](https://www.bluetooth.com/wp-content/uploads/2025/04/MeshSecurityOverview_INFO_v1.0-1.pdf)
- [BlueZ Mesh D-Bus API](https://bluez.readthedocs.io/en/latest/mesh-api/)
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

The suite checks protocol bytes, brightness safety, CDB consistency, destination restrictions, state permissions and atomic writes, redacted output, CLI prevalidation, replay-diagnostic safety, 24-bit sequence bounds, forward-only recovery, protected backups, MQTT protocol validation, queue behavior, deduplication, retained-command policy and token-output patterns.

During the completed MQTT hardware validation on 2026-07-15, 97 tests passed on the target Linux host. The exact count may increase as regression coverage grows; passing the current suite is authoritative.

## Optional MQTT edge gateway

For an ioBroker host outside Bluetooth range, keep this Raspberry Pi near the lamps and run the merged MQTT service from `main`. The lamp-side Pi remains the only host containing the private CDB and BlueZ state.

Configuration, installation and operation are documented in [docs/MQTT_GATEWAY.md](docs/MQTT_GATEWAY.md). The versioned broker contract is in [docs/MQTT_API.md](docs/MQTT_API.md), the completed hardware validation is in [docs/MQTT_TEST_PLAN.md](docs/MQTT_TEST_PLAN.md), and the validated generic ioBroker path is in [docs/IOBROKER_INTEGRATION.md](docs/IOBROKER_INTEGRATION.md).

The gateway keeps one MQTT connection and one serialized command queue. `bluetooth-meshd` remains persistent. Each queued command invokes the hardware-validated CLI transaction engine through a fixed argument vector; it never invokes a shell and MQTT cannot supply executable paths or arbitrary options.

The gateway implementation has been hardware validated for read-only refresh, verified set/restore, duplicate delivery, command expiry, retained-message rejection, offline retained-command suppression, coalescing, blackout/restore, persistent rate limiting, broker restart, gateway restart, full Raspberry Pi reboot and generic ioBroker operation.

Important automation rules:

- command topics are never retained;
- QoS 1 duplicates are deduplicated by command ID, including after gateway restart;
- every command has a creation time and short TTL;
- rapid pending `set-max` updates for one node are coalesced;
- cache-only no-op suppression is disabled by default because the SANlight app may also write;
- writes remain subject to the persistent ten-second guard;
- routine automation should normally update no faster than once per minute;
- periodic refresh defaults to 30 minutes and can be disabled;
- gateway logs are unbuffered under systemd and should appear immediately.

Do not map a per-second sensor loop or an un-debounced UI slider directly to Mesh commands. Read-only polling also consumes Sequence Numbers.
