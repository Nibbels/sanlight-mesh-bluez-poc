#!/usr/bin/env python3
"""Canonical SANlight App-ID source-address transport proof of concept.

This v12 diagnostic deliberately preserves the working v6 control provisioner
(App-ID 1 / 0x2400) and adds a separate local sender using the CDB identity of
SANlight Provisioner 2 (App-ID 2 / 0x2800).

The sender exposes both the Configuration Client model recorded for the CDB
provisioner identity and the SANlight vendor model 0x0A8B/0x0001 required by
BlueZ Node1.Send. The control provisioner configures AppKey 0, binds the vendor
model and sets default TTL 5. Read/write commands then originate from the
canonical primary source address 0x2800.

The existing v6 0x2401 gateway and its state are not changed or removed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from sanlight_protocol import (
    PRIMARY_APP_INDEX,
    SANLIGHT_COMPANY_ID,
    SANLIGHT_MODEL_ID,
    MeshMaterial,
    build_config_default_ttl_set_pdu,
    build_config_network_transmit_get_pdu,
    build_get_uptime_brightness_pdu,
    build_set_max_brightness_pdu,
    build_set_uptime_pdu,
    format_milliseconds_as_clock,
    format_seconds_as_clock,
    build_vendor_model_app_bind_pdu,
    config_default_ttl_status_value,
    decode_config_network_transmit_status,
    get_uptime_brightness_status_parameters,
    is_config_default_ttl_status,
    is_config_network_transmit_status,
    is_get_uptime_brightness_status,
    is_set_max_brightness_status,
    is_set_uptime_status,
    load_cdb_node_device_key,
    load_mesh_material,
    parse_clock_time,
    parse_destination,
    validate_destination,
    set_uptime_status_parameters,
    validate_max_brightness,
    validate_uptime_milliseconds,
    validate_uptime_seconds,
)

MESH_SERVICE = "org.bluez.mesh"
MESH_NETWORK_IFACE = "org.bluez.mesh.Network1"
MESH_NODE_IFACE = "org.bluez.mesh.Node1"
MESH_MGMT_IFACE = "org.bluez.mesh.Management1"
MESH_APPLICATION_IFACE = "org.bluez.mesh.Application1"
MESH_ELEMENT_IFACE = "org.bluez.mesh.Element1"
DBUS_OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"

CONTROL_APP_ROOT = "/com/nibbels/sanlight_mesh_poc_provisioner"
CONTROL_ELEMENT_PATH = CONTROL_APP_ROOT + "/ele00"
SENDER_APP_ROOT = "/com/nibbels/sanlight_mesh_poc_appid2_sender"
SENDER_ELEMENT_PATH = SENDER_APP_ROOT + "/ele00"

CONFIG_CLIENT_MODEL_ID = 0x0001
APP_COMPANY_ID = SANLIGHT_COMPANY_ID
APP_VERSION_ID = 0x0003
CONTROL_PRODUCT_ID = 0x0001
SENDER_PRODUCT_ID = 0x0003
TARGET_DEFAULT_TTL = 5


class PocError(RuntimeError):
    pass


def byte_array(data: bytes) -> dbus.Array:
    return dbus.Array([dbus.Byte(value) for value in data], signature="y")


def empty_options() -> dbus.Dictionary:
    return dbus.Dictionary({}, signature="sv")


def dbus_error_name(error: BaseException) -> str:
    getter = getattr(error, "get_dbus_name", None)
    return str(getter()) if callable(getter) else ""



def parse_destination_or_all(value: str) -> int | None:
    if value.strip().lower() == "all":
        return None
    return parse_destination(value)


def milliseconds_since_local_midnight(
    offset_seconds: int = 0, offset_milliseconds: int = 0
) -> tuple[int, datetime]:
    now = datetime.now().astimezone()
    milliseconds = (
        now.hour * 3600000
        + now.minute * 60000
        + now.second * 1000
        + now.microsecond // 1000
        + offset_seconds * 1000
        + offset_milliseconds
    )
    return milliseconds % 86400000, now


class ControlApplication(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus, runtime: "Runtime") -> None:
        self.runtime = runtime
        super().__init__(bus, CONTROL_APP_ROOT)

    def get_properties(self) -> dict[str, dict[str, Any]]:
        return {
            MESH_APPLICATION_IFACE: {
                "CompanyID": dbus.UInt16(APP_COMPANY_ID),
                "ProductID": dbus.UInt16(CONTROL_PRODUCT_ID),
                "VersionID": dbus.UInt16(APP_VERSION_ID),
            }
        }

    @dbus.service.method(DBUS_OBJECT_MANAGER_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self) -> dict[str, dict[str, dict[str, Any]]]:
        return {
            CONTROL_APP_ROOT: self.get_properties(),
            CONTROL_ELEMENT_PATH: self.runtime.control_element.get_properties(),
        }

    @dbus.service.method(MESH_APPLICATION_IFACE, in_signature="t", out_signature="")
    def JoinComplete(self, token: dbus.UInt64) -> None:
        self.runtime.on_control_join_complete(int(token))

    @dbus.service.method(MESH_APPLICATION_IFACE, in_signature="s", out_signature="")
    def JoinFailed(self, reason: dbus.String) -> None:
        self.runtime.fail(f"BlueZ control provisioner Import failed: {reason}")


class SenderApplication(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus, runtime: "Runtime") -> None:
        self.runtime = runtime
        super().__init__(bus, SENDER_APP_ROOT)

    def get_properties(self) -> dict[str, dict[str, Any]]:
        return {
            MESH_APPLICATION_IFACE: {
                "CompanyID": dbus.UInt16(APP_COMPANY_ID),
                "ProductID": dbus.UInt16(SENDER_PRODUCT_ID),
                "VersionID": dbus.UInt16(APP_VERSION_ID),
            }
        }

    @dbus.service.method(DBUS_OBJECT_MANAGER_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self) -> dict[str, dict[str, dict[str, Any]]]:
        return {
            SENDER_APP_ROOT: self.get_properties(),
            SENDER_ELEMENT_PATH: self.runtime.sender_element.get_properties(),
        }

    @dbus.service.method(MESH_APPLICATION_IFACE, in_signature="t", out_signature="")
    def JoinComplete(self, token: dbus.UInt64) -> None:
        self.runtime.on_sender_join_complete(int(token))

    @dbus.service.method(MESH_APPLICATION_IFACE, in_signature="s", out_signature="")
    def JoinFailed(self, reason: dbus.String) -> None:
        self.runtime.fail(f"BlueZ canonical sender Import failed: {reason}")


class ControlElement(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus, runtime: "Runtime") -> None:
        self.runtime = runtime
        super().__init__(bus, CONTROL_ELEMENT_PATH)

    def get_properties(self) -> dict[str, dict[str, Any]]:
        sig_models = dbus.Array(
            [(dbus.UInt16(CONFIG_CLIENT_MODEL_ID), dbus.Dictionary({}, signature="sv"))],
            signature="(qa{sv})",
        )
        vendor_models = dbus.Array([], signature="(qqa{sv})")
        return {
            MESH_ELEMENT_IFACE: {
                "Index": dbus.Byte(0),
                "Models": sig_models,
                "VendorModels": vendor_models,
            }
        }

    @dbus.service.method(MESH_ELEMENT_IFACE, in_signature="qqvay", out_signature="")
    def MessageReceived(
        self,
        source: dbus.UInt16,
        key_index: dbus.UInt16,
        destination: dbus.Signature,
        data: dbus.Array,
    ) -> None:
        payload = bytes(int(value) for value in data)
        print(
            f"Control RX access: src=0x{int(source):04X} "
            f"appKey={int(key_index)} pdu={payload.hex()}"
        )

    @dbus.service.method(MESH_ELEMENT_IFACE, in_signature="qbqay", out_signature="")
    def DevKeyMessageReceived(
        self,
        source: dbus.UInt16,
        remote: dbus.Boolean,
        net_index: dbus.UInt16,
        data: dbus.Array,
    ) -> None:
        payload = bytes(int(value) for value in data)
        print(
            f"Control RX DevKey: src=0x{int(source):04X} remote={bool(remote)} "
            f"netKey={int(net_index)} pdu={payload.hex()}"
        )

        if is_config_network_transmit_status(payload):
            if self.runtime.args.command != "get-net-tx":
                print(
                    "Ignoring Config Network Transmit Status outside get-net-tx."
                )
                return
            if int(source) != self.runtime.args.destination:
                print(
                    f"Ignoring Config Network Transmit Status from unexpected source "
                    f"0x{int(source):04X}; expected "
                    f"0x{self.runtime.args.destination:04X}."
                )
                return
            transmissions, interval_ms = decode_config_network_transmit_status(
                payload
            )
            print(
                "Config Network Transmit Status: "
                f"transmissions={transmissions}, interval={interval_ms} ms, "
                f"encoded=0x{payload[2]:02X}"
            )
            self.runtime.on_network_transmit_status(
                int(source), transmissions, interval_ms, payload[2]
            )
            return

        if len(payload) >= 6 and payload[:2] == bytes.fromhex("8003"):
            if int(source) != self.runtime.sender_unicast:
                print(
                    f"Ignoring Config AppKey Status from unexpected source "
                    f"0x{int(source):04X}."
                )
                return
            status = payload[2]
            print(f"Config AppKey Status: 0x{status:02X}")
            if status == 0:
                self.runtime.on_sender_app_key_added()
            else:
                self.runtime.fail(
                    f"Config AppKey Add returned Mesh status 0x{status:02X}"
                )
            return

        if len(payload) >= 3 and payload[:2] == bytes.fromhex("803e"):
            if int(source) != self.runtime.sender_unicast:
                print(
                    f"Ignoring Config Model App Status from unexpected source "
                    f"0x{int(source):04X}."
                )
                return
            status = payload[2]
            print(f"Config Model App Status: 0x{status:02X}")
            if status == 0:
                self.runtime.on_sender_binding_confirmed("Config Model App Status")
            else:
                self.runtime.fail(
                    f"Config Model App Bind returned Mesh status 0x{status:02X}"
                )
            return

        if is_config_default_ttl_status(payload):
            if int(source) != self.runtime.sender_unicast:
                print(
                    f"Ignoring Config Default TTL Status from unexpected source "
                    f"0x{int(source):04X}."
                )
                return
            ttl = config_default_ttl_status_value(payload)
            print(f"Config Default TTL Status: {ttl} (0x{ttl:02X})")
            self.runtime.on_sender_ttl_status(ttl)

    @dbus.service.method(MESH_ELEMENT_IFACE, in_signature="qa{sv}", out_signature="")
    def UpdateModelConfiguration(
        self, model_id: dbus.UInt16, config: dbus.Dictionary
    ) -> None:
        print(
            f"Control model config update: model=0x{int(model_id):04X} "
            f"config={dict(config)}"
        )


class SenderElement(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus, runtime: "Runtime") -> None:
        self.runtime = runtime
        super().__init__(bus, SENDER_ELEMENT_PATH)

    def get_properties(self) -> dict[str, dict[str, Any]]:
        # Preserve the CDB provisioner identity's Config Client model and add the
        # local SANlight vendor model required by BlueZ Node1.Send.
        sig_models = dbus.Array(
            [(dbus.UInt16(CONFIG_CLIENT_MODEL_ID), dbus.Dictionary({}, signature="sv"))],
            signature="(qa{sv})",
        )
        vendor_models = dbus.Array(
            [
                (
                    dbus.UInt16(SANLIGHT_COMPANY_ID),
                    dbus.UInt16(SANLIGHT_MODEL_ID),
                    dbus.Dictionary({}, signature="sv"),
                )
            ],
            signature="(qqa{sv})",
        )
        return {
            MESH_ELEMENT_IFACE: {
                "Index": dbus.Byte(0),
                "Models": sig_models,
                "VendorModels": vendor_models,
            }
        }

    @dbus.service.method(MESH_ELEMENT_IFACE, in_signature="qqvay", out_signature="")
    def MessageReceived(
        self,
        source: dbus.UInt16,
        key_index: dbus.UInt16,
        destination: dbus.Signature,
        data: dbus.Array,
    ) -> None:
        payload = bytes(int(value) for value in data)
        try:
            dest_text = f"0x{int(destination):04X}"
        except (TypeError, ValueError):
            dest_text = str(destination)
        print(
            f"Sender RX access: src=0x{int(source):04X} dst={dest_text} "
            f"appKey={int(key_index)} pdu={payload.hex()}"
        )

        if is_set_max_brightness_status(payload):
            print("Received SANlight SetMaxBrightness status (vendor opcode 0x07).")
            self.runtime.remote_status_seen = True
            return

        if is_set_uptime_status(payload):
            params = set_uptime_status_parameters(payload)
            detail = f"src=0x{int(source):04X} parameters={params.hex() or '<empty>'}"
            if len(params) >= 4:
                status_ms = int.from_bytes(params[:4], "little")
                detail += (
                    f"; uint32_le[0:4]={status_ms} ms "
                    f"(~{format_milliseconds_as_clock(status_ms)})"
                )
            print(
                "Received SANlight SetUptime status (vendor opcode 0x0B): "
                + detail
            )
            self.runtime.uptime_status_seen.add(int(source))
            self.runtime.remote_status_seen = True
            return

        if is_get_uptime_brightness_status(payload):
            if (
                self.runtime.args.command == "get-live"
                and int(source) != self.runtime.args.destination
            ):
                print(
                    f"Ignoring SANlight 0x0D status from unexpected source "
                    f"0x{int(source):04X}; expected "
                    f"0x{self.runtime.args.destination:04X}."
                )
                return
            params = get_uptime_brightness_status_parameters(payload)
            print(
                "Received SANlight GetUptimeAndBrightness status "
                "(vendor opcode 0x0D): "
                f"src=0x{int(source):04X} parameters={params.hex() or '<empty>'}"
            )
            self.runtime.live_status = (int(source), params)
            self.runtime.finish_get_live()

    @dbus.service.method(MESH_ELEMENT_IFACE, in_signature="qbqay", out_signature="")
    def DevKeyMessageReceived(
        self,
        source: dbus.UInt16,
        remote: dbus.Boolean,
        net_index: dbus.UInt16,
        data: dbus.Array,
    ) -> None:
        payload = bytes(int(value) for value in data)
        print(
            f"Sender RX DevKey: src=0x{int(source):04X} remote={bool(remote)} "
            f"netKey={int(net_index)} pdu={payload.hex()}"
        )

    @dbus.service.method(MESH_ELEMENT_IFACE, in_signature="qa{sv}", out_signature="")
    def UpdateModelConfiguration(
        self, model_id: dbus.UInt16, config: dbus.Dictionary
    ) -> None:
        config_dict = dict(config)
        vendor = int(config_dict.get("Vendor", 0xFFFF))
        bindings = [int(value) for value in config_dict.get("Bindings", [])]
        print(
            f"Sender model config update: vendor=0x{vendor:04X} "
            f"model=0x{int(model_id):04X} bindings={bindings}"
        )
        if (
            int(model_id) == SANLIGHT_MODEL_ID
            and vendor == SANLIGHT_COMPANY_ID
            and PRIMARY_APP_INDEX in bindings
        ):
            self.runtime.on_sender_binding_confirmed(
                "Sender UpdateModelConfiguration"
            )


class Runtime:
    def __init__(
        self,
        args: argparse.Namespace,
        control: MeshMaterial,
        sender: MeshMaterial,
    ) -> None:
        self.args = args
        self.control = control
        self.sender = sender
        self.sender_unicast = sender.provisioner.unicast

        self.mainloop = GLib.MainLoop()
        self.exit_code = 1
        self.finished = False

        self.control_node: dbus.Interface | None = None
        self.control_management: dbus.Interface | None = None
        self.sender_node: dbus.Interface | None = None
        self.sender_bound = False
        self.app_key_added = False
        self.network_transmit_status: tuple[int, int, int, int] | None = None
        self.app_key_add_requested = False
        self.binding_requested = False
        self.ttl_requested = False
        self.ttl_confirmed = False
        self.remote_status_seen = False
        self.live_status: tuple[int, bytes] | None = None
        self.uptime_targets: set[int] = set()
        self.uptime_status_seen: set[int] = set()
        self.live_attempt = 0
        self.live_max_attempts = 2

        self.bus = dbus.SystemBus()
        self.control_element = ControlElement(self.bus, self)
        self.control_application = ControlApplication(self.bus, self)
        self.sender_element = SenderElement(self.bus, self)
        self.sender_application = SenderApplication(self.bus, self)

        mesh_object = self.bus.get_object(MESH_SERVICE, "/org/bluez/mesh")
        self.network = dbus.Interface(mesh_object, MESH_NETWORK_IFACE)

    def log_identity(self) -> None:
        summary = {
            "meshUUID": str(self.control.mesh_uuid),
            "control": {
                "appId": self.args.control_app_id,
                "name": self.control.provisioner.name,
                "uuid": str(self.control.provisioner.uuid),
                "unicast": f"0x{self.control.provisioner.unicast:04X}",
            },
            "sender": {
                "appId": self.args.sender_app_id,
                "name": self.sender.provisioner.name,
                "uuid": str(self.sender.provisioner.uuid),
                "unicast": f"0x{self.sender_unicast:04X}",
                "defaultTTLTarget": TARGET_DEFAULT_TTL,
                "models": ["SIG Config Client 0x0001", "Vendor 0x0A8B/0x0001"],
            },
            "netIndex": self.control.net_index,
            "appIndex": self.control.app_index,
            "ivIndexInCdb": self.control.cdb_iv_index,
            "groups": {
                f"0x{address:04X}": name
                for address, name in sorted(self.control.groups.items())
            },
            "sanlightNodes": {
                f"0x{address:04X}": name
                for address, name in sorted(self.control.sanlight_nodes.items())
            },
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print("Secret NetKey/AppKey/DeviceKey values are intentionally not printed.")
        print("Existing v6 gateway 0x2401/state is intentionally untouched by this script.")

    def timeout(self, seconds: int, callback: Callable[[], None]) -> None:
        GLib.timeout_add_seconds(seconds, self._run_timeout, callback)

    @staticmethod
    def _run_timeout(callback: Callable[[], None]) -> bool:
        callback()
        return False

    def finish(self, message: str, code: int = 0) -> None:
        if self.finished:
            return
        self.finished = True
        self.exit_code = code
        print(message)
        self.mainloop.quit()

    def fail(self, message: str) -> None:
        self.finish(f"ERROR: {message}", 1)

    def run(self) -> int:
        self.log_identity()
        if self.args.command == "setup":
            self.start_setup()
        elif self.args.command in ("get-live", "set-max", "set-uptime", "set-time", "sync-now"):
            self.start_sender_command()
        elif self.args.command == "get-net-tx":
            self.start_control_command()
        elif self.args.command == "leave-sender":
            self.start_leave_sender()
        else:
            raise PocError(f"Unsupported runtime command: {self.args.command}")

        if not self.finished:
            self.mainloop.run()
        return self.exit_code

    def _write_state(self, path: Path, state: dict[str, Any]) -> None:
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)

    def _read_state(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PocError(f"Cannot read state file {path}: {exc}") from exc

    @staticmethod
    def _token_from_state(state: dict[str, Any], label: str) -> int | None:
        raw = state.get("token")
        if raw in (None, ""):
            return None
        try:
            return int(str(raw), 16)
        except ValueError as exc:
            raise PocError(f"{label} state contains no valid token") from exc

    @staticmethod
    def _validate_state_identity(
        state: dict[str, Any], expected: dict[str, Any], label: str
    ) -> None:
        for key, value in expected.items():
            if state.get(key) != value:
                raise PocError(
                    f"{label} state identity mismatch for {key}: "
                    f"expected {value!r}, got {state.get(key)!r}"
                )

    def load_control_state(self) -> dict[str, Any] | None:
        state = self._read_state(self.args.provisioner_state)
        if state is None:
            return None
        expected = {
            "role": "provisioner",
            "meshUUID": str(self.control.mesh_uuid),
            "provisionerUUID": str(self.control.provisioner.uuid),
            "unicast": self.control.provisioner.unicast,
            "appId": self.args.control_app_id,
        }
        self._validate_state_identity(state, expected, "Control provisioner")
        return state

    def save_control_state(self, token: int) -> None:
        self._write_state(
            self.args.provisioner_state,
            {
                "role": "provisioner",
                "meshUUID": str(self.control.mesh_uuid),
                "provisionerUUID": str(self.control.provisioner.uuid),
                "unicast": self.control.provisioner.unicast,
                "appId": self.args.control_app_id,
                "token": f"{token:016x}",
                "ivIndex": self.args.iv_index,
            },
        )
        print(
            f"Saved control provisioner BlueZ token to {self.args.provisioner_state} "
            "(mode 0600)."
        )

    def load_sender_state(self) -> dict[str, Any] | None:
        state = self._read_state(self.args.sender_state)
        if state is None:
            return None
        expected = {
            "role": "canonical-sender",
            "meshUUID": str(self.control.mesh_uuid),
            "senderProvisionerUUID": str(self.sender.provisioner.uuid),
            "senderAppId": self.args.sender_app_id,
            "unicast": self.sender_unicast,
        }
        self._validate_state_identity(state, expected, "Canonical sender")
        return state

    def save_sender_state(self, token: int) -> None:
        self._write_state(
            self.args.sender_state,
            {
                "role": "canonical-sender",
                "meshUUID": str(self.control.mesh_uuid),
                "senderProvisionerUUID": str(self.sender.provisioner.uuid),
                "senderAppId": self.args.sender_app_id,
                "unicast": self.sender_unicast,
                "token": f"{token:016x}",
                "ivIndex": self.args.iv_index,
            },
        )
        print(
            f"Saved canonical sender BlueZ token to {self.args.sender_state} "
            "(mode 0600)."
        )

    def start_setup(self) -> None:
        if self.args.iv_index is None:
            raise PocError(
                "The CDB has no ivIndex. Pass the captured current IV Index with "
                "--iv-index (current captured value: 0)."
            )
        self.ensure_control()

    def ensure_control(self) -> None:
        state = self.load_control_state()
        token = None if state is None else self._token_from_state(
            state, "Control provisioner"
        )
        if token is not None:
            print("Control provisioner state exists; attaching App-ID identity.")
            self.attach_control(token)
            return

        print(
            f"Importing control CDB provisioner {self.control.provisioner.name} at "
            f"0x{self.control.provisioner.unicast:04X} as Configuration Client..."
        )
        self.network.Import(
            dbus.ObjectPath(CONTROL_APP_ROOT),
            byte_array(self.control.provisioner.uuid.bytes),
            byte_array(self.control.provisioner.device_key),
            byte_array(self.control.net_key),
            dbus.UInt16(self.control.net_index),
            self.import_flags(),
            dbus.UInt32(self.args.iv_index),
            dbus.UInt16(self.control.provisioner.unicast),
            reply_handler=lambda: print(
                "Control provisioner Import request accepted by bluetooth-meshd."
            ),
            error_handler=lambda error: self.fail(
                f"Control Network1.Import failed: {error}"
            ),
        )
        self.timeout(
            20,
            lambda: self.fail("Timed out waiting for control provisioner JoinComplete")
            if not self.finished and self.control_node is None
            else None,
        )

    def on_control_join_complete(self, token: int) -> None:
        if self.finished:
            return
        print(f"Control provisioner BlueZ JoinComplete token: {token:016x}")
        self.save_control_state(token)
        self.attach_control(token)

    def attach_control(self, token: int) -> None:
        print(f"Attaching control provisioner using token {token:016x}...")
        self.network.Attach(
            dbus.ObjectPath(CONTROL_APP_ROOT),
            dbus.UInt64(token),
            reply_handler=self.on_control_attach,
            error_handler=lambda error: self.fail(
                f"Control Network1.Attach failed: {error}"
            ),
        )

    def on_control_attach(
        self, node_path: dbus.ObjectPath, configuration: dbus.Array
    ) -> None:
        if self.finished:
            return
        print(f"Control provisioner attached: {node_path}")
        node_object = self.bus.get_object(MESH_SERVICE, str(node_path))
        self.control_node = dbus.Interface(node_object, MESH_NODE_IFACE)
        self.control_management = dbus.Interface(node_object, MESH_MGMT_IFACE)
        self.import_control_subnet()

    def import_control_subnet(self) -> None:
        if self.control_management is None:
            self.fail("Control Management1 interface is unavailable")
            return
        print(
            f"Importing NetKey index {self.control.net_index} into the control "
            "Management1 key database..."
        )
        self.control_management.ImportSubnet(
            dbus.UInt16(self.control.net_index),
            byte_array(self.control.net_key),
            reply_handler=self.on_control_subnet_ready,
            error_handler=self.on_control_subnet_error,
        )

    def on_control_subnet_error(self, error: BaseException) -> None:
        if dbus_error_name(error).endswith("AlreadyExists"):
            print(
                f"Control NetKey index {self.control.net_index} already exists locally."
            )
            self.on_control_subnet_ready()
            return
        self.fail(f"Control Management1.ImportSubnet failed: {error}")

    def on_control_subnet_ready(self) -> None:
        if self.finished:
            return
        print(f"Control NetKey index {self.control.net_index} is available locally.")
        assert self.control_management is not None
        print(
            f"Importing AppKey index {self.control.app_index} into the control "
            "Management1 key database..."
        )
        self.control_management.ImportAppKey(
            dbus.UInt16(self.control.net_index),
            dbus.UInt16(self.control.app_index),
            byte_array(self.control.app_key),
            reply_handler=self.on_control_app_key_ready,
            error_handler=self.on_control_app_key_error,
        )

    def on_control_app_key_error(self, error: BaseException) -> None:
        if dbus_error_name(error).endswith("AlreadyExists"):
            print(
                f"Control AppKey index {self.control.app_index} already exists locally."
            )
            self.on_control_app_key_ready()
            return
        self.fail(f"Control Management1.ImportAppKey failed: {error}")

    def on_control_app_key_ready(self) -> None:
        if self.finished:
            return
        print(f"Control AppKey index {self.control.app_index} is available locally.")
        if self.args.command == "get-net-tx":
            self.prepare_network_transmit_probe()
            return
        self.ensure_sender()

    def start_control_command(self) -> None:
        state = self.load_control_state()
        if state is None:
            raise PocError("No control provisioner state found. Run setup first.")
        token = self._token_from_state(state, "Control provisioner")
        if token is None:
            raise PocError(
                "Control provisioner state has no BlueZ token. Run setup first."
            )
        self.attach_control(token)

    def prepare_network_transmit_probe(self) -> None:
        if self.control_management is None:
            self.fail("Control Management1 interface is unavailable")
            return
        target = self.args.destination
        device_key = load_cdb_node_device_key(self.args.cdb, target)
        description = validate_destination(self.control, target)
        print(
            f"Importing CDB Device Key for 0x{target:04X} ({description}) "
            "as a remote node into the control provisioner key database..."
        )
        self.control_management.ImportRemoteNode(
            dbus.UInt16(target),
            dbus.Byte(1),
            byte_array(device_key),
            reply_handler=self.send_network_transmit_get,
            error_handler=self.on_network_probe_remote_key_error,
        )

    def on_network_probe_remote_key_error(self, error: BaseException) -> None:
        if dbus_error_name(error).endswith("AlreadyExists"):
            print(
                f"Remote Device Key for 0x{self.args.destination:04X} already "
                "exists in the control provisioner key database."
            )
            self.send_network_transmit_get()
            return
        self.fail(f"Control Management1.ImportRemoteNode failed: {error}")

    def send_network_transmit_get(self) -> None:
        if self.control_node is None:
            self.fail("Control Node1 interface is unavailable")
            return
        payload = build_config_network_transmit_get_pdu()
        description = validate_destination(self.control, self.args.destination)
        print(
            f"Sending read-only Config Network Transmit Get from control "
            f"0x{self.control.provisioner.unicast:04X} to "
            f"0x{self.args.destination:04X} ({description}); "
            f"DevKey PDU={payload.hex()}..."
        )
        self.control_node.DevKeySend(
            dbus.ObjectPath(CONTROL_ELEMENT_PATH),
            dbus.UInt16(self.args.destination),
            dbus.Boolean(True),
            dbus.UInt16(self.control.net_index),
            empty_options(),
            byte_array(payload),
            reply_handler=lambda: print(
                "Config Network Transmit Get accepted by bluetooth-meshd "
                "for transmission."
            ),
            error_handler=lambda error: self.fail(
                f"Control Node1.DevKeySend Network Transmit Get failed: {error}"
            ),
        )
        self.timeout(10, self.finish_network_transmit_probe)

    def on_network_transmit_status(
        self,
        source: int,
        transmissions: int,
        interval_ms: int,
        encoded: int,
    ) -> None:
        if self.finished:
            return
        self.network_transmit_status = (
            source,
            transmissions,
            interval_ms,
            encoded,
        )
        self.finish_network_transmit_probe()

    def finish_network_transmit_probe(self) -> None:
        if self.finished:
            return
        if self.network_transmit_status is None:
            self.finish(
                "GET-NET-TX COMPLETE. No Config Network Transmit Status was "
                "observed during the 10-second window."
            )
            return
        source, transmissions, interval_ms, encoded = self.network_transmit_status
        self.finish(
            f"GET-NET-TX COMPLETE. Node 0x{source:04X}: "
            f"Network Transmit transmissions={transmissions}, "
            f"interval={interval_ms} ms, encoded=0x{encoded:02X}."
        )

    def ensure_sender(self) -> None:
        state = self.load_sender_state()
        token = None if state is None else self._token_from_state(
            state, "Canonical sender"
        )
        if token is not None:
            print(
                f"Canonical sender state exists; attaching CDB App-ID "
                f"{self.args.sender_app_id} at 0x{self.sender_unicast:04X}."
            )
            self.attach_sender(token)
            return

        print(
            f"Importing CDB sender identity {self.sender.provisioner.name} at "
            f"0x{self.sender_unicast:04X} with Config Client + SANlight vendor model..."
        )
        self.network.Import(
            dbus.ObjectPath(SENDER_APP_ROOT),
            byte_array(self.sender.provisioner.uuid.bytes),
            byte_array(self.sender.provisioner.device_key),
            byte_array(self.control.net_key),
            dbus.UInt16(self.control.net_index),
            self.import_flags(),
            dbus.UInt32(self.args.iv_index),
            dbus.UInt16(self.sender_unicast),
            reply_handler=lambda: print(
                "Canonical sender Import request accepted by bluetooth-meshd."
            ),
            error_handler=lambda error: self.fail(
                f"Canonical sender Network1.Import failed: {error}"
            ),
        )
        self.timeout(
            20,
            lambda: self.fail("Timed out waiting for canonical sender JoinComplete")
            if not self.finished and self.sender_node is None
            else None,
        )

    def on_sender_join_complete(self, token: int) -> None:
        if self.finished:
            return
        print(f"Canonical sender BlueZ JoinComplete token: {token:016x}")
        self.save_sender_state(token)
        self.attach_sender(token)

    def attach_sender(self, token: int) -> None:
        print(f"Attaching canonical sender using token {token:016x}...")
        self.network.Attach(
            dbus.ObjectPath(SENDER_APP_ROOT),
            dbus.UInt64(token),
            reply_handler=self.on_sender_attach,
            error_handler=lambda error: self.fail(
                f"Canonical sender Network1.Attach failed: {error}"
            ),
        )

    def on_sender_attach(
        self, node_path: dbus.ObjectPath, configuration: dbus.Array
    ) -> None:
        if self.finished:
            return
        print(f"Canonical sender attached: {node_path}")
        node_object = self.bus.get_object(MESH_SERVICE, str(node_path))
        self.sender_node = dbus.Interface(node_object, MESH_NODE_IFACE)
        self.sender_bound = self.configuration_has_binding(configuration)
        print(
            "Canonical sender SANlight vendor model AppKey-0 binding present: "
            f"{self.sender_bound}"
        )

        if self.args.command == "setup":
            self.import_sender_device_key_into_control()
            return

        if not self.sender_bound:
            self.fail(
                "Canonical sender vendor model is not bound. Run this script's setup first."
            )
            return
        self.on_sender_ready()

    @staticmethod
    def configuration_has_binding(configuration: dbus.Array) -> bool:
        for element_config in configuration:
            if int(element_config[0]) != 0:
                continue
            for model_id, config in element_config[1]:
                config_dict = dict(config)
                vendor = int(config_dict.get("Vendor", 0xFFFF))
                bindings = [int(value) for value in config_dict.get("Bindings", [])]
                if (
                    int(model_id) == SANLIGHT_MODEL_ID
                    and vendor == SANLIGHT_COMPANY_ID
                    and PRIMARY_APP_INDEX in bindings
                ):
                    return True
        return False

    def import_sender_device_key_into_control(self) -> None:
        if self.control_management is None:
            self.fail("Control Management1 interface is unavailable")
            return
        print(
            f"Importing CDB sender 0x{self.sender_unicast:04X} Device Key as a remote "
            "node into the control provisioner key database..."
        )
        self.control_management.ImportRemoteNode(
            dbus.UInt16(self.sender_unicast),
            dbus.Byte(1),
            byte_array(self.sender.provisioner.device_key),
            reply_handler=self.on_sender_remote_key_ready,
            error_handler=self.on_sender_remote_key_error,
        )

    def on_sender_remote_key_error(self, error: BaseException) -> None:
        if dbus_error_name(error).endswith("AlreadyExists"):
            print(
                "Canonical sender Device Key already exists in the control remote "
                "key database."
            )
            self.on_sender_remote_key_ready()
            return
        self.fail(f"Control Management1.ImportRemoteNode failed: {error}")

    def on_sender_remote_key_ready(self) -> None:
        if self.finished:
            return
        if self.sender_bound:
            print("Vendor model is already bound; proceeding to Default TTL Set 5.")
            self.send_sender_ttl_set()
            return
        self.send_sender_app_key_add()

    def send_sender_app_key_add(self) -> None:
        if self.control_node is None or self.app_key_add_requested:
            return
        self.app_key_add_requested = True
        print(
            f"Sending Config AppKey Add for AppKey {self.control.app_index} to canonical "
            f"sender 0x{self.sender_unicast:04X}..."
        )
        self.control_node.AddAppKey(
            dbus.ObjectPath(CONTROL_ELEMENT_PATH),
            dbus.UInt16(self.sender_unicast),
            dbus.UInt16(self.control.app_index),
            dbus.UInt16(self.control.net_index),
            dbus.Boolean(False),
            reply_handler=lambda: print(
                "Canonical sender Config AppKey Add accepted for transmission."
            ),
            error_handler=lambda error: self.fail(
                f"Control Node1.AddAppKey failed: {error}"
            ),
        )
        self.timeout(
            12,
            lambda: self.fail(
                "No successful Config AppKey Status was observed for canonical sender."
            )
            if not self.finished and not self.app_key_added
            else None,
        )

    def on_sender_app_key_added(self) -> None:
        if self.finished or self.app_key_added:
            return
        self.app_key_added = True
        print(
            f"Canonical sender accepted AppKey index {self.control.app_index}; "
            "continuing with vendor-model binding."
        )
        self.send_sender_model_bind()

    def send_sender_model_bind(self) -> None:
        if self.control_node is None or self.binding_requested:
            return
        self.binding_requested = True
        payload = build_vendor_model_app_bind_pdu(
            self.sender_unicast,
            self.control.app_index,
            SANLIGHT_COMPANY_ID,
            SANLIGHT_MODEL_ID,
        )
        print(
            f"Binding AppKey {self.control.app_index} to canonical sender vendor model "
            f"0x0A8B/0x0001 at 0x{self.sender_unicast:04X}; "
            f"PDU={payload.hex()}..."
        )
        self.control_node.DevKeySend(
            dbus.ObjectPath(CONTROL_ELEMENT_PATH),
            dbus.UInt16(self.sender_unicast),
            dbus.Boolean(True),
            dbus.UInt16(self.control.net_index),
            empty_options(),
            byte_array(payload),
            reply_handler=lambda: print(
                "Canonical sender Config Model App Bind accepted for transmission."
            ),
            error_handler=lambda error: self.fail(
                f"Control Node1.DevKeySend bind failed: {error}"
            ),
        )
        self.timeout(
            12,
            lambda: self.fail(
                "No successful canonical sender model-binding confirmation was observed."
            )
            if not self.finished and not self.sender_bound
            else None,
        )

    def on_sender_binding_confirmed(self, source: str) -> None:
        if self.finished or self.sender_bound:
            return
        self.sender_bound = True
        print(f"Canonical sender AppKey/model binding confirmed via {source}.")
        self.send_sender_ttl_set()

    def send_sender_ttl_set(self) -> None:
        if self.control_node is None or self.ttl_requested:
            return
        self.ttl_requested = True
        payload = build_config_default_ttl_set_pdu(TARGET_DEFAULT_TTL)
        print(
            f"Setting canonical sender Default TTL to {TARGET_DEFAULT_TTL}; "
            f"Config Default TTL Set PDU={payload.hex()}..."
        )
        self.control_node.DevKeySend(
            dbus.ObjectPath(CONTROL_ELEMENT_PATH),
            dbus.UInt16(self.sender_unicast),
            dbus.Boolean(True),
            dbus.UInt16(self.control.net_index),
            empty_options(),
            byte_array(payload),
            reply_handler=lambda: print(
                "Canonical sender Config Default TTL Set accepted for transmission."
            ),
            error_handler=lambda error: self.fail(
                f"Control Node1.DevKeySend Default TTL Set failed: {error}"
            ),
        )
        self.timeout(
            12,
            lambda: self.fail(
                "No Config Default TTL Status=5 was observed from canonical sender."
            )
            if not self.finished and not self.ttl_confirmed
            else None,
        )

    def on_sender_ttl_status(self, ttl: int) -> None:
        if self.finished:
            return
        if ttl != TARGET_DEFAULT_TTL:
            self.fail(
                f"Canonical sender returned Default TTL {ttl}; expected "
                f"{TARGET_DEFAULT_TTL}"
            )
            return
        self.ttl_confirmed = True
        self.finish(
            "SETUP OK: control App-ID 1 / 0x2400 is attached as Config Client; "
            f"canonical sender App-ID {self.args.sender_app_id} / "
            f"0x{self.sender_unicast:04X} is attached, AppKey 0 is bound to "
            "SANlight vendor model 0x0A8B/0x0001, and Default TTL is 5."
        )

    def start_sender_command(self) -> None:
        state = self.load_sender_state()
        if state is None:
            raise PocError("No canonical sender state found. Run setup first.")
        token = self._token_from_state(state, "Canonical sender")
        if token is None:
            raise PocError("Canonical sender state has no BlueZ token. Run setup first.")
        self.attach_sender(token)

    def on_sender_ready(self) -> None:
        if self.args.command == "get-live":
            self.send_get_live()
            return
        if self.args.command == "set-max":
            self.send_max_brightness()
            return
        if self.args.command in ("set-uptime", "set-time", "sync-now"):
            self.send_set_uptime()
            return
        self.fail(f"Unexpected command after sender attach: {self.args.command}")

    def send_get_live(self) -> None:
        if self.sender_node is None:
            self.fail("Canonical sender Node1 interface is unavailable")
            return
        self.live_attempt += 1
        payload = build_get_uptime_brightness_pdu()
        description = validate_destination(self.control, self.args.destination)
        print(
            f"Sending SANlight GetUptimeAndBrightness attempt "
            f"{self.live_attempt}/{self.live_max_attempts} from canonical source "
            f"0x{self.sender_unicast:04X} to 0x{self.args.destination:04X} "
            f"({description}); access PDU={payload.hex()}"
        )
        self.sender_node.Send(
            dbus.ObjectPath(SENDER_ELEMENT_PATH),
            dbus.UInt16(self.args.destination),
            dbus.UInt16(self.control.app_index),
            empty_options(),
            byte_array(payload),
            reply_handler=self.on_get_live_send_accepted,
            error_handler=lambda error: self.fail(
                f"Canonical sender Node1.Send GetUptimeAndBrightness failed: {error}"
            ),
        )

    def on_get_live_send_accepted(self) -> None:
        print(
            "BlueZ accepted canonical-source GetUptimeAndBrightness for Mesh transmission."
        )
        self.timeout(10, self.on_get_live_timeout)

    def on_get_live_timeout(self) -> None:
        if self.finished or self.live_status is not None:
            return
        if self.live_attempt < self.live_max_attempts:
            print(
                f"No SANlight 0x0D status after 10 seconds; retrying "
                f"({self.live_attempt}/{self.live_max_attempts})."
            )
            self.send_get_live()
            return
        self.finish_get_live()

    def finish_get_live(self) -> None:
        if self.finished:
            return
        if self.live_status is None:
            self.finish(
                "GET-LIVE COMPLETE. No SANlight 0x0D status was observed after "
                f"{self.live_max_attempts} attempt(s) from canonical source "
                f"0x{self.sender_unicast:04X}."
            )
            return

        source, params = self.live_status
        detail = f"raw parameters={params.hex() or '<empty>'}"
        if len(params) == 6:
            uptime_raw = int.from_bytes(params[:4], "little")
            brightness_raw = int.from_bytes(params[4:6], "little")
            detail += (
                f"; uint32_le[0:4]={uptime_raw} ms "
                f"(~{format_milliseconds_as_clock(uptime_raw)}); "
                f"uint16_le[4:6]={brightness_raw}"
            )
        self.finish(
            f"GET-LIVE COMPLETE. SANlight 0x0D status received from "
            f"0x{source:04X} at canonical source 0x{self.sender_unicast:04X}; {detail}."
        )

    def resolve_clock_destinations(self) -> list[int]:
        destination = getattr(self.args, "destination", None)
        if destination is None:
            if not self.control.sanlight_nodes:
                raise PocError("CDB contains no SANlight lamp nodes for destination 'all'.")
            return sorted(self.control.sanlight_nodes)
        return [destination]

    def command_clock_milliseconds(self) -> int:
        if self.args.command == "set-uptime":
            seconds = validate_uptime_seconds(self.args.seconds)
            return validate_uptime_milliseconds(seconds * 1000)
        if self.args.command == "set-time":
            return validate_uptime_milliseconds(self.args.milliseconds)
        if self.args.command == "sync-now":
            milliseconds, now = milliseconds_since_local_midnight(
                self.args.offset_seconds, self.args.offset_milliseconds
            )
            print(
                "Local system time for sync-now: "
                f"{now.isoformat(timespec='milliseconds')} -> "
                f"{milliseconds} milliseconds since local midnight "
                f"({format_milliseconds_as_clock(milliseconds)})."
            )
            return milliseconds
        raise PocError(f"Unsupported clock command: {self.args.command}")

    def send_set_uptime(self) -> None:
        if self.sender_node is None:
            self.fail("Canonical sender Node1 interface is unavailable")
            return

        milliseconds = self.command_clock_milliseconds()
        payload = build_set_uptime_pdu(milliseconds)
        destinations = self.resolve_clock_destinations()
        self.uptime_targets = set(destinations)
        self.uptime_status_seen = set()

        for destination in destinations:
            description = validate_destination(self.control, destination)
            print(
                "Sending SANlight SetUptime "
                f"{milliseconds} ms ({format_milliseconds_as_clock(milliseconds)}) from "
                f"canonical source 0x{self.sender_unicast:04X} to "
                f"0x{destination:04X} ({description}); access PDU={payload.hex()}"
            )
            self.sender_node.Send(
                dbus.ObjectPath(SENDER_ELEMENT_PATH),
                dbus.UInt16(destination),
                dbus.UInt16(self.control.app_index),
                empty_options(),
                byte_array(payload),
                reply_handler=lambda dest=destination: print(
                    "BlueZ accepted canonical-source SetUptime for Mesh "
                    f"transmission to 0x{dest:04X}."
                ),
                error_handler=lambda error, dest=destination: self.fail(
                    f"Canonical sender Node1.Send SetUptime to 0x{dest:04X} failed: {error}"
                ),
            )

        self.timeout(4, self.finish_set_uptime_window)

    def finish_set_uptime_window(self) -> None:
        if self.finished:
            return
        missing = sorted(self.uptime_targets - self.uptime_status_seen)
        seen = sorted(self.uptime_status_seen)
        seen_text = ", ".join(f"0x{value:04X}" for value in seen) or "none"
        missing_text = ", ".join(f"0x{value:04X}" for value in missing) or "none"
        self.finish(
            "SET-UPTIME COMPLETE. "
            f"Status seen from: {seen_text}. Missing status from: {missing_text}."
        )

    def send_max_brightness(self) -> None:
        if self.sender_node is None:
            self.fail("Canonical sender Node1 interface is unavailable")
            return
        payload = build_set_max_brightness_pdu(self.args.percent)
        description = validate_destination(self.control, self.args.destination)
        print(
            f"Sending SANlight SetMaxBrightness {self.args.percent}% from canonical "
            f"source 0x{self.sender_unicast:04X} to 0x{self.args.destination:04X} "
            f"({description}); access PDU={payload.hex()}"
        )
        self.sender_node.Send(
            dbus.ObjectPath(SENDER_ELEMENT_PATH),
            dbus.UInt16(self.args.destination),
            dbus.UInt16(self.control.app_index),
            empty_options(),
            byte_array(payload),
            reply_handler=self.on_send_accepted,
            error_handler=lambda error: self.fail(
                f"Canonical sender Node1.Send failed: {error}"
            ),
        )

    def on_send_accepted(self) -> None:
        print("BlueZ accepted canonical-source access message for Mesh transmission.")
        self.timeout(4, self.finish_send_window)

    def finish_send_window(self) -> None:
        suffix = (
            " A SANlight 0x07 status was received."
            if self.remote_status_seen
            else " No SANlight 0x07 status was observed during the 4-second window."
        )
        self.finish("SEND COMPLETE." + suffix)

    def start_leave_sender(self) -> None:
        state = self.load_sender_state()
        if state is None:
            raise PocError("No canonical sender state found; nothing to leave.")
        token = self._token_from_state(state, "Canonical sender")
        if token is None:
            raise PocError("Canonical sender state has no BlueZ token.")
        print(
            f"Removing only canonical sender 0x{self.sender_unicast:04X} from "
            "bluetooth-meshd; control provisioner and v6 gateway remain untouched..."
        )
        self.network.Leave(
            dbus.UInt64(token),
            reply_handler=self.on_sender_left,
            error_handler=lambda error: self.fail(
                f"Canonical sender Network1.Leave failed: {error}"
            ),
        )

    def on_sender_left(self) -> None:
        try:
            self.args.sender_state.unlink(missing_ok=True)
        except OSError as exc:
            self.fail(
                f"Canonical sender left BlueZ, but state file could not be removed: {exc}"
            )
            return
        self.finish(
            "Canonical sender removed locally; sender state deleted. Control provisioner "
            "and existing SANlight lamp nodes were not reset."
        )

    @staticmethod
    def import_flags() -> dbus.Dictionary:
        return dbus.Dictionary(
            {"IvUpdate": dbus.Boolean(False), "KeyRefresh": dbus.Boolean(False)},
            signature="sv",
        )


def validate_material_pair(
    control: MeshMaterial,
    sender: MeshMaterial,
    control_app_id: int,
    sender_app_id: int,
) -> None:
    if control_app_id == sender_app_id:
        raise ValueError("control App-ID and sender App-ID must be different")
    if control.mesh_uuid != sender.mesh_uuid:
        raise ValueError("control and sender identities do not belong to the same meshUUID")
    if control.net_index != sender.net_index or control.net_key != sender.net_key:
        raise ValueError("control and sender CDB material disagree on primary NetKey")
    if control.app_index != sender.app_index or control.app_key != sender.app_key:
        raise ValueError("control and sender CDB material disagree on primary AppKey")
    if control.provisioner.unicast == sender.provisioner.unicast:
        raise ValueError("control and sender CDB primary unicast addresses overlap")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "SANlight canonical App-ID source-address PoC via BlueZ Bluetooth Mesh v8"
        )
    )
    parser.add_argument(
        "--cdb",
        type=Path,
        required=True,
        help="Path to the private SANlightMesh.json export",
    )
    parser.add_argument(
        "--control-app-id",
        type=int,
        default=1,
        choices=range(0, 16),
        metavar="0..15",
        help="CDB provisioner used as Configuration Client; default: 1 / 0x2400",
    )
    parser.add_argument(
        "--sender-app-id",
        type=int,
        default=2,
        choices=range(0, 16),
        metavar="0..15",
        help="unused CDB App-ID identity used as canonical source; default: 2 / 0x2800",
    )
    parser.add_argument(
        "--iv-index",
        type=lambda value: int(value, 0),
        default=None,
        help="Current Mesh IV Index. Required for initial sender setup when absent from CDB.",
    )
    parser.add_argument(
        "--provisioner-state",
        type=Path,
        default=Path(".sanlight-mesh-poc-provisioner-state.json"),
        help="existing v6 control provisioner BlueZ token/state file",
    )
    parser.add_argument(
        "--sender-state",
        type=Path,
        default=Path(".sanlight-mesh-poc-appid2-sender-state.json"),
        help="canonical sender BlueZ token/state file",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "inspect", help="Parse both CDB App-ID identities and print a redacted JSON summary"
    )
    subparsers.add_parser(
        "list-nodes",
        help="List SANlight lamp node and group addresses detected from the CDB; no secrets printed",
    )
    subparsers.add_parser(
        "setup",
        help="Import/configure canonical sender, bind AppKey 0 and set Default TTL 5",
    )

    get_live = subparsers.add_parser(
        "get-live",
        help="Read GetUptimeAndBrightness from canonical source; two 10-second attempts",
    )
    get_live.add_argument(
        "destination",
        type=parse_destination,
        help="CDB node address; use a unicast node such as 0003",
    )

    get_net_tx = subparsers.add_parser(
        "get-net-tx",
        help=(
            "Read Config Network Transmit state from a CDB unicast node "
            "using its Device Key"
        ),
    )
    get_net_tx.add_argument(
        "destination",
        type=parse_destination,
        help="CDB node/unicast address, e.g. 0002 or 0003",
    )

    set_max = subparsers.add_parser(
        "set-max", help="Send MaxBrightness 20..100 from canonical source"
    )
    set_max.add_argument(
        "destination", type=parse_destination, help="CDB address, e.g. C000"
    )
    set_max.add_argument(
        "percent", type=int, help="integer 20..100; 0 and 1..19 are rejected"
    )

    set_uptime = subparsers.add_parser(
        "set-uptime",
        help="Set lamp clock using seconds since local midnight; sends milliseconds on the wire",
    )
    set_uptime.add_argument(
        "destination",
        type=parse_destination_or_all,
        help="CDB unicast node address such as 0002/0003, or 'all'",
    )
    set_uptime.add_argument(
        "seconds",
        type=int,
        help="seconds since lamp day start, converted to milliseconds for SANlight",
    )


    set_time = subparsers.add_parser(
        "set-time",
        help="Set lamp clock to HH:MM[:SS] on one node or 'all' SANlight nodes",
    )
    set_time.add_argument(
        "destination",
        type=parse_destination_or_all,
        help="CDB unicast node address such as 0002/0003, or 'all'",
    )
    set_time.add_argument(
        "milliseconds",
        type=parse_clock_time,
        help="local clock time as HH:MM or HH:MM:SS",
    )

    sync_now = subparsers.add_parser(
        "sync-now",
        help="Set lamp clock to current local system time; default destination is all lamps",
    )
    sync_now.add_argument(
        "destination",
        nargs="?",
        type=parse_destination_or_all,
        default=None,
        help="optional CDB unicast node address; omit or use 'all' for all SANlight nodes",
    )
    sync_now.add_argument(
        "--offset-seconds",
        type=int,
        default=0,
        help="optional signed seconds offset added before modulo 24h, default 0",
    )
    sync_now.add_argument(
        "--offset-ms",
        dest="offset_milliseconds",
        type=int,
        default=0,
        help="optional signed millisecond offset added before modulo 24h, default 0",
    )

    subparsers.add_parser(
        "leave-sender",
        help="Remove only the local canonical sender; preserve control/v6 identities",
    )
    return parser


def safe_summary(
    control: MeshMaterial, sender: MeshMaterial, args: argparse.Namespace
) -> dict[str, Any]:
    return {
        "meshUUID": str(control.mesh_uuid),
        "control": {
            "appId": args.control_app_id,
            "name": control.provisioner.name,
            "uuid": str(control.provisioner.uuid),
            "unicast": f"0x{control.provisioner.unicast:04X}",
        },
        "sender": {
            "appId": args.sender_app_id,
            "name": sender.provisioner.name,
            "uuid": str(sender.provisioner.uuid),
            "unicast": f"0x{sender.provisioner.unicast:04X}",
            "defaultTTLTarget": TARGET_DEFAULT_TTL,
        },
        "netIndex": control.net_index,
        "appIndex": control.app_index,
        "ivIndexInCdb": control.cdb_iv_index,
        "groups": {
            f"0x{address:04X}": name
            for address, name in sorted(control.groups.items())
        },
        "sanlightNodes": {
            f"0x{address:04X}": name
            for address, name in sorted(control.sanlight_nodes.items())
        },
    }


def print_node_overview(control: MeshMaterial, args: argparse.Namespace) -> None:
    print("SANlight node/address overview")
    print("==============================")
    print(f"CDB file: {args.cdb}")
    print()
    print("Addresses are read from SANlightMesh.json.")
    print("Do not assume that 0002/0003 or C000/C001 exist in another installation.")
    print()

    print("Detected SANlight lamp nodes (unicast targets):")
    if control.sanlight_nodes:
        for address, name in sorted(control.sanlight_nodes.items()):
            print(f"  {address:04X}  0x{address:04X}  {name}")
    else:
        print("  none detected")
    print()

    print("Groups from CDB:")
    if control.groups:
        for address, name in sorted(control.groups.items()):
            print(f"  {address:04X}  0x{address:04X}  {name}")
    else:
        print("  none")
    print()

    print("Usage guidance:")
    print("  get-live requires a unicast lamp node address, not a group.")
    print("  set-time and sync-now accept one unicast node address or 'all'.")
    print("  set-max accepts a CDB address; for first tests prefer unicast nodes.")
    print()

    if control.sanlight_nodes:
        first = next(iter(sorted(control.sanlight_nodes)))
        print("Examples using your first detected lamp node:")
        print(f"  sudo python3 sanlight_canonical_sender_poc.py --cdb {args.cdb} get-live {first:04X}")
        print(f"  sudo python3 sanlight_canonical_sender_poc.py --cdb {args.cdb} set-max {first:04X} 68")
        print(f"  sudo python3 sanlight_canonical_sender_poc.py --cdb {args.cdb} set-time all 10:38:30")
        print(f"  sudo python3 sanlight_canonical_sender_poc.py --cdb {args.cdb} sync-now")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        control = load_mesh_material(args.cdb, args.control_app_id)
        sender = load_mesh_material(args.cdb, args.sender_app_id)
        validate_material_pair(
            control, sender, args.control_app_id, args.sender_app_id
        )

        if args.iv_index is None:
            args.iv_index = control.cdb_iv_index

        if args.command in ("get-live", "set-max", "get-net-tx"):
            validate_destination(control, args.destination)
        if args.command in ("set-uptime", "set-time", "sync-now"):
            if args.destination is not None:
                validate_destination(control, args.destination)
                if args.destination not in control.node_names:
                    raise ValueError(
                        f"{args.command} requires a CDB node/unicast destination or 'all', "
                        "not a group address"
                    )
            elif not control.sanlight_nodes:
                raise ValueError("CDB contains no SANlight lamp nodes for destination 'all'")
        if args.command == "get-net-tx" and args.destination not in control.node_names:
            raise ValueError(
                "get-net-tx requires a CDB node/unicast destination, not a group"
            )
        if args.command == "get-live" and args.destination not in control.node_names:
            raise ValueError(
                "get-live intentionally requires a CDB node/unicast destination, "
                "not a group address"
            )
        if args.command == "set-max":
            validate_max_brightness(args.percent)
        if args.command == "set-uptime":
            validate_uptime_seconds(args.seconds)
        if args.command == "set-time":
            validate_uptime_milliseconds(args.milliseconds)

        if args.command == "list-nodes":
            print_node_overview(control, args)
            return 0

        if args.command == "inspect":
            print(
                json.dumps(
                    safe_summary(control, sender, args),
                    indent=2,
                    ensure_ascii=False,
                )
            )
            print("Secret NetKey/AppKey/DeviceKey values are intentionally not printed.")
            print("Existing v6 gateway 0x2401/state is intentionally untouched.")
            if control.cdb_iv_index is None:
                print("NOTE: CDB has no ivIndex; initial setup requires --iv-index <value>.")
            return 0

        DBusGMainLoop(set_as_default=True)
        runtime = Runtime(args, control, sender)
        return runtime.run()
    except (ValueError, PocError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except dbus.exceptions.DBusException as exc:
        print(f"D-Bus ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
