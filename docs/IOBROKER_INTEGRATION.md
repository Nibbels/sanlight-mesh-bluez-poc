# ioBroker integration

## Normal connection model

Each SANlight gateway Pi runs its own authenticated Mosquitto broker. ioBroker
runs on another host and uses the native `ioBroker.sanlightmesh` adapter:

```text
SANlight-PoCe gateway Pi
  BlueZ + SANlight gateway + Mosquitto :1883
                     ^
                     | trusted LAN
                     |
ioBroker host
  one sanlightmesh adapter instance per gateway Pi
```

Do not install ioBroker's generic MQTT adapter for the normal product setup. It
was useful during early protocol validation, but the native adapter is now the
single ioBroker integration path and avoids a duplicate raw MQTT object tree.

Adapter repository:

```text
https://github.com/Nibbels/ioBroker.sanlightmesh
```

During development, install it through ioBroker Admin's **Install from custom
URL** function, then create an instance.

## Instance configuration

The gateway installer prints or references all required settings:

- broker host: stable LAN IP/hostname of the corresponding SANlight gateway Pi;
- broker port: `1883`;
- MQTT username: generated ioBroker user;
- MQTT password: obtained with the root-only command printed by the installer;
- topic prefix: `sanlightmesh/v1`;
- exact gateway ID selected during gateway installation;
- TLS: disabled for the supported trusted-LAN topology.

Use a DHCP reservation or stable local hostname for each gateway Pi. Do not
publish port `1883` to the internet.

## Multiple gateway and adapter instances

Multiple physical SANlight gateways were explicitly designed into the adapter.
One adapter instance manages exactly one gateway ID and one broker connection:

```text
sanlightmesh.0 -> room-a.local:1883     -> gateway ID room-a
sanlightmesh.1 -> room-b.local:1883     -> gateway ID room-b
sanlightmesh.2 -> greenhouse.local:1883 -> gateway ID greenhouse
```

Each instance receives an independent ioBroker object namespace and subscribes
only to the configured gateway's output topics. It must never use a wildcard to
discover and combine all gateways.

A second room/building therefore needs:

1. another SANlight gateway Pi and its own private CDB/BlueZ identities;
2. a unique or clearly assigned gateway ID;
3. one additional `ioBroker.sanlightmesh` adapter instance configured for that
   Pi's IP/hostname, credentials and gateway ID.

Gateway IDs may technically repeat on separate brokers, but unique descriptive
IDs are strongly recommended because they make logs, diagnostics and future
broker migrations unambiguous.

## Credential retrieval and rotation

The ioBroker password is stored only on the corresponding SANlight gateway Pi:

```bash
sudo cat /etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt
```

Copy the value directly into the protected adapter setting. Do not paste it into
issues, logs or chat transcripts.

A normal `--reuse-existing` update preserves local-broker credentials. Migration
from the former external-broker setup generates new credentials and prints an
explicit notice; update the matching ioBroker adapter instance afterward.

## Safety and object-state rules

- One instance controls only its exact configured gateway ID.
- Requested brightness and verified reported brightness remain separate.
- Normal brightness is restricted to `20..100%`.
- Blackout remains an explicit, separately enabled workflow.
- Commands are non-retained and use unique IDs plus short TTLs.
- UI sliders and sensor-driven changes must be debounced.
- The gateway remains the final authority for validation, rate limits,
  coalescing, readback and sequence-space safety.
- Mesh keys, the private CDB and BlueZ state never leave the gateway Pi.

For the exact topic and payload contract, see [MQTT_API.md](MQTT_API.md).
