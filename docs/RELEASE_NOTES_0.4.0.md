# MQTT Gateway for SANlight Mesh 0.4.0

This release adds read-only access to the daylight configuration currently
stored in each SANlight lamp. The independent community gateway remains pre-1.0
and is intended for the documented Raspberry Pi / BlueZ Mesh topology.

## Highlights

- Read the stored daylight configuration from one lamp or all detected lamps with
  the dedicated `get-daylight` CLI command and MQTT `read-daylight` action.
- Keep normal startup, periodic and manual refresh behavior unchanged; daylight
  data is requested only when explicitly triggered.
- Prefer the combined `0x0E`/`0x0F` operation and retain a bounded
  configuration-only `0x03`/`0x04` fallback for missing or unknown responses.
- Parse the hardware-confirmed configuration ID, profile name and ordered
  minute/brightness datapoints while retaining the complete raw PDU and
  parameters for diagnostics and future firmware variants.
- Expose combined-response snapshots for lamp time, live brightness and
  MaxBrightness together with the stored profile.
- Preserve the last verified parsed profile when a later read times out or
  returns an unknown layout.
- Support verified per-lamp results and sequential all-lamp reads without
  treating different valid profiles as a transport failure.

## Compatibility

The MQTT topic contract remains API v1. Version 0.4.0 adds the new
`read-daylight` action and an optional retained `daylightConfiguration` section
below each node state. Existing v0.3.0 clients that ignore unknown fields can
continue using brightness and clock functionality, but the companion
`ioBroker.sanlightmesh` adapter must be updated to v0.4.0 to expose and interpret
the daylight data.

No daylight write opcode is implemented. MaxBrightness, live effective-output
reporting, manual lamp-clock control, blackout protection, queueing, rate limits
and sequence-state safety remain unchanged.

## Hardware validation

The reader was validated on two real lamps using repeated direct reads and MQTT
all-lamp reads. Captured configurations included:

- matching 12:12 profiles with eight datapoints and 30-minute ramps;
- a mixed 18:6 and 12:12 setup; and
- two-point all-dark profiles from `00:00` to `24:00`.

All responses parsed directly from the combined `0x0F` status without fallback,
retained node state matched the command results, and the gateway remained
healthy. The final offline suite contains 164 tests with real captured fixtures
for all three profile shapes.

## Important limitations

- The gateway transports and validates the stored profile but deliberately does
  not classify flowering, vegetative or other cultivation states. Policy and
  photoperiod interpretation belong in clients such as the companion adapter.
- Reads are snapshots. The gateway does not poll daylight profiles automatically.
- All-lamp reads are sequential and consume Bluetooth Mesh Sequence Numbers.
- Unknown firmware layouts are preserved as raw hexadecimal and return a partial
  result instead of overwriting the last verified profile.
- The implementation has been validated against the documented reference lamps
  and firmware; other models or firmware revisions require their own evidence.

## Installation

Use the release archive attached to the GitHub release, verify its SHA-256 file,
extract it into a new directory, run the offline tests, and reinstall while
reusing the existing configuration and protected Mesh state. Never restore an
older Bluetooth Mesh sequence-state directory during an update or rollback.
