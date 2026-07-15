#!/usr/bin/env python3
"""Stable entrypoint for the optional MQTT edge gateway."""
from sanlight_mesh.gateway_service import main


if __name__ == "__main__":
    raise SystemExit(main())
