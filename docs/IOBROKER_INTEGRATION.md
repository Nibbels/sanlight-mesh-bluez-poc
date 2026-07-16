# ioBroker integration boundary

The supported ioBroker integration is the native
[`ioBroker.sanlightmesh`](https://github.com/Nibbels/ioBroker.sanlightmesh)
adapter.

The gateway installer already provides the authenticated Mosquitto broker on
the gateway Pi. The ioBroker host does not need BlueZ, the private
SANlight export, SSH access or the generic ioBroker MQTT adapter.

```text
Gateway Pi (this project)
  BlueZ + gateway service + Mosquitto :1883
                     ^
                     | trusted LAN
                     |
ioBroker host
  one sanlightmesh instance per gateway Pi
```

## Handoff to the adapter

After `scripts/install-gateway.sh` reports `Doctor result: healthy`, keep the
connection values printed by the installer and continue with the adapter
repository's README:

```text
https://github.com/Nibbels/ioBroker.sanlightmesh
```

That README is the authoritative guide for:

- installing the adapter;
- entering the generated gateway connection data;
- checking the four connection states;
- performing the first read-only lamp refresh;
- configuring additional gateway instances.

Keeping these steps in the adapter repository avoids two setup guides drifting
apart.

## One instance per gateway

One adapter instance intentionally connects to one exact gateway ID and broker
connection. A second independent SANlight Mesh needs another gateway Pi, its own
credentials and another adapter instance.

The adapter subscribes only to the configured topic root. It must not discover
or combine unrelated gateways through a broad wildcard.

## Security boundary

- Mesh keys, the private CDB and BlueZ state remain on the gateway Pi.
- ioBroker receives only its scoped MQTT username/password and gateway ID.
- Normal MaxBrightness is limited to `20..100%`.
- Blackout is a separate workflow and is disabled by default in the adapter.
- The gateway remains the final authority for validation, rate limiting,
  snapshots and readback verification.

For the wire protocol, see [MQTT_API.md](MQTT_API.md). For adapter objects and
controls, see the adapter repository's `docs/OBJECT_MODEL.md`.
