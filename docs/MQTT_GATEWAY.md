# MQTT gateway and local broker

The gateway Raspberry Pi is a self-contained edge gateway for SANlight Mesh:

```text
ioBroker.sanlightmesh
      |
      | MQTT over a trusted LAN
      v
Gateway Raspberry Pi (this project)
  mosquitto.service
  sanlight-mqtt-gateway.service
  sanlight-meshd-generic.service
      |
      | Bluetooth Mesh
      v
SANlight dimmers
```

The private CDB, Mesh keys, DeviceKeys, BlueZ state and sender sequence state
remain only on the gateway Pi.

## Installation

Use the single product installer:

```bash
sudo bash scripts/install-gateway.sh
```

It installs and configures:

- Mosquitto on TCP port `1883`;
- separate local-gateway and remote-ioBroker users;
- gateway-scoped Mosquitto ACLs;
- a gateway TOML pointing to `127.0.0.1:1883`;
- the Mesh and MQTT systemd services.

There is no separate broker installation on the ioBroker host.

## Credentials

The installer creates:

```text
/etc/sanlight-mesh-mqtt-gateway/mqtt-password.txt
/etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt
```

Both files are root-only mode `0600`. The gateway password is consumed locally.
Retrieve the ioBroker password only while configuring the adapter:

```bash
sudo cat /etc/sanlight-mesh-mqtt-gateway/iobroker-mqtt-password.txt
```

Do not include either password in diagnostics or support requests.

## Broker ACL model

For gateway ID `<gateway-id>`, the local gateway user can:

```text
read  sanlightmesh/v1/<gateway-id>/command
write sanlightmesh/v1/<gateway-id>/availability
write sanlightmesh/v1/<gateway-id>/gateway/#
write sanlightmesh/v1/<gateway-id>/nodes/#
write sanlightmesh/v1/<gateway-id>/result/#
```

The ioBroker user can:

```text
write sanlightmesh/v1/<gateway-id>/command
read  sanlightmesh/v1/<gateway-id>/availability
read  sanlightmesh/v1/<gateway-id>/gateway/#
read  sanlightmesh/v1/<gateway-id>/nodes/#
read  sanlightmesh/v1/<gateway-id>/result/#
```

Anonymous access is disabled. Commands are non-retained; availability, metadata,
gateway information and verified node state are retained intentionally.

## Network boundary

The default listener is reachable over the gateway Pi's IPv4 LAN interfaces so
ioBroker can connect. Port `1883` uses authenticated plain MQTT and is suitable
only for a trusted private LAN/VLAN.

- assign the gateway Pi a stable DHCP reservation or hostname;
- do not expose port `1883` to the internet;
- do not reuse the generated credentials for unrelated applications.

TLS, external brokers and shared brokers are not alternate public-installer
modes. They require intentional design changes and their own validation.

## Multiple gateways

Each physical gateway Pi normally has its own broker, gateway ID and
credentials:

```text
sanlightmesh.0 -> room-a.local:1883 -> room-a
sanlightmesh.1 -> room-b.local:1883 -> room-b
```

Do not clone a running gateway image together with its CDB, BlueZ sender
identity and sequence state.

## Service operation

```bash
sudo sanlight-gateway status
sudo sanlight-gateway doctor
sudo sanlight-gateway logs
```

Direct checks:

```bash
systemctl is-active mosquitto.service
systemctl is-active sanlight-meshd-generic.service
systemctl is-active sanlight-mqtt-gateway.service

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

The update preserves the protected credentials and Mesh identity state, rebuilds
the managed broker policy and refreshes the services.

## MQTT and sequence safety

Every outgoing Bluetooth Mesh application/config message consumes one value
from the sender's 24-bit Sequence Number space. The gateway therefore:

- serializes Mesh transactions;
- uses MQTT 5 and preserves the retain flag;
- rejects retained commands before payload decoding;
- prevents retained/offline commands from being replayed after reconnect;
- requires command IDs, creation time and TTL;
- deduplicates QoS 1 redelivery across service restarts;
- persists an in-flight marker before execution;
- coalesces rapid same-node setpoints;
- preserves the persistent brightness-write rate guard;
- publishes retained sequence-health information;
- recommends routine automation intervals of at least 60 seconds.

Do not connect a per-second sensor loop or an un-debounced slider directly to
MaxBrightness commands.

Daylight configuration reads are also explicit and serialized. They are not
included in startup or periodic refresh because one read can require a fallback
request and a larger segmented Mesh response. The gateway preserves raw vendor
data and leaves schedule interpretation and farm policy to its MQTT clients.

For the wire contract, see [MQTT_API.md](MQTT_API.md). For ioBroker setup, see
[IOBROKER_INTEGRATION.md](IOBROKER_INTEGRATION.md).
