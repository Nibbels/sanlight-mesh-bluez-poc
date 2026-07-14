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

The suite checks protocol bytes, brightness safety, CDB consistency, destination restrictions, state permissions and atomic writes, redacted output, CLI prevalidation and token-output patterns.
