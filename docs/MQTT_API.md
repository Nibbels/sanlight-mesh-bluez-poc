# SANlight Mesh MQTT API v1

The gateway topic root is:

```text
sanlightmesh/v1/<gateway-id>
```

The protocol major version is part of the topic. Breaking changes require a new major topic such as `v2`.

## Topics

| Topic | Retained | Purpose |
|---|---:|---|
| `availability` | yes | `online` or Last-Will `offline` |
| `gateway/info` | yes | gateway, nodes, traffic policy and sequence budget |
| `nodes/<NODE>/meta` | yes | stable node metadata |
| `nodes/<NODE>/state` | yes | last verified MaxBrightness state |
| `command` | **never** | ioBroker/client requests |
| `result/<COMMAND_ID>` | no | final result for one request ID |

Command messages must be non-retained. Recommended QoS is 1. Application-level command IDs provide deduplication because QoS 1 may redeliver. The gateway uses MQTT 5 subscription options `retainAsPublished=true` and `retainHandling=DO_NOT_SEND` so a live retained publication remains detectable while retained commands stored during downtime are never replayed to the gateway.

## Common command fields

```json
{
  "id": "unique-command-id",
  "action": "refresh",
  "target": "0003",
  "createdAt": "2026-07-15T20:30:00Z",
  "ttlSeconds": 30
}
```

Rules:

- `id` is unique for the intended action;
- `createdAt` includes a timezone;
- `ttlSeconds` is `1..300`;
- stale commands are rejected before Mesh transmission;
- retained commands are always rejected;
- node addresses are four hexadecimal digits and must exist in the CDB;
- MQTT cannot supply file paths, shell commands or arbitrary CLI options.

## Actions

### Refresh

```json
{
  "id": "refresh-0003-001",
  "action": "refresh",
  "target": "0003",
  "createdAt": "2026-07-15T20:30:00Z",
  "ttlSeconds": 30
}
```

Use target `all` to refresh every detected SANlight node. Refresh is read-only but still consumes Mesh Sequence Numbers.

### Set MaxBrightness

```json
{
  "id": "set-0003-48-001",
  "action": "set-max",
  "target": "0003",
  "value": 48,
  "createdAt": "2026-07-15T20:30:00Z",
  "ttlSeconds": 30
}
```

`value` is strictly `20..100`. Zero is rejected here and exists only in the explicit blackout workflow. A successful result means the hardened CLI read the configured percentage back from the lamp.

### Blackout

```json
{
  "id": "blackout-all-001",
  "action": "blackout",
  "target": "all",
  "confirmed": true,
  "createdAt": "2026-07-15T20:30:00Z",
  "ttlSeconds": 120
}
```

Target may be one node or `all`. The gateway uses the protected snapshot workflow and verifies zero readback. `confirmed=true` is mandatory.

### Restore latest blackout

```json
{
  "id": "restore-blackout-001",
  "action": "restore-blackout",
  "target": "latest",
  "confirmed": true,
  "createdAt": "2026-07-15T20:30:00Z",
  "ttlSeconds": 180
}
```

MQTT v1 deliberately accepts only `latest`; callers cannot supply local paths.

## Result example

```json
{
  "protocolVersion": 1,
  "id": "set-0003-48-001",
  "ok": true,
  "status": "verified",
  "message": "Node 0003 reports MaxBrightness 48% as requested.",
  "action": "set-max",
  "target": "0003",
  "requested": 48,
  "details": {
    "reported": {"0003": 48},
    "exitCode": 0
  },
  "timestamp": "2026-07-15T20:30:04Z"
}
```

Important statuses include:

- `verified`
- `no-op`
- `superseded`
- `expired`
- `rejected`
- `queue-full`
- `unconfirmed`
- `partial`
- `failed`
- `gateway-error`
- `indeterminate-after-restart`

`superseded` means a newer pending setpoint for the same node replaced the older request before any Bluetooth message was sent.

`indeterminate-after-restart` means the gateway persisted an in-flight marker, then stopped before it could store a final result. The same command ID is deliberately not executed again. Refresh the node state and decide whether a new write with a new ID is needed.

## Node state example

```json
{
  "protocolVersion": 1,
  "address": "0003",
  "name": "3-60 1.5 Rechts",
  "maxBrightness": 48,
  "off": false,
  "verified": true,
  "verifiedAt": "2026-07-15T20:30:04Z"
}
```

Only verified values update retained node state.

## Schemas

Machine-readable schemas are in `schemas/`:

- `command-v1.schema.json`
- `result-v1.schema.json`
- `node-state-v1.schema.json`
- `gateway-info-v1.schema.json`
