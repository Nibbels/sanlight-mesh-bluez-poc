"""Bounded serialized gateway command queue with set-max coalescing."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .gateway_protocol import GatewayCommand


@dataclass(frozen=True)
class SupersededCommand:
    command: GatewayCommand
    replacement_id: str


class GatewayCommandQueue:
    def __init__(self, max_size: int) -> None:
        self._queue: queue.Queue[GatewayCommand] = queue.Queue(maxsize=max_size)
        self._pending_ids: set[str] = set()
        self._lock = threading.Lock()

    def put(self, command: GatewayCommand) -> bool:
        with self._lock:
            if command.command_id in self._pending_ids:
                return False
            self._queue.put_nowait(command)
            self._pending_ids.add(command.command_id)
            return True

    def get(self, timeout: float | None = None) -> GatewayCommand:
        return self._queue.get(timeout=timeout)

    def done(self, command: GatewayCommand) -> None:
        with self._lock:
            self._pending_ids.discard(command.command_id)

    def contains(self, command_id: str) -> bool:
        with self._lock:
            return command_id in self._pending_ids

    def size(self) -> int:
        return self._queue.qsize()

    def coalesce_set_max(
        self,
        first: GatewayCommand,
        *,
        wait_seconds: float,
        sleep: Callable[[float], None],
    ) -> tuple[GatewayCommand, list[SupersededCommand]]:
        """Keep the newest queued set-max for the same target during a short window.

        Commands for other targets/actions are restored in their original order.
        The caller must publish a final ``superseded`` result for every returned item.
        """
        if first.action != "set-max" or wait_seconds <= 0:
            return first, []
        sleep(wait_seconds)
        drained: list[GatewayCommand] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except queue.Empty:
                break

        selected = first
        superseded: list[SupersededCommand] = []
        restore: list[GatewayCommand] = []
        for command in drained:
            if command.action == "set-max" and command.target == first.target:
                superseded.append(
                    SupersededCommand(command=selected, replacement_id=command.command_id)
                )
                selected = command
            else:
                restore.append(command)

        for command in restore:
            self._queue.put_nowait(command)
        with self._lock:
            for item in superseded:
                self._pending_ids.discard(item.command.command_id)
            self._pending_ids.add(selected.command_id)
        return selected, superseded
