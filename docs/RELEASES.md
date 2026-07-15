# Releases and updates

## Maintenance strategy

The project intentionally avoids Debian packaging for now. The expected user base and long-term support burden are unknown, and a package repository would add more maintenance than the runtime currently needs.

Use tagged GitHub release archives instead:

```text
sanlight-mesh-mqtt-gateway-<version>.tar.gz
sanlight-mesh-mqtt-gateway-<version>.tar.gz.sha256
```

The archive contains application code, tests, schemas, systemd templates and documentation. It must never contain private CDB files, `.state/`, logs, packet captures or MQTT passwords.

## Build a release archive

From a clean checkout:

```bash
scripts/release-archive.sh 0.2.0
```

The script refuses a dirty worktree, uses `git archive`, verifies the archive listing and writes a SHA-256 file below `dist/`.

## Update an installed gateway

1. Back up `/etc/sanlight-mesh-mqtt-gateway/` and the private state directory.
2. Extract the new release into a new directory.
3. Run the offline tests.
4. Reinstall the service with the existing configuration; the installer updates only `gateway.project_root` to the new release directory and preserves the remaining settings and secrets.
5. Verify retained availability and node state.

Example:

```bash
./scripts/run-tests.sh
sudo bash scripts/install-gateway.sh \
    --config /etc/sanlight-mesh-mqtt-gateway/gateway.toml \
    --reuse-existing
sudo sanlight-gateway doctor
```

Never copy a stale `.state/` directory from another active gateway. Sequence state belongs to one sender identity.

## Rollback

A rollback may restore application code and systemd templates, but must not roll back Bluetooth Mesh sequence state. Preserve the newest valid sender and gateway state. A code rollback that also restores an old sequence counter can trigger replay rejection.
