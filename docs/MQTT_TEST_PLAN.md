# MQTT gateway validation record and regression plan

The original feature-branch test plan was completed on real hardware on 2026-07-15. The gateway was then merged into `main`; no permanent `feature/mqtt-gateway` branch is required.

This file records what was validated and the minimum regression sequence for future gateway changes.

## Validated reference topology

- lamp-side Raspberry Pi 3 running Debian 13 `trixie`, BlueZ 5.82 and `generic:hci0`;
- persistent `sanlight-meshd-generic.service`;
- persistent `sanlight-mqtt-gateway.service`;
- Mosquitto 2.0 broker on a separate ioBroker Raspberry Pi;
- authentication enabled with separate least-privilege gateway and ioBroker users;
- generic ioBroker MQTT adapter in client/subscriber mode;
- two real SANlight lamp nodes;
- MQTT API v1, gateway service version `0.1.1` during validation.

Addresses, node names, IP addresses and credentials are installation-specific and are intentionally omitted here.

## Completed validation matrix

| Test | Result |
|---|---|
| Python syntax, static secret scan and unit suite | 97 tests passed on target Linux host |
| Gateway configuration check | redacted output only; no keys, passwords or tokens |
| Initial MQTT connection | online availability, gateway info and two node definitions published |
| Startup refresh | both nodes published verified retained states |
| Read-only refresh | verified, no state change |
| Verified `set-max` and restore | applied and read back correctly |
| Ordinary `set-max` value `0` | rejected before Mesh write |
| Live retained command | rejected using MQTT 5 retain preservation |
| Retained command stored while offline | not delivered after reconnect |
| QoS 1 duplicate ID | stored result republished; no second Mesh write |
| Duplicate cache after gateway restart | preserved and still deduplicated |
| Expired command | rejected with `meshMessagesSent: 0` |
| Rapid same-node setpoints | older requests `superseded`; newest request transmitted |
| Persistent ten-second write guard | short-TTL second command expired without Mesh traffic |
| Blackout | explicit confirmation, verified zero and physical lamp off |
| Restore latest | verified prior value and physical lamp on |
| Gateway SIGKILL / Last Will | `offline`, automatic restart, then `online` |
| Mosquitto restart | gateway reconnected and republished operational state |
| Lamp-side Raspberry Pi reboot | both services auto-started and node states refreshed |
| ioBroker integration | connection true, availability online and verified node JSON received |
| ioBroker command publication | refresh, set and restore results received correctly |
| systemd logging | `PYTHONUNBUFFERED=1` produced immediate journal output |
| Final state | both validation nodes restored to their original 68% setting |

The final percentage above is a fact about the validation installation, not a generic default.

## Minimum regression sequence

Run this after meaningful gateway, protocol, queue, store, MQTT or systemd changes.

### 1. Update and run offline tests

```bash
git switch main
git pull --ff-only
git status --short
./scripts/run-tests.sh
```

Expected: all tests pass and no private file is staged.

### 2. Validate private configuration

```bash
sudo python3 sanlight_mqtt_gateway.py \
    --config private/sanlight-gateway.toml \
    --check
```

The output must not contain Mesh keys, DeviceKeys, passwords or BlueZ tokens.

### 3. Reinstall and inspect the service

```bash
sudo bash ./scripts/install-mqtt-gateway.sh \
    --config private/sanlight-gateway.toml

systemctl is-active sanlight-meshd-generic.service
systemctl is-active sanlight-mqtt-gateway.service
sudo journalctl -u sanlight-mqtt-gateway.service -n 50 --no-pager
```

### 4. Verify retained MQTT state

Subscribe with MQTT 5 and the configured automation user:

```bash
mosquitto_sub -V mqttv5 \
    -h BROKER \
    -q 1 \
    -v \
    -t 'sanlightmesh/v1/GATEWAY_ID/availability' \
    -t 'sanlightmesh/v1/GATEWAY_ID/gateway/info' \
    -t 'sanlightmesh/v1/GATEWAY_ID/nodes/+/state'
```

Expected: `online`, healthy sequence status and verified node states. A wrapper such as `timeout 10` normally exits with code `124`; that timeout is not a gateway failure.

### 5. Run a read-only refresh

Use a node address discovered from the CDB and a fresh timestamp/ID. Confirm a `verified` result and a refreshed retained node state.

### 6. Run one reversible write

Record the current value, set a safe temporary value in `20..100`, wait for a verified result, wait at least ten seconds, then restore the original value with a new command ID.

### 7. Re-run safety cases when affected code changes

At minimum validate:

- duplicate command ID;
- live retained command rejection;
- offline retained command suppression;
- expired command with no Mesh messages;
- same-node coalescing;
- write-rate guard;
- explicit blackout and restore when blackout code changed;
- gateway and broker restart recovery;
- full Raspberry Pi reboot when service/install files changed.

### 8. Verify ioBroker

Confirm:

- `mqtt.0.info.connection` is `true`;
- gateway availability is `online`;
- node state objects contain JSON strings with `verified: true`;
- a JavaScript-published read-only command receives its result.

## Safety boundary

Do not repeat destructive Mesh resets, replay recovery or blackout tests merely for documentation changes. Use the smallest test set justified by the changed files. Hardware claims require hardware evidence; unit tests alone cannot prove RF, D-Bus timing, broker behavior or systemd recovery.
