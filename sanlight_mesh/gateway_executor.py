"""Typed execution backend for the MQTT gateway.

The first gateway release intentionally reuses the already hardware-validated CLI
transaction engine in a child process. ``bluetooth-meshd`` remains persistent; the
child only attaches the local D-Bus application for one serialized transaction.
No shell is involved and MQTT input never becomes an executable path or option.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from .gateway_config import GatewayConfig
from .gateway_protocol import GatewayCommand
from .protocol import LiveStatus


_GET_MAX_RE = re.compile(
    r"GET-MAX COMPLETE\. Node 0x([0-9A-F]{4}) reports MaxBrightness (\d+)%"
)
_GET_LIVE_RE = re.compile(
    r"GET-LIVE COMPLETE\. Node 0x([0-9A-F]{4}) reports "
    r"lampTimeMs=(\d+) lampClock=([0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}) "
    r"liveBrightnessRaw=(\d+) "
    r"liveBrightnessPercentEstimate=([0-9]+(?:\.[0-9]+)?)%\."
)
_SEQUENCE_RE = re.compile(
    r"sequenceNumber=(\d+) \(0x[0-9A-Fa-f]+\).*?sequenceRemaining=(\d+)",
    re.DOTALL,
)
_STATUS_VALUE_RE = re.compile(r"from 0x([0-9A-F]{4}): (\d+)%")
_NODE_VALUE_RE = re.compile(
    r"Node 0x([0-9A-F]{4}) (?:already )?reports(?: MaxBrightness)? (\d+)%"
)
_FINAL_VALUE_RE = re.compile(r"0x([0-9A-F]{4})=(\d+)%")


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def summary(self) -> str:
        lines = [line.strip() for line in (self.stdout + "\n" + self.stderr).splitlines()]
        useful = [line for line in lines if line]
        return useful[-1][:500] if useful else f"process exited {self.exit_code}"


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    status: str
    message: str
    reported: Mapping[str, int]
    details: Mapping[str, object]
    live_reported: Mapping[str, LiveStatus] = field(default_factory=dict)


class GatewayExecutionError(RuntimeError):
    pass


class CliCommandExecutor:
    def __init__(self, config: GatewayConfig, node_addresses: Iterable[str]) -> None:
        self.config = config
        self.node_addresses = tuple(sorted(node_addresses))
        self.entrypoint = config.project_root / "sanlight_canonical_sender_poc.py"
        if not self.entrypoint.is_file():
            raise GatewayExecutionError(f"CLI entrypoint not found: {self.entrypoint}")

    def _base_argv(self) -> list[str]:
        return [
            sys.executable,
            str(self.entrypoint),
            "--cdb",
            str(self.config.cdb_path),
            "--control-app-id",
            str(self.config.control_app_id),
            "--sender-app-id",
            str(self.config.sender_app_id),
            "--provisioner-state",
            str(self.config.state_dir / "control-provisioner.json"),
            "--sender-state",
            str(self.config.state_dir / "canonical-sender.json"),
        ]

    def _run(self, arguments: list[str], timeout: int | None = None) -> ProcessResult:
        argv = self._base_argv() + arguments
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                argv,
                cwd=self.config.project_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.config.command_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GatewayExecutionError(
                f"command exceeded {timeout or self.config.command_timeout_seconds} seconds"
            ) from exc
        return ProcessResult(completed.returncode, completed.stdout, completed.stderr)

    @staticmethod
    def _parse_get_max(result: ProcessResult) -> tuple[str, int] | None:
        matches = _GET_MAX_RE.findall(result.stdout)
        if not matches:
            return None
        address, value = matches[-1]
        parsed = int(value)
        if not 0 <= parsed <= 100:
            return None
        return address, parsed

    @staticmethod
    def _parse_get_live(result: ProcessResult) -> tuple[str, LiveStatus] | None:
        matches = _GET_LIVE_RE.findall(result.stdout)
        if not matches:
            return None
        address, lamp_time_ms, lamp_clock, brightness_raw, percent_estimate = matches[-1]
        try:
            status = LiveStatus(int(lamp_time_ms), int(brightness_raw))
        except ValueError:
            return None
        if status.lamp_clock != lamp_clock:
            return None
        if abs(status.brightness_percent_estimate - float(percent_estimate)) > 0.05:
            return None
        return address, status

    @staticmethod
    def _parse_reported_values(result: ProcessResult) -> dict[str, int]:
        reported: dict[str, int] = {}
        for pattern in (_STATUS_VALUE_RE, _NODE_VALUE_RE, _FINAL_VALUE_RE):
            for address, value in pattern.findall(result.stdout):
                parsed = int(value)
                if 0 <= parsed <= 100:
                    reported[address] = parsed
        return reported

    def refresh(self, target: str) -> ExecutionResult:
        targets = self.node_addresses if target == "all" else (target,)
        reported: dict[str, int] = {}
        live_reported: dict[str, LiveStatus] = {}
        errors: dict[str, dict[str, str]] = {}
        for address in targets:
            max_result = self._run(["get-max", address])
            parsed_max = self._parse_get_max(max_result)
            if (
                max_result.exit_code == 0
                and parsed_max is not None
                and parsed_max[0] == address
            ):
                reported[address] = parsed_max[1]
            else:
                errors.setdefault(address, {})["maxBrightness"] = max_result.summary

            live_result = self._run(["get-live", address])
            parsed_live = self._parse_get_live(live_result)
            if (
                live_result.exit_code == 0
                and parsed_live is not None
                and parsed_live[0] == address
            ):
                live_reported[address] = parsed_live[1]
            else:
                errors.setdefault(address, {})["liveBrightness"] = live_result.summary

        ok = not errors
        any_reported = bool(reported or live_reported)
        return ExecutionResult(
            ok=ok,
            status="verified" if ok else "partial" if any_reported else "failed",
            message=(
                "MaxBrightness and live lamp output refreshed and verified."
                if ok
                else "One or more read-only lamp status requests failed."
            ),
            reported=reported,
            live_reported=live_reported,
            details={"errors": errors} if errors else {},
        )

    def execute(self, command: GatewayCommand) -> ExecutionResult:
        if command.action == "refresh":
            return self.refresh(command.target)

        if command.action == "set-max":
            assert command.value is not None
            result = self._run(["set-max", command.target, str(command.value)])
            if result.exit_code == 0:
                live_result = self._run(["get-live", command.target])
                parsed_live = self._parse_get_live(live_result)
                live_reported: dict[str, LiveStatus] = {}
                details: dict[str, object] = {"exitCode": result.exit_code}
                if (
                    live_result.exit_code == 0
                    and parsed_live is not None
                    and parsed_live[0] == command.target
                ):
                    live_reported[command.target] = parsed_live[1]
                else:
                    details["liveError"] = live_result.summary
                return ExecutionResult(
                    ok=True,
                    status="verified",
                    message=(
                        f"Node {command.target} reports MaxBrightness "
                        f"{command.value}% as requested."
                    ),
                    reported={command.target: command.value},
                    live_reported=live_reported,
                    details=details,
                )
            return ExecutionResult(
                ok=False,
                status="unconfirmed" if result.exit_code in (3, 4) else "failed",
                message=result.summary,
                reported={},
                live_reported={},
                details={"exitCode": result.exit_code},
            )

        if command.action == "blackout":
            result = self._run(
                ["blackout", command.target, "--confirm-blackout"],
                timeout=max(self.config.command_timeout_seconds, 120),
            )
            if result.exit_code != 0:
                return ExecutionResult(
                    ok=False,
                    status="unconfirmed" if result.exit_code in (3, 4) else "failed",
                    message=result.summary,
                    reported={},
                    live_reported={},
                    details={"exitCode": result.exit_code},
                )
            expected = self.node_addresses if command.target == "all" else (command.target,)
            # CLI exit 0 is reached only after its own per-node GetMaxBrightness
            # verification. Avoid a redundant second MaxBrightness refresh.
            reported = {address: 0 for address in expected}
            return ExecutionResult(
                ok=True,
                status="verified",
                message="All selected nodes report 0% (off).",
                reported=reported,
                live_reported={},
                details={"exitCode": result.exit_code},
            )

        if command.action == "restore-blackout":
            result = self._run(
                ["restore-blackout", "latest", "--confirm-restore"],
                timeout=max(self.config.command_timeout_seconds, 180),
            )
            if result.exit_code != 0:
                return ExecutionResult(
                    ok=False,
                    status="unconfirmed" if result.exit_code in (3, 4) else "failed",
                    message=result.summary,
                    reported={},
                    live_reported={},
                    details={"exitCode": result.exit_code},
                )
            reported = self._parse_reported_values(result)
            return ExecutionResult(
                ok=True,
                status="verified",
                message=(
                    "Latest blackout snapshot restored and verified by the CLI "
                    "transaction engine."
                ),
                reported=reported,
                live_reported={},
                details={"exitCode": result.exit_code},
            )

        raise GatewayExecutionError(f"unsupported action: {command.action}")

    def sender_sequence_state(self) -> dict[str, int] | None:
        result = self._run(["show-sender-state"])
        if result.exit_code != 0:
            return None
        match = _SEQUENCE_RE.search(result.stdout)
        if not match:
            return None
        return {
            "sequenceNumber": int(match.group(1)),
            "sequenceRemaining": int(match.group(2)),
        }
