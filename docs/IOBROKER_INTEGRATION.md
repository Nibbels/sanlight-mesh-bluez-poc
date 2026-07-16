# ioBroker integration

The normal integration uses the native
[`ioBroker.sanlightmesh`](https://github.com/Nibbels/ioBroker.sanlightmesh)
adapter.

The gateway installer already installs Mosquitto on the SANlight gateway Pi.
There is no broker installation step on the ioBroker host.

```text
SANlight gateway Pi
  BlueZ + SANlight gateway + Mosquitto :1883
                     ^
                     | trusted LAN
                     |
ioBroker host
  one sanlightmesh instance per gateway Pi
```

The generic ioBroker MQTT adapter is not required. It was useful during early
protocol testing but creates a second raw MQTT object tree and is not part of
the normal product setup.

## Install the adapter

In ioBroker Admin:

1. Open **Adapters**.
2. Choose **Install from custom URL**.
3. Enter:

```text
https://github.com/Nibbels/ioBroker.sanlightmesh
```

4. Install the adapter.
5. Create one instance for the physical SANlight gateway.

During pre-1.0 development, update the adapter through the same GitHub custom-URL
path.

## Configure one instance

The gateway installer prints or references every required value.

| Adapter setting | Value |
|---|---|
| MQTT broker host | stable LAN IP/hostname of the SANlight gateway Pi |
| MQTT broker port | `1883` |
| Use MQTT TLS | disabled for the documented trusted-LAN setup |
| MQTT username | generated `sanlight-iobroker-<gateway-id>` user |
| MQTT password | protected value stored on the gateway Pi |
| Topic prefix | `sanlightmesh/v1` |
| Gateway ID | exact ID selected during gateway installation |
| Command lifetime | `30` seconds |
| Brightness debounce | `1000` ms |
| Explicit blackout | disabled initially |

Retrieve the password on the corresponding gateway Pi:

```bash
sudo cat /etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt
```

Copy it directly into the protected adapter setting. Do not paste it into logs,
issues or chat transcripts.

## Verify the connection

After starting the instance, these states should become `true`:

```text
sanlightmesh.0.info.mqttConnected
sanlightmesh.0.info.gatewayOnline
sanlightmesh.0.info.protocolCompatible
sanlightmesh.0.info.connection
```

Detected lamps appear below `sanlightmesh.0.lamps`.

Use a lamp's `control.refresh` button for the first end-to-end test. It is
read-only. A successful command produces:

```text
lamps.<address>.command.lastStatus = verified
```

Only then test a small reversible MaxBrightness change within `20..100` and
restore the original value.

## Multiple gateways

One adapter instance intentionally manages exactly one gateway ID and one broker
connection:

```text
sanlightmesh.0 -> room-a.local:1883 -> gateway ID room-a
sanlightmesh.1 -> room-b.local:1883 -> gateway ID room-b
sanlightmesh.2 -> greenhouse.local:1883 -> gateway ID greenhouse
```

A second room or building therefore needs:

1. another SANlight gateway Pi with its own CDB and BlueZ identities;
2. its own gateway ID and generated credentials;
3. another `ioBroker.sanlightmesh` instance.

Each adapter instance subscribes only to its exact configured topic root. It
must never wildcard-discover and combine every gateway.

## Safety model

- Requested and verified brightness are separate states.
- Normal brightness is restricted to `20..100%`.
- Blackout is a separately enabled workflow and remains disabled by default.
- Commands are non-retained and have unique IDs and short TTLs.
- Slider writes are debounced.
- The gateway remains the final authority for validation, rate limits,
  coalescing, readback and sequence-space safety.
- Mesh keys, the private CDB and BlueZ state never leave the gateway Pi.

For object details, see the adapter repository's `docs/OBJECT_MODEL.md`. For the
wire protocol, see [MQTT_API.md](MQTT_API.md).

## Reference validation

The native adapter path was validated on 2026-07-16 with:

- a Raspberry Pi 4 ioBroker host running Node.js 22.15.0;
- a separate Raspberry Pi 3 gateway using the local Mosquitto topology;
- successful MQTT, gateway-online and protocol-compatible states;
- automatic creation of two lamp object trees;
- a verified read-only refresh;
- reversible 68% → 67% → 68% writes on both real lamps, independently visible
  in the SANlight app.

The addresses and percentages belong only to that reference installation.
