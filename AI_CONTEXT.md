# AI continuation context

## Project objective

This repository controls SANlight EVO Bluetooth Mesh dimmers from a Raspberry Pi
through BlueZ. The product path is a self-contained lamp-side appliance:

```text
SANlight lamps <-Bluetooth Mesh-> gateway Pi
                                  BlueZ + Python gateway + local Mosquitto
                                                      ^
                                                      | trusted-LAN MQTT
                                                      |
                                             ioBroker adapter
```

The CLI remains the authoritative Mesh transaction engine. The MQTT service adds
serialized, versioned and auditable LAN integration without exposing Mesh
secrets. `scripts/install-gateway.sh` is the only public installer.

The validated host path is:

- Raspberry Pi OS Lite 64-bit / Debian 13 `trixie`;
- BlueZ 5.82;
- internal Raspberry Pi controller `hci0`;
- `bluetooth-meshd --io generic:hci0 --nodetach`;
- exclusive controller use by `sanlight-meshd-generic.service`.

Do not replace this with the default BlueZ Mesh service or a different I/O
backend without a separate hardware validation.

## Product topology and ioBroker instances

The normal installer puts Mosquitto on the same Pi as BlueZ and the gateway
service. The gateway client connects to `127.0.0.1:1883`. ioBroker connects to a
stable LAN IP/hostname of that Pi.

Multiple physical gateway Pis for separate SANlight Mesh installations are
intentional. The adapter contract is:

- one `ioBroker.sanlightmesh` instance manages exactly one gateway ID;
- one instance has one broker connection;
- each instance subscribes only to
  `sanlightmesh/v1/<configured-gateway-id>/...`;
- normal discovery must never wildcard and combine every gateway;
- separate rooms/buildings use separate gateway IDs, credentials and adapter
  instances;
- a custom shared-broker fork would still require one adapter instance per gateway.

The separate adapter repository is:

```text
https://github.com/Nibbels/ioBroker.sanlightmesh
```

The adapter must never use SSH, import the CDB, receive Mesh keys, invoke Python
CLI commands remotely, or duplicate BlueZ logic. MQTT API v1 is the only runtime
contract between repositories.

## Non-negotiable secret boundary

Never print, commit, publish or paste:

- `private/SANlightMesh.json`;
- NetKey, AppKey or DeviceKey values;
- BlueZ JoinComplete/attach token values;
- contents of `.state/*.json`;
- `/var/lib/bluetooth/mesh` contents;
- `/etc/sanlight-mesh-mqtt-gateway/mqtt-password.txt`;
- `/etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt`;
- Mosquitto password databases or broker credentials.

Safe diagnostics may contain Mesh UUID, provisioner UUID/name, the CDB-derived
SANlight App-ID relationship, unicast addresses, group names, node names, opcodes
and access PDUs. State writes remain
atomic. `.state/` is mode `0700`; JSON and clear-text password files are mode
`0600`.

## Local broker invariants

The public installer owns the dedicated local broker configuration:

```text
/etc/mosquitto/conf.d/sanlight-mesh-mqtt-gateway.conf
/etc/mosquitto/sanlight-mesh-mqtt-gateway.passwd
/etc/mosquitto/sanlight-mesh-mqtt-gateway.acl
```

Rules:

- install Mosquitto and clients in the same package phase as BlueZ/Paho;
- default listener is IPv4 TCP 1883 on the trusted LAN;
- gateway TOML uses `127.0.0.1:1883`;
- anonymous access is disabled;
- generate separate random gateway and ioBroker users;
- ACL every user to one exact gateway ID;
- do not define duplicate global persistence settings in the project fragment;
- require the validated Debian Mosquitto configuration to enable persistence;
- refuse to merge with unrelated listener/authentication fragments;
- do not expose port 1883 to the internet;
- TLS or external/shared brokers are unsupported custom forks, not alternate
  normal setup paths;
- pass secrets to `mosquitto_passwd` through a pseudo-terminal, never in argv;
- `--reuse-existing` preserves localhost/port-1883/TLS-disabled generated
  credentials; a legacy external-broker config is migrated to localhost while
  preserving gateway/CDB/state/refresh settings and generating new credentials;
- every successful public installation ends in the local-broker topology;
- a missing ioBroker password on repair may be regenerated, but the installer
  must clearly say that the adapter password must be updated.

Gateway ACL for ID `<id>`:

```text
read  sanlightmesh/v1/<id>/command
write sanlightmesh/v1/<id>/availability
write sanlightmesh/v1/<id>/gateway/#
write sanlightmesh/v1/<id>/nodes/#
write sanlightmesh/v1/<id>/result/#
```

ioBroker ACL:

```text
write sanlightmesh/v1/<id>/command
read  sanlightmesh/v1/<id>/availability
read  sanlightmesh/v1/<id>/gateway/#
read  sanlightmesh/v1/<id>/nodes/#
read  sanlightmesh/v1/<id>/result/#
```

## Installer transaction ordering

`scripts/install-gateway.sh` must preserve this high-level order:

1. resolve/protect CDB, config and state paths;
2. read an existing protected config when `--reuse-existing` is used;
3. prompt only for gateway ID and refresh interval on a normal new install;
4. install BlueZ, Python, Paho, Mosquitto and MQTT client packages once;
5. run offline compile/unit/source-security tests;
6. validate Raspberry Pi / BlueZ environment;
7. stop project services;
8. reconcile both exact CDB-derived identities with BlueZ storage;
9. install/start Mesh service and attach/import identities;
10. create/reuse gateway and ioBroker broker credentials;
11. write the dedicated Mosquitto password database, ACL and listener fragment;
12. restart and validate Mosquitto; anonymous access must fail;
13. write/validate the gateway TOML using localhost;
14. install/start the gateway service;
15. run read-only diagnostics and print ioBroker connection settings.

Installation must never send lamp brightness or clock commands. The public
installer must never expose `--reset-mesh-state`. Lower-level helpers retain
explicit destructive reset only for deliberate maintenance.

## CDB identity model

Default identities are loaded by CDB node name:

- control identity: `SANlight Provisioner 1`;
- canonical sender identity: `SANlight Provisioner 2`.

The SANlight smartphone app's proprietary **App-ID** setting appears to select
one of these controller/provisioner identities. In the validated export, App-ID
1 mapped to `SANlight Provisioner 1` at `0x2400`, while App-ID 2 mapped to
`SANlight Provisioner 2` at `0x2800`. The phone used App-ID 1 and the gateway's
proven command sender used the separate App-ID 2 identity.

Treat this as an observed mapping, not a universal address formula. Identity
names, UUIDs, DeviceKeys and unicast addresses must always be derived and
validated from the CDB. Do not infer App-ID 3 through 16 addresses. The current
historical CLI selectors are `0..15`, where `0` means `nRF Mesh Provisioner`;
they do not exactly mirror the app's visible `1..16` list. The supported
installer uses 1 and 2 only. Only one active controller may own a local identity
and its sequence state.

SANlight App-ID is not Bluetooth Mesh AppKey index or AID. Both local identities
share Mesh UUID, primary NetKey and AppKey material; the SANlight vendor model is
bound to Bluetooth Mesh AppKey index `0`. The identities still use distinct
provisioner UUIDs and unicast/source addresses.

A SANlight lamp node is detected only when node `cid` is `0A8B` and an element
contains vendor model `0A8B0001`.

## Identity-state adoption invariants

BlueZ 5.82 stores one
`/var/lib/bluetooth/mesh/<provisioner-uuid-without-hyphens>/node.json` per local
identity. Relevant top-level values include `token`, `IVindex`,
`sequenceNumber`, `deviceKey` and `unicastAddress`. Optional fields can differ;
the observed sender had `appKeys` while control did not. This is not corruption.

Recovery rules:

- derive paths only from expected CDB provisioner UUIDs;
- require private regular non-symlink root-owned files;
- validate DeviceKey and unicast without printing private values;
- validate token as uint64 hex and IV Index as uint32;
- require CDB/explicit/project/BlueZ IV values to agree;
- reconstruct only normal protected project token state;
- never identify an identity by `appKeys`, list shape or filesystem ordering;
- never alter `sequenceNumber` during adoption;
- project state present plus BlueZ state absent is a hard error;
- `node.json.bak` without `node.json` requires manual recovery;
- errors remain redacted.

State matrix, independently per identity:

| Project state | BlueZ state | Result |
|---|---|---|
| present | present | validate and attach |
| missing | present | validate, reconstruct state, attach |
| missing | missing | permit fresh import |
| present | missing | abort |
| mismatch | any | abort |

## SANlight protocol and command safety

Company ID is `0x0A8B`, encoded little-endian as `8B 0A` after a vendor opcode.

Validated access PDUs:

- SetMaxBrightness: `C6 8B 0A <percent>`;
- status: `C7 8B 0A`;
- GetMaxBrightness: `C8 8B 0A`;
- status: `C9 8B 0A <percent>`;
- SetUptime: `CA 8B 0A` + uint32 little-endian milliseconds;
- status: `CB 8B 0A`;
- GetUptimeAndBrightness: `CC 8B 0A`;
- status: `CD 8B 0A` plus observed uptime/brightness-related fields.

Do not relabel the partially understood uint16 brightness-related raw value as a
confirmed percentage.

Safety invariants:

- ordinary `set-max` accepts integer `20..100` only;
- `0`, `1..19`, negatives, values above 100 and `0xFFFF` are rejected before
  D-Bus and again in the PDU builder;
- destination must exist in the CDB;
- unicast `set-max` may retry the exact idempotent write once after a lost ack;
- matching source/AppKey/destination is required for an ack;
- readback is authoritative and may retry once;
- readback failure never triggers additional writes;
- group writes are transmitted once and never claimed as group-wide verified;
- explicit 0% uses only confirmed blackout workflow with pre-read, private
  snapshot and per-node verification;
- setup never calls write commands.

## Sequence continuity and replay recovery

Bluetooth Mesh Sequence Number is 24-bit (`0..0xFFFFFF`); IV Index is 32-bit and
network-wide. Sequence must never wrap under the same IV Index. The project does
not initiate IV Update because SANlight network-wide behaviour is not validated.

Project policy:

- setup never changes sequence automatically;
- use `scripts/diagnose-replay.sh NODE_ADDRESS` before recovery;
- retry both identities before classifying a timeout;
- `recover-sequence` is explicit, root-only, forward-only, backed up and atomic;
- never edit BlueZ state while `bluetooth-meshd` runs;
- never claim a lamp power cycle clears replay state;
- do not manually increment IV Index as a shortcut;
- only one active gateway may own a sender identity/sequence state.

Every outgoing application/config message consumes sequence space. Routine
MaxBrightness automation should normally update no faster than once per minute.
The persistent ten-second write guard is an emergency brake, not a recommended
cadence. Read-only polling also consumes sequence values.

## MQTT transport invariants

The gateway uses MQTT 5 and:

- subscribes with `retainAsPublished=true`;
- uses `retainHandling=DO_NOT_SEND` for command subscriptions;
- rejects live retained commands before decoding;
- uses clean sessions so offline commands are not queued;
- requires command ID, creation time and TTL;
- deduplicates QoS 1 redelivery across restart;
- persists in-flight state before execution;
- coalesces pending same-node setpoints;
- updates retained node state only after verified results;
- never accepts executable paths, arbitrary CLI options or local file paths from
  MQTT payloads;
- never publishes CDB/DeviceKey/BlueZ token/password material.

Do not weaken the transport back to MQTT 3.1.1. Retain-flag preservation was a
real safety issue found during validation.

## Testing expectations

Before packaging or committing:

```bash
./scripts/run-tests.sh
bash scripts/install-gateway.sh --help
```

Also inspect patch/release archives. They must not contain private CDB/state,
password files, logs, captures, bytecode or real key/token values.

Unit tests can prove syntax, parsing, policy and filesystem behaviour, but cannot
prove systemd, HCI ownership, D-Bus timing, RF behaviour, Mosquitto startup or
end-to-end ioBroker operation. Hardware claims require the target Raspberry Pi.

Hardware validation history:

- 2026-07-15: the earlier external-broker runtime was validated with two real
  lamps, retained-command safety, QoS 1 deduplication, TTL expiry, coalescing,
  rate limiting, blackout/restore, broker/gateway restart and full Pi reboot;
- 2026-07-16: the supported self-contained local-broker topology was validated
  on the target Raspberry Pi 3. The public installer adopted two intact BlueZ
  identities whose project `.state/` had been removed, installed local
  Mosquitto, created scoped credentials/ACLs, started all services and finished
  with a healthy doctor report;
- the native `ioBroker.sanlightmesh` adapter was installed on a separate
  Raspberry Pi 4, connected to the gateway broker, reported MQTT/gateway/API
  health, completed a verified read-only refresh and performed reversible
  68% -> 67% -> 68% writes on both real nodes with independent SANlight-app
  confirmation.

The reference gateway run passed 124 offline tests and the static token-output
scan. The adapter run passed TypeScript checking, eight protocol unit tests and
package validation. Do not generalise these hardware claims to other SANlight
firmware, Mesh layouts or network-security topologies without evidence.
