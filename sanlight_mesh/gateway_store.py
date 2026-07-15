"""Persistent non-secret cache for MQTT deduplication and verified node state."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .gateway_protocol import isoformat_utc, parse_timestamp, utc_now
from .state import read_state, write_state


STORE_VERSION = 1


@dataclass(frozen=True)
class CachedNodeState:
    max_brightness: int
    verified_at: datetime


class GatewayStore:
    def __init__(
        self,
        path: Path,
        *,
        dedup_ttl_seconds: int,
        dedup_max_entries: int,
    ) -> None:
        self.path = path
        self.dedup_ttl_seconds = dedup_ttl_seconds
        self.dedup_max_entries = dedup_max_entries
        self.document: dict[str, Any] = {
            "version": STORE_VERSION,
            "processed": {},
            "inflight": {},
            "nodes": {},
        }
        loaded = read_state(path)
        if loaded is not None:
            self._load_document(loaded)
        self.prune()

    def _load_document(self, value: Mapping[str, Any]) -> None:
        if value.get("version") != STORE_VERSION:
            return
        processed = value.get("processed", {})
        inflight = value.get("inflight", {})
        nodes = value.get("nodes", {})
        if isinstance(processed, dict) and isinstance(inflight, dict) and isinstance(nodes, dict):
            self.document = {
                "version": STORE_VERSION,
                "processed": dict(processed),
                "inflight": dict(inflight),
                "nodes": dict(nodes),
            }

    @property
    def processed(self) -> dict[str, Any]:
        return self.document["processed"]

    @property
    def inflight(self) -> dict[str, Any]:
        return self.document["inflight"]

    @property
    def nodes(self) -> dict[str, Any]:
        return self.document["nodes"]

    def save(self) -> None:
        write_state(self.path, self.document)

    def prune(self, now: datetime | None = None) -> None:
        current = now or utc_now()
        cutoff = current - timedelta(seconds=self.dedup_ttl_seconds)
        valid: list[tuple[str, dict[str, Any], datetime]] = []
        for command_id, record in list(self.processed.items()):
            if not isinstance(record, dict):
                continue
            try:
                timestamp = parse_timestamp(record.get("completedAt"), "completedAt")
            except Exception:
                continue
            if timestamp >= cutoff and isinstance(record.get("result"), dict):
                valid.append((command_id, record, timestamp))
        valid.sort(key=lambda item: item[2], reverse=True)
        self.document["processed"] = {
            command_id: record
            for command_id, record, _ in valid[: self.dedup_max_entries]
        }

    def get_result(self, command_id: str) -> dict[str, Any] | None:
        record = self.processed.get(command_id)
        if not isinstance(record, dict):
            return None
        result = record.get("result")
        return dict(result) if isinstance(result, dict) else None

    def remember_result(
        self,
        command_id: str,
        result: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> None:
        current = now or utc_now()
        self.processed[command_id] = {
            "completedAt": isoformat_utc(current),
            "result": dict(result),
        }
        self.inflight.pop(command_id, None)
        self.prune(current)
        self.save()


    def mark_inflight(
        self,
        command_id: str,
        command: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> None:
        current = now or utc_now()
        self.inflight[command_id] = {
            "startedAt": isoformat_utc(current),
            "command": dict(command),
        }
        self.save()

    def get_inflight(self, command_id: str) -> dict[str, Any] | None:
        value = self.inflight.get(command_id)
        return dict(value) if isinstance(value, dict) else None

    def update_node(
        self,
        address: str,
        max_brightness: int,
        *,
        now: datetime | None = None,
    ) -> None:
        if not 0 <= max_brightness <= 100:
            raise ValueError("cached MaxBrightness must be between 0 and 100")
        current = now or utc_now()
        self.nodes[address] = {
            "maxBrightness": max_brightness,
            "verifiedAt": isoformat_utc(current),
        }
        self.save()

    def get_node(self, address: str) -> CachedNodeState | None:
        record = self.nodes.get(address)
        if not isinstance(record, dict):
            return None
        value = record.get("maxBrightness")
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            return None
        try:
            verified_at = parse_timestamp(record.get("verifiedAt"), "verifiedAt")
        except Exception:
            return None
        return CachedNodeState(value, verified_at)

    def node_is_fresh(
        self,
        address: str,
        *,
        fresh_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        state = self.get_node(address)
        if state is None:
            return False
        current = now or utc_now()
        return current - state.verified_at <= timedelta(seconds=fresh_seconds)
