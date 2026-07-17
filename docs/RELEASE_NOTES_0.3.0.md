# MQTT Gateway for SANlight Mesh 0.3.0

This release adds explicit manual lamp-clock control to the independent
community gateway. It remains pre-1.0 and is intended for the documented
Raspberry Pi / BlueZ Mesh topology.

## Highlights

- Read lamp clocks as whole seconds since midnight and as `HH:MM:SS` snapshots.
- Synchronize one lamp or all lamps to the gateway Raspberry Pi's current local time.
- Apply an arbitrary `0..86399` seconds-since-midnight target to one lamp or all lamps.
- Refresh the retained gateway local-clock snapshot without a Bluetooth Mesh operation or Sequence Number use.
- Verify every clock write by live readback with per-lamp outcomes and elapsed-time compensation for sequential all-lamp targets.
- Use clearer refresh and all-lamp result messages.
- Hardware-validate the complete workflow on two real lamps, including a power cycle and recovery synchronization.

## Compatibility

The MQTT topic contract remains API v1, but this is a coordinated pre-1.0
compatibility change: external `lampTimeMs` is removed and replaced by
`lampClockSeconds` plus second-resolution `lampClock`. Millisecond handling
remains internal to the SANlight vendor protocol implementation. Update the
gateway and companion `ioBroker.sanlightmesh` adapter together to v0.3.0.

MaxBrightness, live effective-output reporting, blackout protection, queueing,
rate limits and sequence-state safety are unchanged.

## Power-loss behavior

On the validated two-lamp reference setup, restoring lamp power reset both lamp
clocks to `00:00:00`. The gateway deliberately does not synchronize
automatically. After a power interruption, wait until the lamps are reachable,
perform a read-only refresh where useful, and explicitly trigger clock
synchronization.

## Important limitations

- Clock states are snapshots and do not tick inside MQTT or ioBroker.
- There is no automatic synchronization, drift alarm, NTP check, timezone or DST policy, or background lamp polling.
- Lamp reads and clock writes consume Bluetooth Mesh Sequence Numbers; `refresh-gateway-info` does not.
- Do not expose MQTT port 1883 to the internet.
- Do not copy Mesh keys, CDB exports or `.state/` between independent active gateways.

## Upgrade

Pull or extract the release, run the offline tests, then rerun the installer with
the existing configuration. Preserve the newest valid Bluetooth Mesh sequence
state during upgrades and rollbacks. See `docs/RELEASES.md`.
