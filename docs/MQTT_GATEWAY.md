# MQTT gateway and local broker

The lamp-side Raspberry Pi is a self-contained SANlight edge appliance:

```text
ioBroker adapter or another MQTT client
              |
              | MQTT over a trusted LAN
              v
SANlight gateway Raspberry Pi
  mosquitto.service
  sanlight-mqtt-gateway.service
  sanlight-meshd-generic.service
              |
              | Bluetooth Mesh
              v
SANlight dimmers
```

The private CDB, Mesh keys, DeviceKeys and BlueZ state remain only on the
gateway Pi. MQTT carries node addresses, names, percentages, health information
and request/result IDs.

## Installation

Use the single product installer:

```bash
sudo bash scripts/install-gateway.sh
```

It installs and configures:

- Mosquitto on TCP port `1883`;
- a local gateway user;
- a remote ioBroker user;
- gateway-scoped Mosquitto ACLs;
- the gateway TOML pointing at `127.0.0.1:1883`;
- the Mesh and MQTT systemd services.

There is no separate broker-host installation step. The installer refuses to
merge its dedicated listener/authentication policy with unrelated Mosquitto
listener or authentication fragments.

## Generated credentials

The installer creates two random passwords:

```text
/etc/sanlight-mesh-mqtt-gateway/mqtt-password.txt
/etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt
```

Both are root-only mode `0600`. The gateway password is consumed locally. To
configure ioBroker, use the command printed at the end of installation:

```bash
sudo cat /etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt
```

Do not paste that password into logs, issues or diagnostics.

The Mosquitto password database contains hashes and is stored separately under
`/etc/mosquitto/` with group-read access for the broker service.

## Broker ACL model

For gateway ID `<id>`, the local gateway user may:

```text
subscribe sanlightmesh/v1/<id>/command
publish   sanlightmesh/v1/<id>/availability
publish   sanlightmesh/v1/<id>/gateway/#
publish   sanlightmesh/v1/<id>/nodes/#
publish   sanlightmesh/v1/<id>/result/#
```

The ioBroker user may:

```text
publish   sanlightmesh/v1/<id>/command
subscribe sanlightmesh/v1/<id>/availability
subscribe sanlightmesh/v1/<id>/gateway/#
subscribe sanlightmesh/v1/<id>/nodes/#
subscribe sanlightmesh/v1/<id>/result/#
```

Anonymous access is disabled. Commands must be non-retained; retained state,
metadata and availability are intentional.

## Network exposure

The default listener is reachable over IPv4 LAN interfaces so that ioBroker can
connect. Plain MQTT credentials are not encrypted. Use this default only on a
trusted private LAN/VLAN and assign the gateway Pi a stable DHCP reservation or
hostname.

Do not expose port `1883` to the internet. TLS and external/shared-broker
topologies are not supported by the public installer; they require an
intentional code/configuration change and separate validation.

## Multiple gateways

Each physical gateway Pi normally runs its own broker and uses its own gateway
ID and credentials. Create one ioBroker adapter instance per Pi:

```text
sanlightmesh.0 -> room-a.local:1883 -> room-a
sanlightmesh.1 -> room-b.local:1883 -> room-b
```

The topic root and ACLs isolate the gateways. Do not clone a running Pi image
with its CDB, BlueZ sender identity and sequence state.

## Services

```bash
systemctl is-enabled mosquitto.service
systemctl is-active mosquitto.service
systemctl is-enabled sanlight-meshd-generic.service
systemctl is-active sanlight-meshd-generic.service
systemctl is-enabled sanlight-mqtt-gateway.service
systemctl is-active sanlight-mqtt-gateway.service
```

Status and logs:

```bash
sudo sanlight-gateway status
sudo sanlight-gateway doctor
sudo journalctl -u mosquitto.service -n 100 --no-pager
sudo journalctl -u sanlight-mqtt-gateway.service -n 100 --no-pager
```

## Update

```bash
git switch main
git pull --ff-only
./scripts/run-tests.sh
sudo bash scripts/install-gateway.sh --reuse-existing
```

The update reuses the protected passwords, rebuilds the dedicated password
database and ACL from the configured gateway ID, refreshes the services and does
not reset Mesh state.

## Traffic and sequence safety

Every outgoing Bluetooth Mesh message consumes one value from the sender's
24-bit Sequence Number space. The gateway therefore:

- serializes Mesh transactions;
- uses MQTT 5 with `retainAsPublished=true`;
- uses `retainHandling=DO_NOT_SEND` for the command subscription;
- rejects retained commands before payload decoding;
- uses a clean MQTT session so offline commands are not queued;
- requires command IDs, creation time and TTL;
- deduplicates QoS 1 redelivery across service restarts;
- persists an in-flight marker before execution;
- coalesces rapid pending setpoints for the same node;
- preserves the persistent brightness-write rate guard;
- recommends routine automation intervals of at least 60 seconds;
- publishes sequence status in retained gateway information.

Do not connect a per-second sensor loop or an un-debounced slider directly to
MaxBrightness commands.

For the complete contract, see [MQTT_API.md](MQTT_API.md). For ioBroker, see
[IOBROKER_INTEGRATION.md](IOBROKER_INTEGRATION.md).
