# MQTT Gateway for SANlight Mesh 0.2.0

This is the first public GitHub release of the independent community gateway. It remains pre-1.0 and is intended for the documented Raspberry Pi / BlueZ Mesh topology.

## Highlights

- Complete Raspberry Pi installation with BlueZ Mesh, authenticated local Mosquitto and the always-on MQTT gateway.
- Native integration with `ioBroker.sanlightmesh` through MQTT API v1.
- Verified MaxBrightness reads and writes with a strict normal range of `20..100%`.
- Separate protected blackout and restore workflow.
- Read-only live lamp status including lamp clock, a one-decimal current-output percentage and the raw transport field retained for MQTT API v1 compatibility.
- Safe adoption of matching BlueZ identities, actionable IV Index recovery and protected sequence-state handling.
- Health, log and redacted-diagnostics helper.
- Offline tests, GitHub Actions and secret-free release archive tooling.

## Compatibility

The MQTT contract remains API v1. The live-output fields are additive; older API v1 clients may ignore them. The companion adapter release is `ioBroker.sanlightmesh v0.2.0`.

## Important limitations

- Hardware comparison confirmed `33.4%` from the gateway against the SANlight app's rounded `34%` display; the value is still not calibrated watts, photon flux or PPFD.
- Do not expose MQTT port 1883 to the internet.
- Do not copy Mesh keys, CDB exports or `.state/` between independent active gateways.
- Sequence recovery and destructive Mesh rebuild procedures are advanced recovery operations, not normal update steps.

## Upgrade

Pull or extract the release, run the offline tests, then rerun the installer with the existing configuration. Preserve the newest valid Bluetooth Mesh sequence state during upgrades and rollbacks. See `docs/RELEASES.md`.
