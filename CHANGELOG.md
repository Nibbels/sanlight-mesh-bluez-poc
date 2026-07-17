# Changelog

All notable changes to this community project are documented here. The project is pre-1.0; release notes must identify configuration or protocol compatibility changes explicitly.

## Unreleased

- Add explicit MQTT clock controls for one lamp or all lamps: `sync-clock`, `set-clock` and the Mesh-free `refresh-gateway-info` action.
- Replace MQTT `lampTimeMs` with `lampClockSeconds` (`0..86399`) and second-resolution `lampClock`; keep millisecond handling internal to the vendor protocol implementation.
- Publish the gateway local-clock snapshot in retained `gateway/info`, verify every clock write by live readback, and report partial per-lamp outcomes.

## 0.2.0 - 2026-07-17

- Make GitHub Actions invoke repository shell scripts through `bash`, so CI does not depend on executable bits preserved by the checkout platform.
- Verify the generated release checksum and rerun the complete offline safety suite from the extracted release archive.
- Restore explicit release-archive exclusions for the ioBroker MQTT password file and the managed Mosquitto password database.
- Add an offline GitHub Actions regression gate for Python 3.11 and 3.13, shell syntax and secret-free release archives.
- Replace the oversized first-line operations document with a short operator guide while preserving the complete technical reference under `docs/ADVANCED_REFERENCE.md`.
- Add explicit release metadata and first-public-release notes.
- Use neutral gateway wording in the installed doctor output.
- Prevent root-run doctor and diagnostic repository checks from refreshing or rewriting the Git index by disabling Git optional locks for all read-only repository inspection.
- Extend read-only MQTT node state with lamp time and current effective-output data from `GetUptimeAndBrightness`; preserve the raw uint16 value, expose the empirical `raw / 10` percentage estimate separately, and keep MaxBrightness as the independent configured schedule scaling limit.
- Standardize public documentation and service descriptions so the independent gateway is not presented as an official SANlight product; retain SANlight names only for compatibility and protocol references.
- Make IV Index installation failures actionable: clarify that normal installs require no manual value, document trusted sources and exact recovery steps, and improve the CLI error without changing identity selection or Mesh state behavior.
- Clarify the SANlight app App-ID, CDB provisioner identity, Mesh source address, AppKey index and AID terminology without changing gateway behavior.
- Simplify the public README and first-time setup path, remove duplicated adapter configuration, and clarify the gateway-to-adapter handoff.
- Add the MIT license used by the companion adapter repository.
- Rename the repository to `sanlight-mesh-mqtt-gateway`.
- Define the two-repository architecture with `ioBroker.sanlightmesh` as the companion adapter.
- Add the interactive gateway configuration and installation wrapper.
- Add the `sanlight-gateway` health, log and redacted-diagnostics helper.
- Add secret-free tagged release archive tooling without introducing Debian packaging.
- Add architecture, installer, release, security and AI-assisted support documentation.
- Add and strengthen MQTT v1 JSON schemas, including node metadata.

## 0.1.1 - 2026-07-15

- Hardware-validate the always-on MQTT gateway with two SANlight nodes.
- Harden retained-command handling using MQTT 5 subscription options.
- Validate deduplication, expiry, coalescing, rate limiting, blackout/restore, broker restart, gateway restart and full host reboot recovery.
- Enable unbuffered systemd journal logging.

## 0.1.0 - 2026-07-15

- Add the first MQTT API v1 gateway implementation and systemd service.
