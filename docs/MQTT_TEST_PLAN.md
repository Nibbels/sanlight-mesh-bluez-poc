# MQTT gateway hardware test plan

Run these stages in order on `feature/mqtt-gateway`.

## 1. Branch and offline tests

```bash
git switch -c feature/mqtt-gateway
# copy the overlay into the repository
git status --short
bash ./scripts/run-tests.sh
```

Expected: all offline tests pass and no private file is staged.

## 2. Prepare a broker

Use an existing Mosquitto broker or the ioBroker MQTT adapter in broker/server mode. Record:

- broker IP or DNS name;
- port;
- username/password if configured;
- CA certificate path if TLS is used.

Do not expose an unauthenticated broker to the internet.

## 3. Configure without starting a service

```bash
cp config/sanlight-gateway.toml.example private/sanlight-gateway.toml
chmod 600 private/sanlight-gateway.toml
nano private/sanlight-gateway.toml

sudo python3 sanlight_mqtt_gateway.py \
    --config private/sanlight-gateway.toml \
    --check
```

Check that the redacted output shows the intended gateway ID, broker, sender and nodes. It must not print keys, passwords or tokens.

## 4. Install but do not start

```bash
sudo bash ./scripts/install-mqtt-gateway.sh \
    --config private/sanlight-gateway.toml \
    --no-start

sudo systemctl cat sanlight-mqtt-gateway.service
```

Verify repository, config and state paths before starting.

## 5. Subscribe from the broker/ioBroker side

```bash
mosquitto_sub -h BROKER \
    -t 'sanlightmesh/v1/sanlight-pi/#' \
    -v
```

Use the gateway ID from the TOML file.

## 6. Start and observe

```bash
sudo systemctl start sanlight-mqtt-gateway.service
sudo journalctl -fu sanlight-mqtt-gateway.service
```

Expected retained topics:

```text
availability = online
gateway/info
nodes/0002/meta
nodes/0003/meta
nodes/0002/state
nodes/0003/state
```

The startup refresh may require a retry when a status packet is missed. It must remain serialized.

## 7. Read-only command

```bash
NOW="$(date --utc +%Y-%m-%dT%H:%M:%SZ)"
ID="refresh-0003-$(date +%s)"
mosquitto_pub -h BROKER -q 1 \
    -t 'sanlightmesh/v1/sanlight-pi/command' \
    -m "{\"id\":\"$ID\",\"action\":\"refresh\",\"target\":\"0003\",\"createdAt\":\"$NOW\",\"ttlSeconds\":30}"
```

Expected final result: `status=verified`, with retained node state still at the current percentage.

## 8. Verified write and restore

Only after the read path works:

```bash
NOW="$(date --utc +%Y-%m-%dT%H:%M:%SZ)"
ID="set-0003-48-$(date +%s)"
mosquitto_pub -h BROKER -q 1 \
    -t 'sanlightmesh/v1/sanlight-pi/command' \
    -m "{\"id\":\"$ID\",\"action\":\"set-max\",\"target\":\"0003\",\"value\":48,\"createdAt\":\"$NOW\",\"ttlSeconds\":30}"
```

Expected: final `verified` result and retained `nodes/0003/state` with `48`.

Wait at least ten seconds, then restore `68` using a new command ID.

## 9. Safety tests

- Publish the exact same command ID again: it must republish the stored result without a second Mesh write.
- Publish a retained command while the gateway is online: MQTT 5 `retainAsPublished` must preserve the retain flag and the gateway must reject it.
- Publish a retained command while the gateway is offline, then start it: `retainHandling=DO_NOT_SEND` must prevent execution.
- Publish rapid `set-max` commands for the same node: pending older requests should finish as `superseded`; only the newest should reach Bluetooth.
- Stop the service and confirm retained availability changes to `offline` through Last Will.
- Do not test blackout through MQTT until ordinary refresh/set/restore behavior is stable.
