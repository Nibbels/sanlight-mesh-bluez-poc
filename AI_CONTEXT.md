# AI continuation context

## Project objective

This repository controls SANlight EVO Bluetooth Mesh dimmers from a Raspberry Pi through BlueZ. The immediate objective is a small, robust and auditable command-line project—not an always-on automation service.

The current validated host path is:

- Raspberry Pi OS Lite 64-bit / Debian 13 trixie
- BlueZ 5.82
- internal Raspberry Pi Bluetooth controller exposed as `hci0`
- `bluetooth-meshd --io generic:hci0 --nodetach`
- exclusive controller use by `sanlight-meshd-generic.service`

Do not replace this with the default BlueZ mesh service or a different I/O backend without a separately validated test.

## Non-negotiable security invariants

Never print, commit, publish or paste:

- `private/SANlightMesh.json`
- NetKey
- AppKey
- DeviceKey
- BlueZ `JoinComplete`/attach token values
- the contents of `.state/*.json`
- the BlueZ Mesh database

Safe diagnostic output may contain mesh UUID, provisioner UUID/name, App-ID, unicast addresses, group names, node names, opcodes and access PDUs. Access PDUs built by the CLI do not contain NetKey/AppKey/DeviceKey.

State writes must remain atomic. `.state/` is mode `0700`; JSON state files are mode `0600`. Identity mismatch errors must not echo old or expected private values.

## Safety invariants

- MaxBrightness accepts only integer `20..100`.
- `0`, `1..19`, negative values and values above `100` must be rejected before D-Bus.
- `build_set_max_brightness_pdu()` must independently enforce the same range.
- `0xFFFF` is rejected.
- Destinations must exist in the CDB.
- `get-live`, `get-net-tx`, `set-time`, `set-uptime` and targeted `sync-now` require unicast nodes.
- Destination `all` expands to individually detected SANlight vendor-model nodes; it is not a Mesh all-nodes broadcast.
- Setup must never call `set-max`, `set-time`, `set-uptime` or `sync-now`.
- Setup may configure the local canonical sender and set its Bluetooth Mesh Default TTL to 5.

## Repository architecture

```text
sanlight_canonical_sender_poc.py  stable compatibility entry point
sanlight_protocol.py              compatibility re-exports
sanlight_mesh/
  cli.py                          argparse, offline preflight and redacted output
  cdb.py                          strict CDB loading and destination validation
  protocol.py                     pure PDU and clock helpers
  state.py                        private atomic token-state storage
  locking.py                      exclusive single-process runtime guard
  bluez_runtime.py                D-Bus applications, elements and workflows
scripts/
  setup-all.sh                    ordered first-time setup
  install-service.sh              service installation and readiness check
  start-meshd-generic.sh          generic:hci0 launcher
  sanlight-env-check.sh           validated-platform checks
  run-tests.sh                    offline tests and static token-output scan
systemd/
  sanlight-meshd-generic.service.example
tests/                            standard-library unittest suite; fake keys only
```

Offline commands deliberately do not import `dbus` or `gi`. This allows CDB validation and tests before package installation.

## CDB identity model

The default identities are loaded by node name:

- control App-ID 1: `SANlight Provisioner 1`, typically primary unicast `0x2400`
- canonical sender App-ID 2: `SANlight Provisioner 2`, typically primary unicast `0x2800`

Addresses are CDB-derived and must not be hard-coded as universal. Both identities must share mesh UUID, primary NetKey index/key and primary AppKey index/key, while using distinct provisioner UUIDs and unicast addresses.

A SANlight lamp node is detected only when:

- node `cid` is `0A8B`; and
- an element contains vendor model ID `0A8B0001`.

This avoids treating provisioners or unrelated CDB nodes as lamps for destination `all`.

## Validated protocol material

Company ID: `0x0A8B`, encoded little-endian as `8B 0A` after a three-octet vendor opcode.

- SetMaxBrightness: opcode `0x06`, access prefix `C6 8B 0A`, one percent byte
- SetMaxBrightness Status: `C7 8B 0A`
- GetMaxBrightness: `C8 8B 0A`
- GetMaxBrightness Status: `C9 8B 0A`
- SetUptime: `CA 8B 0A` + uint32 little-endian milliseconds
- SetUptime Status: `CB 8B 0A`
- GetUptimeAndBrightness: `CC 8B 0A`
- GetUptimeAndBrightness Status: `CD 8B 0A`

A six-byte `0x0D` parameter body has been observed as:

- bytes 0..3: uint32 little-endian milliseconds since local midnight
- bytes 4..5: uint16 little-endian brightness-related raw value

Do not silently relabel the uint16 value as a confirmed percent without further protocol validation.

Bluetooth Mesh configuration PDUs used:

- Config Network Transmit Get: `80 23`
- Config Network Transmit Status: `80 25 <encoded>`
- Config Default TTL Set 5: `80 0D 05`
- Config Default TTL Status: `80 0E <ttl>`
- Config Model App Bind: `80 3D` + little-endian element/AppKey/company/model fields

## BlueZ setup workflow

1. Register local D-Bus application objects for control and sender.
2. Import or attach control App-ID 1.
3. Import primary NetKey and AppKey into control `Management1`.
4. Import or attach canonical sender App-ID 2.
5. Import the sender DeviceKey as a remote node into control `Management1`.
6. Add AppKey 0 to the sender when needed.
7. Bind AppKey 0 to vendor model `0x0A8B/0x0001`.
8. Set and confirm sender Default TTL 5.
9. Persist local BlueZ tokens without displaying them.

The binding callback is gated by remote DeviceKey readiness so that an asynchronous `UpdateModelConfiguration` signal cannot trigger a DevKey TTL message too early.

## Setup transaction ordering

`setup-all.sh` must preserve this order:

1. locate and chmod the private CDB;
2. run `inspect` and require IV Index information;
3. run compile and unit tests;
4. install packages;
5. validate environment;
6. install/start service and wait for `org.bluez.mesh` with a hard timeout;
7. execute local identity setup;
8. show read-only verification only.

`--reset-mesh-state` is explicit and occurs only after CDB preflight and tests. Never reintroduce an unconditional reset.

## Service lessons

A clean trixie image exposed a real failure because an earlier unit used `/usr/bin/rfkill`. Debian installs `rfkill` outside that path. The revised launcher:

- installs the `rfkill` package;
- uses a complete service `PATH` and `command -v rfkill`;
- treats unblock failure as non-fatal but verifies `hci0`;
- discovers `bluetooth-meshd` from known Debian locations;
- exits with a concise error before launching if prerequisites are missing.

The installer starts the service asynchronously and polls `busctl tree org.bluez.mesh /org/bluez/mesh` for up to 25 seconds. Failure prints status and recent journal lines.

## Testing expectations

Before packaging or committing:

```bash
bash ./scripts/run-tests.sh
```

Also inspect the archive:

```bash
unzip -l <archive>.zip
```

The archive must not contain:

- `SANlightMesh.json`
- `.state/`
- state JSON files
- logs or packet captures
- `__pycache__`
- real keys or token values

Hardware claims require a Raspberry Pi test. Container/unit tests can validate syntax, CLI behavior, CDB parsing, bytes and filesystem safety, but cannot prove D-Bus timing, HCI ownership or RF reception.

## Next sensible milestones

After the clean-image installation is validated:

1. add a machine-readable `get-live --json` result without changing default output;
2. add an optional long-running service only after command-line reliability is established;
3. add time-drift monitoring as read-only behavior before any opt-in automatic synchronization;
4. integrate ioBroker/MQTT in a separate adapter layer, not inside protocol/CDB modules.

Automatic clock or brightness changes must remain explicit opt-in runtime behavior and must never become part of installation.
