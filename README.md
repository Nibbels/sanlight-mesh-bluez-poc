![Visual overview of SANlight Bluetooth Mesh control via Raspberry Pi](docs/sanlight_mesh_steuerung_ueber_raspberry_pi.png)

# SANlight Mesh BlueZ PoC

Control SANlight EVO Bluetooth Mesh dimmers from a Raspberry Pi with BlueZ and Python. The validated implementation can read lamp time and brightness, synchronize the internal lamp clock, and set MaxBrightness without the SANlight app.

Validated platform: **Raspberry Pi OS Lite 64-bit / Debian 13 trixie, BlueZ 5.82, `bluetooth-meshd --io generic:hci0`**.

> **Private data:** `SANlightMesh.json`, NetKey, AppKey, DeviceKey and local BlueZ state tokens must never be committed, published, pasted into issues, or shared in logs.

## Documentation

- **[SETUP.md](SETUP.md)** — minimal first-time installation
- **[INSTRUCTIONS.md](INSTRUCTIONS.md)** — commands, operation, maintenance and troubleshooting
- **[AI_CONTEXT.md](AI_CONTEXT.md)** — architecture, protocol findings and continuation context
- **[docs/MQTT_GATEWAY.md](docs/MQTT_GATEWAY.md)** — optional Wi-Fi/MQTT edge gateway and ioBroker path

> Unofficial community project. Not affiliated with or endorsed by SANlight GmbH.
