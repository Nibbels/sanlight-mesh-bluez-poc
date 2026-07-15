# ioBroker integration

## Current validated integration: generic MQTT adapter

The validated integration uses an external Mosquitto broker and ioBroker's generic MQTT adapter in client/subscriber mode.

This is sufficient for automation and monitoring in the tested installation. It is intentionally a generic JSON-string integration rather than a polished, typed native adapter.


## Broker and client roles

The validated topology is:

```text
SANlight gateway on the lamp-side Pi
    -> Mosquitto broker on the ioBroker host
    -> ioBroker MQTT adapter in client/subscriber mode
```

The broker and ioBroker may run on the same Raspberry Pi, but they remain separate processes with separate responsibilities. The remote SANlight gateway connects to the ioBroker host's LAN IP or DNS name. The ioBroker MQTT adapter connects to `localhost:1883` when Mosquitto runs on that same host.

The gateway repository includes `scripts/install-mosquitto-broker.sh` for a clean Debian/Raspberry Pi OS broker host. Copy the script to the broker/ioBroker host and run:

```bash
sudo bash install-mosquitto-broker.sh
```

The script creates two users:

- `sanlight-gateway`: reads only the gateway command topic and writes gateway availability, metadata, state and results;
- `sanlight-iobroker`: reads the gateway output topics and writes only the gateway command topic.

Both accounts are restricted to the configured `sanlightmesh/v1/<gateway-id>/...` namespace. Anonymous access is disabled.

The default broker script configures password authentication without TLS on port `1883`. Use it only on a trusted private LAN. The gateway installer must use the `sanlight-gateway` credentials; the ioBroker adapter must use the separate `sanlight-iobroker` credentials.

The ioBroker MQTT adapter's server mode is not the validated broker path for this project. In particular, it has not been validated against the gateway's MQTT 5 retained-command subscription safeguards. Use the adapter in client/subscriber mode with Mosquitto unless that alternative is reviewed and tested separately.

## Validated adapter behavior

The generic adapter subscribes to the gateway tree and creates objects below an instance such as:

```text
mqtt.0.sanlightmesh.v1.<gateway-id>.availability
mqtt.0.sanlightmesh.v1.<gateway-id>.gateway.info
mqtt.0.sanlightmesh.v1.<gateway-id>.nodes.<node>.meta
mqtt.0.sanlightmesh.v1.<gateway-id>.nodes.<node>.state
mqtt.0.sanlightmesh.v1.<gateway-id>.result.<command-id>
```

A tree containing many `result` objects is expected: every unique command ID has its own non-retained result topic, and ioBroker keeps the created state object after the MQTT message has passed.

The generic adapter stores JSON payloads as strings. For example, a node-state value contains serialized JSON with fields such as `maxBrightness`, `off`, `verified` and `verifiedAt`. This is normal for the generic integration; the dedicated adapter provides the typed object model instead.

## Suggested MQTT adapter settings

Validated shape:

- connection mode: client/subscriber;
- broker host `localhost` and port `1883` when Mosquitto runs on the same ioBroker host;
- username `sanlight-iobroker` and the separate password created by the broker setup script;
- subscribe to:
  - `sanlightmesh/v1/<gateway-id>/availability`
  - `sanlightmesh/v1/<gateway-id>/gateway/#`
  - `sanlightmesh/v1/<gateway-id>/nodes/#`
  - `sanlightmesh/v1/<gateway-id>/result/#`
- prevent ordinary ioBroker states from being published automatically, for example with a deliberately non-matching own-state mask;
- disable publish-on-connect;
- disable automatic publication of states with `ack=true`;
- keep separate publish/subscribe topic-name rewriting disabled unless deliberately required;
- disable the persistent MQTT session for this command path;
- disable retain for publications;
- use QoS 1 where available.

Adapter labels vary slightly by version. The invariant is that only the explicit `sendMessage2Client` call publishes gateway commands, and those commands are never retained.

## Publish a command from JavaScript

Use the MQTT adapter's `sendMessage2Client` command. The gateway command must be a fresh, non-retained JSON message:

```javascript
const gatewayId = 'sanlight-pi';
const node = 'NODE_ADDRESS'; // replace with list-nodes output
const command = {
    id: `iobroker-refresh-${node}-${Date.now()}`,
    action: 'refresh',
    target: node,
    createdAt: new Date().toISOString(),
    ttlSeconds: 30,
};

sendTo(
    'mqtt.0',
    'sendMessage2Client',
    {
        topic: `sanlightmesh/v1/${gatewayId}/command`,
        message: JSON.stringify(command),
        retain: false,
    },
);
```

Read the corresponding result object after publication. The exact adapter call is intentionally small; long-running automation scripts should correlate by command ID, impose their own timeout and handle `verified`, `expired`, `superseded`, `rejected` and failure states explicitly.

## Automation rules

- Keep requested targets separate from verified reported state.
- Update reported state only from `nodes/<NODE>/state` or a `verified` result.
- Debounce UI sliders and sensor-driven changes.
- Do not publish faster than the gateway's recommended interval unless performing a controlled diagnostic.
- Generate a new command ID for a genuinely new action.
- Use short TTLs so obsolete automation cannot execute late.
- Never retain commands.
- Require a separate explicit confirmation path for blackout and restore.
- Surface `availability`, `sequenceStatus` and remaining sequence percentage.

## Cleaning old result objects

Deleting old ioBroker `result` state objects is optional housekeeping; it does not delete or replay MQTT commands on the broker. Do not delete retained `availability`, `gateway/info`, node metadata or node-state topics unless deliberately resetting the integration view.

The dedicated native adapter keeps only bounded command status in typed states and does not create one object per command ID.

## Native adapter repository

The initial native adapter implementation is developed in a separate repository:

```text
Repository: Nibbels/ioBroker.sanlightmesh
Adapter name: sanlightmesh
Object root: sanlightmesh.0
```

It should depend only on [MQTT_API.md](MQTT_API.md), not on SSH, local Python paths or the BlueZ implementation. Desirable features include:

- broker and gateway configuration;
- automatic typed node objects from retained metadata;
- writable target states distinct from verified reported states;
- debounce and change detection;
- command/result correlation;
- explicit blackout and restore confirmations;
- gateway availability and sequence-space warnings;
- bounded result history.

The native adapter must not contain CDB keys, invoke Bluetooth remotely, use SSH, or duplicate the gateway's BlueZ logic.

Required gateway repository:

```text
https://github.com/Nibbels/sanlight-mesh-mqtt-gateway
```

## Instance isolation

The native adapter deliberately manages exactly one configured gateway per instance. This is a safety and usability boundary, not a limitation to remove.

Examples:

```text
sanlightmesh.0 -> room-a
sanlightmesh.1 -> room-b
```

Each instance subscribes only to `sanlightmesh/v1/<configured-gateway-id>/...`. It must not discover and combine every gateway on a broker. Multiple instances may share a broker, or each room may use a separate broker.

This design prevents lamps from separate grow rooms, buildings or clubs from appearing in one control tree by accident.

