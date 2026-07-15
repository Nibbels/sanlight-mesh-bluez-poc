# Product architecture

## Two repositories

### `sanlight-mesh-mqtt-gateway`

Owns the lamp-side edge appliance:

- BlueZ Mesh lifecycle and D-Bus interaction;
- SANlight vendor protocol implementation;
- sequence-number continuity and replay-protection recovery;
- local CDB, AppKeys, DeviceKeys and BlueZ identity state;
- serialized command execution and strict readback;
- MQTT API v1, retained state and result publication;
- systemd integration, installation, diagnostics and release archives.

### `ioBroker.sanlightmesh`

Owns the ioBroker integration:

- connection to an MQTT broker;
- exact selection of one gateway ID per adapter instance;
- Admin UI and encrypted broker password storage;
- typed gateway and lamp objects;
- requested versus verified state separation;
- command IDs, TTLs, pending state and final result correlation;
- node additions, renames and missing-node handling;
- ioBroker tests and release lifecycle.

The adapter must not contain Mesh keys, invoke the Python CLI, SSH into the gateway or open BlueZ D-Bus connections.

## Runtime contract

The only runtime contract is MQTT API v1 below:

```text
sanlightmesh/v1/<gateway-id>
```

Breaking protocol changes require a new major topic root such as `v2`. Both repositories may evolve internally without coordinating releases as long as the MQTT major version remains compatible.

## Isolation model

One ioBroker adapter instance manages exactly one physical gateway ID. This is intentional.

Examples:

```text
sanlightmesh.0 -> broker A -> gateway room-a
sanlightmesh.1 -> broker A -> gateway room-b
sanlightmesh.2 -> broker B -> gateway greenhouse-2
```

The adapter subscribes only to the exact configured root. It does not use `sanlightmesh/v1/+/...` in normal operation. This avoids accidentally combining lamps from separate grow rooms, buildings or organizations.

MQTT ACLs should restrict each adapter user to its configured gateway where practical.

## Supported deployment topologies

### Split host

```text
Lamps --Bluetooth Mesh--> gateway Pi --MQTT--> broker/ioBroker host
```

This is the preferred arrangement when Bluetooth distance or building structure requires a gateway near the lamps.

### Single host

```text
Lamps --Bluetooth Mesh--> one Pi running gateway, broker and ioBroker
```

The adapter connects to `localhost` and still uses the same MQTT API.

### External broker

```text
gateway Pi --> broker/NAS/server <-- ioBroker adapter
```

TLS should be used when traffic leaves a trusted local network segment.

## Stable identity

MQTT v1 identifies a lamp by gateway ID plus four-digit Mesh address. A future protocol revision may publish node UUID and topology revision. Until then, the adapter must:

- use `<gateway-id>_<address>` as the internal device key;
- keep the address as metadata;
- update displayed names without deleting objects;
- mark missing nodes unavailable rather than deleting scripts, aliases or history configuration.

## Command flow

```text
ioBroker control state (ack=false)
        |
        v
adapter validates and publishes non-retained MQTT command
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

The adapter may debounce commands, but the gateway remains the final authority for range, confirmation, expiry, coalescing, rate limiting and sequence safety.

## Single-sender rule

Do not clone a running gateway installation and start both copies with the same Bluetooth Mesh sender address and sequence state. Only one active gateway may own a particular sender identity. High availability requires distinct provisioned sender addresses and a separately designed coordination model.
