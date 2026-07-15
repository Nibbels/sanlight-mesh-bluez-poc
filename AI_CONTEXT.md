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
- Unicast `set-max` may retry the exact same idempotent value once after a lost
  `0x07` acknowledgement, but must never perform an unbounded write loop.
- A `0x07` status counts only when source node, AppKey index and response
  destination match the active transaction. It is an acknowledgement, not the
  final configured-value proof.
- Every unicast `set-max` must finish with a read-only GetMaxBrightness query. A
  valid `0x09` response must come from the requested node, use the expected
  AppKey, target the canonical sender, contain exactly one byte and report a
  value in `20..100`.
- Readback may retry once. A matching value returns `0`; missing readback returns
  `3`; a persistent valid mismatch returns `4`. Readback retries must never
  trigger additional writes.
- Standalone `get-max` is read-only and follows the same strict status matching
  and bounded retry rules.
- Group `set-max` is transmitted once because member responses cannot establish
  group-wide confirmation; automatic group-wide readback is not claimed.
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
  protocol.py                     pure PDU, status decoding and clock helpers
  max_brightness_policy.py        bounded write/readback and status-match policy
  set_max_policy.py               compatibility re-export for the v6 module name
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
- GetMaxBrightness Status: `C9 8B 0A <PERCENT>`; the validated form has exactly one byte. Reported `0` means off, `20..100` is the supported on-range, and `1..19` is retained as an unexpected diagnostic.
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

The installer starts the service asynchronously and polls the actual `org.bluez.mesh.Network1` interface with `busctl introspect org.bluez.mesh /org/bluez/mesh org.bluez.mesh.Network1` for up to 25 seconds. Do not pass an object path to `busctl tree`; `tree` accepts service names there and caused a false timeout on a clean trixie installation even though BlueZ had already logged `Added Network Interface on /org/bluez/mesh`. Failure prints status and recent journal lines.

## Testing expectations

Before packaging or committing:

```bash
./scripts/run-tests.sh
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

## Sequence continuity and replay recovery

Bluetooth Mesh Sequence Number is 24-bit (`0..0xFFFFFF`), while IV Index is 32-bit and network-wide. Sequence Number must never wrap to zero under the same IV Index. A proper IV Update advances IV Index and permits sequence counters to restart; this project does not yet initiate IV Update because the SANlight network-wide behavior has not been validated.

A clean SD-card test proved a real migration failure: control App-ID 1 at `0x2400` could exchange DeviceKey Config messages with lamp `0x0002`, while canonical sender App-ID 2 at `0x2800` received no reply over either DeviceKey or AppKey. Advancing only the stopped BlueZ sender `sequenceNumber` from a fresh low value to `0x100000` restored both `get-net-tx-sender` and SANlight `get-live`. This confirms persistent receiver Replay Protection List state for the reused source address.

Project rules:

- setup must not alter Sequence Number automatically;
- use `scripts/diagnose-replay.sh NODE_ADDRESS` for the read-only two-identity probe;
- each diagnostic identity must be retried before classification; a clean-image
  test produced one transient canonical-sender timeout immediately followed by a
  successful standalone probe, so one missing Config Status is not sufficient
  evidence of replay protection;
- use `show-sender-state` for live non-secret Node1 IV/sequence properties;
- `recover-sequence` is explicit, root-only, forward-only, backed up, atomic, and requires `--confirm-replay-recovery`;
- recovery targets are valid only in `1..0xBFFFFF`; protocol maximum remains `0xFFFFFF`;
- never edit BlueZ `node.json` while `bluetooth-meshd` is running;
- never claim that a lamp power cycle clears replay state;
- a remembered `0xFFFFFF` cannot be outrun; stop the source, then use coordinated IV Update or a complete Mesh/CDB rebuild;
- the destructive fallback is SANlight dimmer factory reset plus complete Mesh/CDB rebuild;
- do not implement manual IV Index increments as a shortcut. IV Update is a coordinated network procedure.

The receiver's exact RPL threshold is not exposed by standard Config Models or ordinary advertisements. A key-assisted packet capture can reveal a transmitted Network PDU's sequence, not a lamp's internal stored threshold.

## MaxBrightness write/readback and blackout invariants

Hardware validation on both lamp nodes confirmed:

- `get-max` (`C8 8B 0A`) returns a strict `C9 8B 0A <PERCENT>` status;
- `set-max 0003 48` returned `0x07`, then `get-max` read back `48`;
- restoring `68` returned `0x07`, then `get-max` read back `68`;
- a missing `0x07` can occur even when the lamp applied the value, so readback is authoritative;
- one read-only query required its second bounded attempt during validation, confirming that a single missing status must not be overinterpreted.

Safety rules:

- ordinary `set-max` remains strictly `20..100`; never weaken it to accept zero;
- `get-max` must decode `0..100`, because `0` is a legitimate reported off state;
- explicit 0% output uses only `blackout ... --confirm-blackout`;
- blackout must pre-read every selected unicast node, snapshot only nodes that will actually change, send 0 only to those nodes, and verify `get-max = 0`;
- an all-already-off blackout is a no-op and must not create a zero-value snapshot that shadows a useful restore point;
- blackout never uses a group destination internally, because one group response cannot verify every lamp;
- completed GetMax transactions must invalidate their timeout/retry generation before a write phase begins; stale preflight timers must never overlap brightness writes;
- restore validates Mesh/sender identity and CDB membership, skips already matching nodes, verifies every write, and marks the snapshot completed only after full success;
- `restore-blackout latest` selects the newest active snapshot that contains no legacy zero-value entries, so repeated restores unwind overlapping blackout operations in reverse order; ambiguous v8 snapshots remain available only by exact path;
- Q-Series Gen2 has a 20% minimum; 0% support must be confirmed by the operator for EVO/EVO COMPACT/STIXX hardware;
- 0% is commanded light output off, not electrical mains isolation.


Hardware validation of the first blackout implementation exposed two bugs that are now regression requirements:

- a completed preflight timeout could fire after the 0% write started, causing an overlapping stale GetMax retry and an ignored valid `0x09 = 0` response;
- creating snapshots for already-off nodes made `latest` point at a no-op 0% snapshot instead of the useful earlier restore point.

The runtime now uses generation invalidation between phases, snapshots only changed nodes, creates no snapshot for an all-off no-op, and treats completed snapshots as an undo stack.

## Outgoing traffic and sequence budget

Every new outgoing access/config message consumes one value from the sender's 24-bit Sequence Number space. Read-only queries consume sequence values too. A verified unicast `set-max` normally uses two messages (write + readback) and can use four when both bounded retries occur. At one verified command per second, the full space lasts only about 49..97 days from zero; a 90-day run can therefore exhaust it.

Project control policy:

- use event-driven updates and do not send unchanged values repeatedly;
- routine MaxBrightness automation should normally update once per minute or slower;
- never poll `get-max` or `get-live` every second;
- enforce a persistent 10-second minimum between separate brightness-write commands;
- `--allow-fast-control` is an explicit diagnostic override, not a normal control option;
- the guard is only a last-resort bug brake. It does not make 10-second automation the recommended cadence;
- the lamp-side profile remains responsible for smooth daily changes. Pi-side MaxBrightness is a coarse, infrequent limit.


## Next sensible milestones

After the clean-image installation is validated:

1. add a machine-readable `get-live --json` result without changing default output;
2. add an optional long-running service only after command-line reliability is established;
3. add time-drift monitoring as read-only behavior before any opt-in automatic synchronization;
4. integrate ioBroker/MQTT in a separate adapter layer, not inside protocol/CDB modules.

Automatic clock or brightness changes must remain explicit opt-in runtime behavior and must never become part of installation.


## MQTT gateway feature branch

Planned branch: `feature/mqtt-gateway`. The MQTT API is versioned independently under topic root `sanlightmesh/v1/<gateway-id>`.

Implemented gateway boundary:

- `sanlight_mqtt_gateway.py`: stable service entrypoint;
- `gateway_config.py`: strict mode-0600 TOML config;
- `gateway_protocol.py`: command validation, TTL and result envelope;
- `gateway_queue.py`: bounded serialization and same-node setpoint coalescing;
- `gateway_store.py`: atomic non-secret dedup and verified-state cache;
- `gateway_executor.py`: typed, no-shell bridge to the validated CLI engine;
- `mqtt_transport.py`: Paho connection, Last Will and retained state publishing;
- `gateway_service.py`: orchestration, no-op suppression, expiry and state publishing.

The MQTT service must never receive or publish CDB keys, DeviceKeys, BlueZ tokens, local file paths from clients, or arbitrary CLI options. Retained commands are rejected. Only verified values update retained node state.

The first implementation intentionally keeps `bluetooth-meshd` persistent while using isolated CLI child transactions. This avoids unvalidated long-lived D-Bus object reuse and preserves the existing runtime lock/retry/readback behavior. A later in-process executor may replace this without changing MQTT API v1.

A native ioBroker adapter is a separate future repository (`Nibbels/ioBroker.sanlightmesh`) and must depend only on MQTT API v1. Do not create it inside this Python repository or duplicate BlueZ logic there.
