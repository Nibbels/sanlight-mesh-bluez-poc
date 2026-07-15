# Changelog

All notable changes to this community project are documented here. The project is pre-1.0; release notes must identify configuration or protocol compatibility changes explicitly.

## Unreleased

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
