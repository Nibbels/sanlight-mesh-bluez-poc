# SANlight Mesh MQTT API v1

The gateway topic root is:

```text
sanlightmesh/v1/<gateway-id>
```

The protocol major version is part of the topic. During the project's pre-1.0 releases, coordinated compatibility changes may remain on `v1` when they are called out explicitly in both repositories. The v0.3.0 clock work deliberately replaces `lampTimeMs` with second-resolution fields.

Examples below use the illustrative unicast address `1234`. Replace it with an address reported by `list-nodes` for the actual CDB.

## Topics

| Topic                 |  Retained | Purpose                                                |
| --------------------- | --------: | ------------------------------------------------------ |
| `availability`        |       yes | `online` or Last-Will `offline`                        |
| `gateway/info`        |       yes | gateway, nodes, traffic policy and sequence budget     |
| `nodes/<NODE>/meta`   |       yes | stable node metadata                                   |
| `nodes/<NODE>/state`  |       yes | last verified MaxBrightness and live lamp-output state |
| `command`             | **never** | ioBroker/client requests                               |
| `result/<COMMAND_ID>` |        no | final result for one request ID                        |

Command messages must be non-retained. Recommended QoS is 1. Application-level command IDs provide deduplication because QoS 1 may redeliver.

The gateway uses MQTT 5 subscription options `retainAsPublished=true` and `retainHandling=DO_NOT_SEND`:

- a live retained publication remains detectable and is rejected;
- retained commands stored while the gateway is offline are not delivered after reconnect.

## Common command fields

```json
{
	"id": "unique-command-id",
	"action": "refresh",
	"target": "1234",
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
	"id": "refresh-1234-001",
	"action": "refresh",
	"target": "1234",
	"createdAt": "2026-07-15T20:30:00Z",
	"ttlSeconds": 30
}
```

Use target `all` to refresh every detected SANlight node. For each target, the
gateway reads both configured MaxBrightness and `GetUptimeAndBrightness` live
status. Refresh is read-only but normally sends at least two Mesh application
queries per lamp, plus any bounded retries, so it still consumes Sequence
Numbers.

### Set MaxBrightness

```json
{
	"id": "set-1234-48-001",
	"action": "set-max",
	"target": "1234",
	"value": 48,
	"createdAt": "2026-07-15T20:30:00Z",
	"ttlSeconds": 30
}
```

`value` is strictly `20..100`. Zero is rejected here and exists only in the
explicit blackout workflow. A successful `verified` result means the hardened
CLI read the configured percentage back from the lamp. After that verification,
the gateway also requests one live-status sample. Failure of this additional
read does not make the already verified MaxBrightness write fail; instead,
`liveVerified` becomes false and the result may include `details.liveError`.

Separate brightness writes are subject to the persistent ten-second guard. A command whose TTL expires while waiting for that guard returns `expired` with `details.meshMessagesSent = 0`.

### Synchronize lamp clock

```json
{
	"id": "sync-clock-1234-001",
	"action": "sync-clock",
	"target": "1234",
	"createdAt": "2026-07-17T18:30:00Z",
	"ttlSeconds": 30
}
```

Use target `all` to synchronize every lamp. The gateway samples its current local clock immediately before each sequential lamp write. This command simply copies the gateway's current local clock.

On the validated two-lamp setup, restoring lamp power reset both lamp clocks to `00:00:00`. The gateway does not synchronize automatically after power loss; an MQTT client or operator must explicitly trigger `sync-clock`.

### Set arbitrary lamp clock

```json
{
	"id": "set-clock-1234-001",
	"action": "set-clock",
	"target": "1234",
	"secondsSinceMidnight": 21600,
	"createdAt": "2026-07-17T18:30:00Z",
	"ttlSeconds": 30
}
```

`secondsSinceMidnight` is a strict integer in `0..86399`. MQTT transports no clock strings or milliseconds. For target `all`, the gateway adds monotonic elapsed time before each sequential write so the lamps finish approximately aligned. Every write is followed by a live readback and verified with a five-second tolerance. Per-lamp outcomes are returned below `details.nodes`.

### Refresh gateway information

```json
{
	"id": "refresh-gateway-info-001",
	"action": "refresh-gateway-info",
	"target": "gateway",
	"createdAt": "2026-07-17T18:30:00Z",
	"ttlSeconds": 30
}
```

This republishes retained `gateway/info` with a fresh local-clock snapshot. It performs no Bluetooth Mesh operation and consumes no Mesh Sequence Number.

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
	"id": "set-1234-48-001",
	"ok": true,
	"status": "verified",
	"message": "Node 1234 reports MaxBrightness 48% as requested.",
	"action": "set-max",
	"target": "1234",
	"requested": 48,
	"details": {
		"reported": { "1234": 48 },
		"liveReported": {
			"1234": {
				"lampClockSeconds": 61265,
				"lampClock": "17:01:05",
				"liveBrightnessRaw": 461,
				"liveBrightnessPercentEstimate": 46.1
			}
		},
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

When a completed QoS 1 command ID is delivered again, the gateway republishes the stored final result without a second Mesh transaction. The result details include `duplicateDelivery: true`.

## Node state example

```json
{
	"protocolVersion": 1,
	"address": "1234",
	"name": "Example lamp",
	"maxBrightness": 68,
	"off": false,
	"verified": true,
	"verifiedAt": "2026-07-16T20:30:04Z",
	"liveVerified": true,
	"lampClockSeconds": 61265,
	"lampClock": "17:01:05",
	"liveBrightnessRaw": 461,
	"liveBrightnessPercentEstimate": 46.1,
	"liveVerifiedAt": "2026-07-16T20:30:05Z"
}
```


`lampClockSeconds` is the last observed lamp time as an integer in `0..86399`; `lampClock` is the same snapshot rendered as `HH:MM:SS`. These states do not tick between reads. The former `lampTimeMs` field is removed in v0.3.0; millisecond handling remains internal to the vendor protocol layer.

`maxBrightness` and `liveBrightnessRaw` describe different things:

- `maxBrightness` is the configured daily-profile scaling limit;
- `liveBrightnessRaw` is the current effective-output field returned by the lamp;
- `liveBrightnessPercentEstimate` is the empirical calculation `raw / 10`.

The estimate is useful for relative automation and comparison, but it is not a
calibrated watt, photon-flux or PPFD measurement. The raw value remains available
for full vendor-response validation, compatibility and comparisons across more
hardware and firmware versions.

`liveVerified=false` means no valid current live-status sample accompanied the
latest update. In that case the live value fields are omitted. Older MQTT API v1
gateways may omit `liveVerified` entirely; clients should interpret that as live
status unavailable.

Only verified values update retained node state. `maxBrightness: 0` with
`off: true` is valid only after a verified explicit blackout or an external
change observed by refresh. Blackout and restore verify MaxBrightness but do not
perform a live-status read, so they invalidate the retained live sample until the
next refresh.

The raw uint16 field remains in API v1 so clients can validate the complete vendor
response and existing consumers remain compatible. User interfaces should
normally display `liveBrightnessPercentEstimate`. A hardware comparison produced
`33.4%` while the SANlight app showed the same value rounded to `34%`. The
percentage is not calibrated watts, photon flux or PPFD.

## Gateway information

The retained `gateway/info` object includes:

- `protocolVersion` and `serviceVersion`;
- gateway and sender identifiers;
- detected node metadata;
- current sender Sequence Number and remaining 24-bit budget;
- `sequenceStatus`;
- effective write policy, including minimum and recommended intervals;
- `localClockSeconds` and `localClock`, sampled when the gateway-info payload is published. The existing `timestamp` identifies the snapshot time.

## Schemas

Machine-readable schemas are in `schemas/`:

- `command-v1.schema.json`
- `result-v1.schema.json`
- `node-meta-v1.schema.json`
- `node-state-v1.schema.json`
- `gateway-info-v1.schema.json`
