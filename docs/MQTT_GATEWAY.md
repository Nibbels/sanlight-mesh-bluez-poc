# MQTT edge gateway

This optional service turns the lamp-side Raspberry Pi into a Wi-Fi/Ethernet edge gateway:

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

## Development branch

Develop and validate this feature on:

```bash
git switch -c feature/mqtt-gateway
git push -u origin feature/mqtt-gateway
```

After hardware and broker testing, merge the branch back into `main`. Do not keep a permanent diverging gateway branch.

## Why MQTT first

The gateway protocol is intentionally independent of ioBroker. It can be tested with Mosquitto tools and the generic ioBroker MQTT adapter before a native adapter is created.

A future native adapter should be a separate repository:

```text
Nibbels/ioBroker.sanlightmesh
```

It should depend on the versioned MQTT API documented in [MQTT_API.md](MQTT_API.md), not on the Python source tree and not on SSH or shell access.

## Runtime model

`bluetooth-meshd` remains continuously active and owns `hci0`. The MQTT process remains continuously connected to the broker and serializes commands. For the first gateway release, each command invokes the already hardware-validated Python transaction engine as a child process using an argument vector—never through a shell.

This isolation is deliberate:

- it reuses the tested D-Bus attach, retry, readback and replay-protection logic;
- the existing runtime lock prevents competing Mesh applications;
- a failed command cannot corrupt the long-running MQTT client;
- MQTT input cannot select an executable, file path or arbitrary CLI option.

A later in-process backend can replace the executor without changing MQTT v1.

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

Store the MQTT password in a separate mode-`0600` file. Do not put it in Git.

Validate without connecting to MQTT:

```bash
sudo python3 sanlight_mqtt_gateway.py \
    --config private/sanlight-gateway.toml \
    --check
```

The check prints only redacted configuration and CDB metadata.

## Install the service

Complete [SETUP.md](../SETUP.md) first. Then:

```bash
sudo bash ./scripts/install-mqtt-gateway.sh \
    --config private/sanlight-gateway.toml
```

Status and logs:

```bash
sudo systemctl status sanlight-mqtt-gateway.service
sudo journalctl -fu sanlight-mqtt-gateway.service
```

The installer adds Debian's `python3-paho-mqtt` package. It does not install a broker. Run Mosquitto or another MQTT broker on the ioBroker host or elsewhere on the trusted LAN.

## Traffic and Sequence Number safety

Every outgoing Bluetooth Mesh message consumes one value from the sender's 24-bit Sequence Number space. A verified brightness write normally sends a Set and a Get readback, and retries can send more.

The gateway therefore:

- processes only one Mesh transaction at a time;
- rejects retained MQTT commands;
- uses a clean MQTT session so commands published while the gateway is offline are not queued for later execution;
- requires command IDs and expiration data;
- remembers completed IDs and does not execute QoS 1 duplicates again;
- persists an in-flight marker before execution so an interrupted command is not blindly repeated after restart;
- coalesces rapid pending `set-max` commands for the same node;
- can optionally suppress a write from a fresh verified cache, but this is disabled by default because the SANlight app may also change values;
- preserves the existing persistent ten-second write guard;
- recommends automation intervals of at least 60 seconds;
- publishes `sequenceStatus` and remaining percentage in retained `gateway/info`;
- refreshes state only every 30 minutes by default.

Do not map a fast slider, continuously changing sensor or one-second control loop directly to MaxBrightness. Use thresholds and change detection in ioBroker.

## Broker security

Recommended ACL shape:

```text
Gateway client:
  subscribe sanlightmesh/v1/<gateway-id>/command
  publish   sanlightmesh/v1/<gateway-id>/availability
  publish   sanlightmesh/v1/<gateway-id>/gateway/#
  publish   sanlightmesh/v1/<gateway-id>/nodes/#
  publish   sanlightmesh/v1/<gateway-id>/result/#

ioBroker client:
  publish   sanlightmesh/v1/<gateway-id>/command
  subscribe sanlightmesh/v1/<gateway-id>/#
```

Command messages must be non-retained. State, metadata and availability are retained.

For the staged first hardware run, follow [MQTT_TEST_PLAN.md](MQTT_TEST_PLAN.md).

## Test with Mosquitto clients

Subscribe:

```bash
mosquitto_sub -h BROKER \
    -t 'sanlightmesh/v1/sanlight-pi/#' \
    -v
```

Generate a fresh command timestamp:

```bash
NOW="$(date --utc +%Y-%m-%dT%H:%M:%SZ)"
```

Read one node:

```bash
mosquitto_pub -h BROKER -q 1 \
    -t 'sanlightmesh/v1/sanlight-pi/command' \
    -m "{\"id\":\"manual-refresh-$(date +%s)\",\"action\":\"refresh\",\"target\":\"0003\",\"createdAt\":\"$NOW\",\"ttlSeconds\":30}"
```

Set one node to 48%, with verified readback:

```bash
mosquitto_pub -h BROKER -q 1 \
    -t 'sanlightmesh/v1/sanlight-pi/command' \
    -m "{\"id\":\"manual-set-$(date +%s)\",\"action\":\"set-max\",\"target\":\"0003\",\"value\":48,\"createdAt\":\"$NOW\",\"ttlSeconds\":30}"
```

Do not use `-r`/`--retain` for commands. The gateway rejects retained commands even when the broker delivers one.
