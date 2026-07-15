# ioBroker integration plan

## First integration: generic MQTT

Use an MQTT broker reachable by both Raspberry Pis. The ioBroker MQTT adapter can subscribe to the gateway topics, or ioBroker can connect to an external Mosquitto broker.

Suggested ioBroker mapping:

```text
sanlightmesh.0.info.connection
sanlightmesh.0.gateway.sequenceNumber
sanlightmesh.0.gateway.sequenceRemaining
sanlightmesh.0.nodes.0002.name
sanlightmesh.0.nodes.0002.maxBrightness
sanlightmesh.0.nodes.0002.targetMaxBrightness
sanlightmesh.0.nodes.0002.available
sanlightmesh.0.nodes.0002.lastSeen
```

The desired target and reported value must remain distinct. A write to `targetMaxBrightness` publishes a command. `maxBrightness` changes only after the gateway publishes verified readback.

## Future native adapter

Create a separate repository after MQTT v1 is hardware-validated:

```text
Repository: Nibbels/ioBroker.sanlightmesh
Adapter name: sanlightmesh
Object root: sanlightmesh.0
```

The adapter should contain its own MQTT client and provide:

- broker/gateway configuration;
- automatic node object creation from retained metadata;
- typed writable target states;
- target/report separation;
- debounce before publishing slider changes;
- request IDs and short expirations;
- result/error mapping;
- explicit blackout and restore confirmations;
- gateway availability and sequence-space warnings.

The adapter must not contain CDB keys, use Bluetooth remotely, invoke SSH, or duplicate the BlueZ implementation. It should reference this repository as its required gateway project and declare support for MQTT API v1.

## Repository cross-references

Gateway README:

```text
Optional native ioBroker adapter: https://github.com/Nibbels/ioBroker.sanlightmesh
```

Adapter README:

```text
Required gateway: https://github.com/Nibbels/sanlight-mesh-bluez-gateway
```

Rename the current gateway repository only after the MQTT service is validated and merged. Until then, keep the existing repository URL stable.
