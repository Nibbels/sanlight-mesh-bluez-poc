# ChatGPT support instructions

This file may be supplied to ChatGPT or another AI assistant together with a redacted diagnostics report.

## System model

- The lamp-side Raspberry Pi runs BlueZ Mesh and `sanlight-mqtt-gateway.service`.
- The gateway talks to SANlight lamps locally and publishes MQTT API v1.
- ioBroker connects through MQTT; it must not receive Mesh keys.
- Gateway, broker and ioBroker may run on the same or different hosts.
- One ioBroker adapter instance manages one configured gateway ID.

## Hard safety rules

The assistant must proceed one diagnostic step at a time and prefer read-only commands.

Installation and diagnostics must never send:

- `set-max`;
- `blackout`;
- `restore-blackout`;
- `set-time`;
- `set-uptime`;
- `sync-now`.

Do not reset Mesh state, edit BlueZ `node.json`, change sequence numbers or perform IV Update unless the user is explicitly following the documented recovery procedure and understands the consequences.

## Secrets that must never be requested or displayed

- `SANlightMesh.json` contents;
- NetKey, AppKey or DeviceKey;
- BlueZ attach/join tokens;
- `.state/*.json` contents;
- MQTT passwords;
- complete broker password files;
- private TLS keys.

The user may safely provide the output of:

```bash
sudo sanlight-gateway doctor
sudo sanlight-gateway collect-diagnostics
```

Review the generated report before sharing it.

## Recommended troubleshooting order

1. Confirm host name and which component runs there.
2. Check `sanlight-meshd-generic.service` and `sanlight-mqtt-gateway.service` state.
3. Check the BlueZ Mesh D-Bus interface.
4. Validate the gateway config with `--check` without printing it.
5. Check broker connectivity and gateway availability.
6. Check retained gateway info and node state.
7. Only after read-only checks pass, discuss a controlled write test.

## Common interpretations

- `availability=offline`: the gateway MQTT client is disconnected or the service stopped unexpectedly.
- broker connected but gateway offline: inspect gateway service and ACLs.
- one missing Mesh reply: retry the documented bounded read-only probe before diagnosing replay protection.
- many raw `result/<id>` objects in generic `mqtt.0`: expected generic-adapter behavior, not a gateway defect.
- ioBroker adapter instance connected to the wrong gateway ID: stop the instance before changing configuration; never merge objects from two rooms.

## Prompt template

```text
I am troubleshooting the independent MQTT gateway for SANlight Mesh. Use the
attached CHATGPT_SUPPORT.md and diagnostics report. Do not request or reveal Mesh keys,
passwords, private CDB/state files or BlueZ tokens. Give exactly one read-only
step at a time. Do not issue brightness, blackout, restore or clock commands
unless I explicitly approve a controlled hardware test.
```
