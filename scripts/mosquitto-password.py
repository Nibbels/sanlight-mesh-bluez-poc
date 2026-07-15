#!/usr/bin/env python3
"""Update a Mosquitto password file without putting the password in argv."""

from __future__ import annotations

import argparse
import os
import pty
import select
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--password-db", required=True, type=Path)
    parser.add_argument("--username", required=True)
    parser.add_argument("--secret-file", required=True, type=Path)
    parser.add_argument("--create", action="store_true")
    parser.add_argument(
        "--executable",
        default="/usr/bin/mosquitto_passwd",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def load_secret(path: Path) -> bytes:
    value = path.read_bytes().rstrip(b"\r\n")
    if not value:
        raise SystemExit("ERROR: MQTT password file is empty")
    if b"\x00" in value or b"\n" in value or b"\r" in value:
        raise SystemExit("ERROR: MQTT password must be one non-empty line")
    return value


def run_interactive(argv: list[str], secret: bytes) -> None:
    pid, master_fd = pty.fork()
    if pid == 0:
        os.execv(argv[0], argv)

    transcript = bytearray()
    sent = 0
    deadline = time.monotonic() + 20.0
    status: int | None = None

    try:
        while time.monotonic() < deadline:
            waited_pid, waited_status = os.waitpid(pid, os.WNOHANG)
            if waited_pid == pid:
                status = waited_status
                break

            readable, _, _ = select.select([master_fd], [], [], 0.1)
            if not readable:
                continue

            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                chunk = b""
            if not chunk:
                continue

            transcript.extend(chunk.lower())
            prompt_count = transcript.count(b"password:")
            while sent < min(prompt_count, 2):
                os.write(master_fd, secret + b"\n")
                sent += 1

        if status is None:
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass
            _, status = os.waitpid(pid, 0)
            raise SystemExit("ERROR: mosquitto_passwd did not finish in time")
    finally:
        os.close(master_fd)

    if sent != 2 or not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise SystemExit("ERROR: mosquitto_passwd failed")


def main() -> None:
    args = parse_args()
    secret = load_secret(args.secret_file)
    executable = str(Path(args.executable).resolve())
    argv = [executable]
    if args.create:
        argv.append("-c")
    argv.extend([str(args.password_db), args.username])
    run_interactive(argv, secret)


if __name__ == "__main__":
    main()
