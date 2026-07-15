# MQTT edge gateway

The MQTT service turns the lamp-side Raspberry Pi into an always-on LAN edge gateway:

```text
ioBroker or another MQTT client
          |
          | MQTT over the LAN
          v
MQTT broker
          |
          v
Raspberry Pi near the lamps
  sanlight-mqtt-gateway.service
  sanlight-meshd-generic.service
          |
          | Bluetooth Mesh
          v
SANlight dimmers
```

The private CDB, Mesh keys, DeviceKeys and BlueZ state remain only on the lamp-side Raspberry Pi. MQTT carries node addresses, names, percentages, health information and request/result IDs.

This is an unofficial community project and is not affiliated with or endorsed by SANlight GmbH.

## Status

The gateway implementation is merged into `main` and hardware validated for the documented installation. It is a pre-1.0 community gateway: there is not yet a broad support contract, and deployments with different firmware, Mesh topology, broker or network-security requirements must be validated independently.

The completed validation covered:

- 97 offline unit/security tests on the target Raspberry Pi;
- initial startup and retained metadata/state publication;
- read-only refresh and verified `set-max`/restore;
- rejection of ordinary `set-max` values below 20, including zero;
- rejection of live retained commands with MQTT 5 retain preservation;
- suppression of retained commands stored while the gateway was offline;
- QoS 1 duplicate-ID deduplication across service restart;
- TTL expiry before execution with `meshMessagesSent: 0`;
- same-node command coalescing;
- explicit blackout, zero readback and restore;
- persistent ten-second write-rate limiting;
- Last-Will `offline` and automatic reconnect;
- Mosquitto restart, gateway restart and full lamp-side Raspberry Pi reboot;
- generic ioBroker MQTT adapter subscription and command publishing;
- unbuffered systemd journal output.

The validated service reported MQTT protocol version 1 and service version `0.1.1`. Version numbers may advance independently of this record.

## Runtime model

`bluetooth-meshd` remains continuously active and owns `hci0`. The MQTT process remains continuously connected to the broker and serializes commands. Each gateway command invokes the hardware-validated Python transaction engine as a child process using a fixed argument vector—never through a shell.

This isolation is deliberate:

- it reuses the tested D-Bus attach, retry, readback and replay-protection logic;
- the existing runtime lock prevents competing Mesh applications;
- a failed command cannot corrupt the long-running MQTT client;
- MQTT input cannot select an executable, file path or arbitrary CLI option.

A later in-process backend may replace the executor without changing MQTT v1.

## Prerequisites

Complete [SETUP.md](../SETUP.md) first and verify at least one lamp with `get-live` or `get-max`.

Run an MQTT broker reachable from both the lamp-side Raspberry Pi and the automation host. Mosquitto on the ioBroker host is a validated arrangement. Do not expose an unauthenticated broker to the internet.

## Configuration

Copy the example and protect it:

```bash
cp config/sanlight-gateway.toml.example private/sanlight-gateway.toml
chmod 600 private/sanlight-gateway.toml
nano private/sanlight-gateway.toml
```

Set at least:

- a stable gateway ID;
- the current repository and CDB paths;
- MQTT broker host and port;
- optional username and `password_file`;
- optional TLS CA certificate.

Store the MQTT password in a separate mode-`0600` file. Do not put it in Git or directly in the TOML file.

Validate without connecting to MQTT:

```bash
sudo python3 sanlight_mqtt_gateway.py \
    --config private/sanlight-gateway.toml \
    --check
```

The check prints only redacted configuration and CDB metadata.

## Install and operate the service

```bash
sudo bash ./scripts/install-mqtt-gateway.sh \
    --config private/sanlight-gateway.toml
```

The installer adds Debian's `python3-paho-mqtt` package. The gateway requires Paho MQTT 2.x and MQTT 5 support.

Check both lamp-side services:

```bash
systemctl is-enabled sanlight-meshd-generic.service
systemctl is-active sanlight-meshd-generic.service
systemctl is-enabled sanlight-mqtt-gateway.service
systemctl is-active sanlight-mqtt-gateway.service
```

Status and immediate logs:

```bash
sudo systemctl status sanlight-mqtt-gateway.service --no-pager --full
sudo journalctl -fu sanlight-mqtt-gateway.service
```

The installed unit uses `PYTHONUNBUFFERED=1`, so gateway messages should appear in the journal immediately rather than only during shutdown.


## Interactive deployment helper

After `SETUP.md` has created and verified the local Mesh identities, the new wrapper can create the protected MQTT configuration and install the service:

```bash
sudo bash scripts/install-gateway.sh
```

It asks for broker settings and stores the password in a separate mode-0600 file. It does not provision the Mesh and never changes lamp brightness or time. See [INSTALLER.md](INSTALLER.md) for scope and current validation status.

For routine checks and redacted support output:

```bash
sudo scripts/sanlight-gateway status
sudo scripts/sanlight-gateway doctor
sudo scripts/sanlight-gateway collect-diagnostics
```

## Update an installed gateway

After updating the repository on `main`:

```bash
git switch main
git pull --ff-only
./scripts/run-tests.sh
sudo bash ./scripts/install-mqtt-gateway.sh \
    --config private/sanlight-gateway.toml
```

The installer updates the unit without resetting Mesh state. A reset must remain explicit.

## Traffic and Sequence Number safety

Every outgoing Bluetooth Mesh message consumes one value from the sender's 24-bit Sequence Number space. A verified brightness write normally sends a Set and a Get readback, and retries can send more.

The gateway therefore:

- processes only one Mesh transaction at a time;
- uses MQTT 5 with `retainAsPublished=true` and rejects live retained MQTT commands;
- uses `retainHandling=DO_NOT_SEND`, so commands retained while the gateway is offline are not delivered after reconnect;
- uses a clean MQTT session so commands published while the gateway is offline are not queued for later execution;
- requires command IDs and expiration data;
- remembers completed IDs and does not execute QoS 1 duplicates again;
- persists an in-flight marker before execution so an interrupted command is not blindly repeated after restart;
- coalesces rapid pending `set-max` commands for the same node;
- can optionally suppress a write from a fresh verified cache, but this is disabled by default because the SANlight app may also change values;
- preserves the persistent ten-second write guard;
- recommends automation intervals of at least 60 seconds;
- publishes `sequenceStatus` and remaining percentage in retained `gateway/info`;
- refreshes state only every 30 minutes by default.

Do not map a fast slider, continuously changing sensor or one-second control loop directly to MaxBrightness. Use thresholds, debounce and change detection in ioBroker.

## Broker security

Recommended ACL shape:

```text
Gateway client:
  subscribe sanlightmesh/v1/<gateway-id>/command
  publish   sanlightmesh/v1/<gateway-id>/availability
  publish   sanlightmesh/v1/<gateway-id>/gateway/#
  publish   sanlightmesh/v1/<gateway-id>/nodes/#
  publish   sanlightmesh/v1/<gateway-id>/result/#

Automation client:
  publish   sanlightmesh/v1/<gateway-id>/command
  subscribe sanlightmesh/v1/<gateway-id>/#
```

Command messages must be non-retained. State, metadata and availability are retained. Use separate least-privilege broker users for the gateway and automation client.

Plain MQTT credentials are visible to hosts able to inspect that LAN segment. Use a trusted isolated LAN/VLAN or configure TLS when this is not acceptable. TLS support exists in the gateway configuration, but the documented hardware run used plain MQTT on a trusted LAN and therefore did not validate a TLS deployment.

Mosquitto deployment notes from the validated setup:

- disable anonymous access and use separate ACL-limited gateway and automation users;
- Mosquitto combines its main file and included fragments into one configuration, so settings such as `persistence_location` must be defined only once;
- when a listener is bound to one specific interface address, keep that address stable and ensure the interface is available when Mosquitto starts;
- the gateway installer installs the MQTT client dependency, not the broker or its users/ACLs.

## Test with Mosquitto clients

Discover lamp addresses first:

```bash
python3 sanlight_canonical_sender_poc.py \
    --cdb private/SANlightMesh.json \
    list-nodes
```

Set shell variables from your own configuration:

```bash
BROKER=broker.example.lan
GATEWAY_ID=sanlight-pi
NODE=NODE_ADDRESS
ROOT="sanlightmesh/v1/$GATEWAY_ID"
```

Replace `NODE_ADDRESS` with a unicast node reported by `list-nodes`.

Subscribe:

```bash
mosquitto_sub -V mqttv5 \
    -h "$BROKER" \
    -q 1 \
    -t "$ROOT/#" \
    -v
```

Publish a read-only refresh:

```bash
NOW="$(date --utc +%Y-%m-%dT%H:%M:%SZ)"
ID="manual-refresh-$(date +%s)"
PAYLOAD="$(printf \
    '{"id":"%s","action":"refresh","target":"%s","createdAt":"%s","ttlSeconds":30}' \
    "$ID" "$NODE" "$NOW")"

mosquitto_pub -V mqttv5 \
    -h "$BROKER" \
    -q 1 \
    -t "$ROOT/command" \
    -m "$PAYLOAD"
```

Do not use `-r`/`--retain` for commands. The gateway rejects retained commands even when the broker delivers one.

For the complete contract, see [MQTT_API.md](MQTT_API.md). For ioBroker, see [IOBROKER_INTEGRATION.md](IOBROKER_INTEGRATION.md). The completed validation matrix is recorded in [MQTT_TEST_PLAN.md](MQTT_TEST_PLAN.md).
