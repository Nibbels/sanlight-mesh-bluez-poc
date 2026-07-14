"""Command-line interface with offline preflight support."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .cdb import (
    CdbError,
    MeshMaterial,
    load_mesh_material,
    safe_summary,
    validate_destination,
    validate_material_pair,
)
from .protocol import (
    parse_clock_time,
    parse_destination,
    parse_destination_or_all,
    validate_max_brightness,
    validate_uptime_milliseconds,
    validate_uptime_seconds,
)
from .locking import LockError, exclusive_runtime_lock
from .state import StateError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DIR = PROJECT_ROOT / ".state"
DEFAULT_CONTROL_STATE = DEFAULT_STATE_DIR / "control-provisioner.json"
DEFAULT_SENDER_STATE = DEFAULT_STATE_DIR / "canonical-sender.json"


class CliError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SANlight canonical App-ID source via BlueZ Bluetooth Mesh"
    )
    parser.add_argument(
        "--cdb",
        type=Path,
        required=True,
        help="path to the private SANlightMesh.json export",
    )
    parser.add_argument(
        "--control-app-id",
        type=int,
        default=1,
        choices=range(0, 16),
        metavar="0..15",
        help="CDB provisioner used as Configuration Client; default: 1",
    )
    parser.add_argument(
        "--sender-app-id",
        type=int,
        default=2,
        choices=range(0, 16),
        metavar="0..15",
        help="CDB provisioner used as canonical source; default: 2",
    )
    parser.add_argument(
        "--iv-index",
        type=lambda value: int(value, 0),
        default=None,
        help="current Mesh IV Index; required for initial setup when absent from CDB",
    )
    parser.add_argument(
        "--provisioner-state",
        type=Path,
        default=DEFAULT_CONTROL_STATE,
        help=f"control identity state; default: {DEFAULT_CONTROL_STATE}",
    )
    parser.add_argument(
        "--sender-state",
        type=Path,
        default=DEFAULT_SENDER_STATE,
        help=f"canonical sender state; default: {DEFAULT_SENDER_STATE}",
    )

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "inspect", help="validate both CDB identities and print a redacted JSON summary"
    )
    commands.add_parser(
        "list-nodes", help="list detected SANlight lamp and group addresses"
    )
    commands.add_parser(
        "setup",
        help="import/configure local identities, bind AppKey 0 and set sender TTL 5",
    )

    get_live = commands.add_parser(
        "get-live", help="read lamp time and brightness from one unicast node"
    )
    get_live.add_argument("destination", type=parse_destination)

    get_net_tx = commands.add_parser(
        "get-net-tx", help="read Config Network Transmit via control identity"
    )
    get_net_tx.add_argument("destination", type=parse_destination)

    get_net_tx_sender = commands.add_parser(
        "get-net-tx-sender",
        help=(
            "diagnostic: read Config Network Transmit via canonical sender "
            "identity (read-only)"
        ),
    )
    get_net_tx_sender.add_argument("destination", type=parse_destination)

    set_max = commands.add_parser(
        "set-max", help="set MaxBrightness; safety range is strictly 20..100"
    )
    set_max.add_argument("destination", type=parse_destination)
    set_max.add_argument("percent", type=int)

    set_uptime = commands.add_parser(
        "set-uptime", help="set lamp clock using seconds since local midnight"
    )
    set_uptime.add_argument("destination", type=parse_destination_or_all)
    set_uptime.add_argument("seconds", type=int)

    set_time = commands.add_parser(
        "set-time", help="set lamp clock to HH:MM[:SS] on one node or all nodes"
    )
    set_time.add_argument("destination", type=parse_destination_or_all)
    set_time.add_argument("milliseconds", type=parse_clock_time)

    sync_now = commands.add_parser(
        "sync-now", help="set lamp clock to current Raspberry Pi local time"
    )
    sync_now.add_argument(
        "destination", nargs="?", type=parse_destination_or_all, default=None
    )
    sync_now.add_argument("--offset-seconds", type=int, default=0)
    sync_now.add_argument(
        "--offset-ms", dest="offset_milliseconds", type=int, default=0
    )

    commands.add_parser(
        "leave-sender",
        help="remove only the local canonical sender identity from bluetooth-meshd",
    )
    return parser


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _validate_iv_index(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("IV Index must be between 0 and 4294967295 inclusive")
    return value


def _validate_node_destination(
    material: MeshMaterial, destination: int, command: str
) -> None:
    validate_destination(material, destination)
    if destination not in material.node_names:
        raise ValueError(f"{command} requires a CDB node/unicast destination, not a group")


def validate_args(args: argparse.Namespace, control: MeshMaterial) -> None:
    args.iv_index = _validate_iv_index(args.iv_index)
    if args.command in ("get-live", "get-net-tx", "get-net-tx-sender"):
        _validate_node_destination(control, args.destination, args.command)
    elif args.command == "set-max":
        validate_destination(control, args.destination)
        validate_max_brightness(args.percent)
    elif args.command in ("set-uptime", "set-time", "sync-now"):
        if args.destination is None:
            if not control.sanlight_nodes:
                raise ValueError("CDB contains no SANlight lamp nodes for destination 'all'")
        else:
            _validate_node_destination(control, args.destination, args.command)
        if args.command == "set-uptime":
            validate_uptime_seconds(args.seconds)
        elif args.command == "set-time":
            validate_uptime_milliseconds(args.milliseconds)


def print_node_overview(control: MeshMaterial, cdb_path: Path) -> None:
    print("SANlight node/address overview")
    print("==============================")
    print(f"CDB file: {cdb_path}")
    print("\nDetected SANlight lamp nodes (unicast targets):")
    if control.sanlight_nodes:
        print("  NODE_ADDRESS  HEX_ADDRESS  NAME")
        for address, name in sorted(control.sanlight_nodes.items()):
            print(f"  {address:04X}          0x{address:04X}       {name}")
        print(
            "\nNODE_ADDRESS is the four-digit unicast value in the first column."
        )
        print("Use a node address, not a CDB group address, with get-live.")
    else:
        print("  none detected")
    print("\nGroups from CDB:")
    if control.groups:
        for address, name in sorted(control.groups.items()):
            print(f"  {address:04X}  0x{address:04X}  {name}")
    else:
        print("  none")
    print("\nRead-only verification example:")
    if control.sanlight_nodes:
        first = min(control.sanlight_nodes)
        print(
            "  sudo python3 sanlight_canonical_sender_poc.py "
            f"--cdb {cdb_path} get-live {first:04X}"
        )
    else:
        print("  no unicast SANlight node available")
    print("\nWriting commands are documented separately in INSTRUCTIONS.md.")


def _load_material(args: argparse.Namespace) -> tuple[MeshMaterial, MeshMaterial]:
    control = load_mesh_material(args.cdb, args.control_app_id)
    sender = load_mesh_material(args.cdb, args.sender_app_id)
    validate_material_pair(control, sender, args.control_app_id, args.sender_app_id)
    if args.iv_index is None:
        args.iv_index = control.cdb_iv_index
    return control, sender


def _run_runtime(
    args: argparse.Namespace, control: MeshMaterial, sender: MeshMaterial
) -> int:
    try:
        from .bluez_runtime import BluezRuntime, BluezRuntimeError
    except ImportError as exc:
        missing = getattr(exc, "name", None) or str(exc)
        raise CliError(
            "BlueZ runtime dependency is missing "
            f"({missing}). Install packages with scripts/setup-all.sh."
        ) from exc

    lock_file = args.sender_state.parent / "runtime.lock"
    try:
        with exclusive_runtime_lock(lock_file):
            return BluezRuntime(args, control, sender).run()
    except (BluezRuntimeError, LockError) as exc:
        raise CliError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = build_parser()
    args = parser.parse_args(argv)
    args.cdb = _resolve_path(args.cdb)
    args.provisioner_state = _resolve_path(args.provisioner_state)
    args.sender_state = _resolve_path(args.sender_state)

    try:
        control, sender = _load_material(args)
        validate_args(args, control)

        if args.command == "inspect":
            print(
                json.dumps(
                    safe_summary(
                        control, sender, args.control_app_id, args.sender_app_id
                    ),
                    indent=2,
                    ensure_ascii=False,
                )
            )
            print("Secret NetKey/AppKey/DeviceKey values are intentionally not printed.")
            print("Local BlueZ state tokens are intentionally not printed.")
            if control.cdb_iv_index is None:
                print("NOTE: CDB has no ivIndex; initial setup requires --iv-index <value>.")
            return 0

        if args.command == "list-nodes":
            print_node_overview(control, args.cdb)
            return 0

        if args.command == "setup" and args.iv_index is None:
            raise ValueError(
                "CDB has no ivIndex. Pass the verified current value with --iv-index."
            )
        return _run_runtime(args, control, sender)
    except (CdbError, StateError, ValueError, CliError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
