# Product architecture

## Two repositories

### `sanlight-mesh-mqtt-gateway`

Owns the lamp-side appliance:

- BlueZ Mesh lifecycle and D-Bus interaction;
- SANlight vendor protocol implementation;
- sequence-number continuity and replay-protection recovery;
- local CDB, AppKeys, DeviceKeys and BlueZ identity state;
- serialized command execution and strict readback;
- the local authenticated Mosquitto broker;
- MQTT API v1, retained state and result publication;
- systemd integration, installation, diagnostics and release archives.

### `ioBroker.sanlightmesh`

Owns the ioBroker integration:

- connection to one configured SANlight gateway broker per adapter instance;
- exact selection of one gateway ID per instance;
- Admin UI and encrypted broker password storage;
- typed gateway and lamp objects;
- requested versus verified state separation;
- command IDs, TTLs, pending state and final result correlation;
- node additions, renames and missing-node handling;
- ioBroker tests and release lifecycle.

The adapter must not contain Mesh keys, invoke the Python CLI, SSH into the
gateway or open BlueZ D-Bus connections.

## Default topology

```text
Lamps --Bluetooth Mesh--> SANlight gateway Pi
                           BlueZ + gateway + Mosquitto
                                      ^
                                      | MQTT over trusted LAN
                                      |
                           ioBroker adapter instance
```

The gateway process connects to `127.0.0.1:1883`. The ioBroker adapter connects
to a stable LAN IP or hostname of that gateway Pi.

The local-broker topology is the supported installation. The public installer
does not preserve or configure an external/shared broker topology. Such a
deployment requires an intentional fork or code/configuration change and its own
validation.

## Runtime contract

The only runtime contract between repositories is MQTT API v1:

```text
sanlightmesh/v1/<gateway-id>/
```

Breaking protocol changes require a new major topic root such as `v2`. Both
repositories may evolve internally without coordinated releases while the MQTT
major version remains compatible.

## Multiple gateways and adapter instances

One ioBroker adapter instance manages exactly one physical gateway ID and one
broker connection. This is intentional:

```text
sanlightmesh.0 -> room-a gateway Pi -> 192.168.1.31:1883 -> gateway ID room-a
sanlightmesh.1 -> room-b gateway Pi -> 192.168.1.32:1883 -> gateway ID room-b
sanlightmesh.2 -> greenhouse Pi    -> greenhouse.local:1883 -> gateway ID greenhouse
```

Each instance subscribes only to its exact configured root. It does not use
`sanlightmesh/v1/+/...` in normal operation. This prevents lamps from separate
grow rooms, buildings or organizations from appearing in one control tree by
accident.

Multiple adapter instances connect to the separate local brokers on their
corresponding gateway Pis. A custom shared-broker fork would still require one
distinct gateway ID and one adapter instance per gateway.

## Stable identity

MQTT v1 identifies a lamp by gateway ID plus four-digit Mesh address. A future
protocol revision may publish node UUID and topology revision. Until then, the
adapter must:

- use `<gateway-id>_<address>` or another collision-free internal key;
- keep the address as metadata;
- update displayed names without deleting objects;
- mark missing nodes unavailable rather than deleting scripts, aliases or
  history configuration.

## Command flow

```text
ioBroker control state (ack=false)
        |
        v
adapter validates and publishes a non-retained MQTT command
        |
        v
gateway serializes, applies safety policy and talks to BlueZ
        |
        v
gateway verifies readback and publishes result + retained node state
        |
        v
adapter updates reported state (ack=true)
```

The adapter may debounce commands, but the gateway remains the final authority
for range, confirmation, expiry, coalescing, rate limiting and sequence safety.

## Single-sender rule

Do not clone a running gateway installation and start both copies with the same
Bluetooth Mesh sender address and sequence state. Only one active gateway may
own a particular sender identity. High availability requires distinct
provisioned sender addresses and a separately designed coordination model.
