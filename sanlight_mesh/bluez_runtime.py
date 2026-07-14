"""BlueZ Mesh D-Bus runtime.

Only live commands import this module. Offline CDB inspection stays usable before
D-Bus packages are installed.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from .cdb import MeshMaterial, load_cdb_node_device_key, safe_summary, validate_destination
from .constants import (
    PRIMARY_APP_INDEX,
    SANLIGHT_COMPANY_ID,
    SANLIGHT_MODEL_ID,
    TARGET_DEFAULT_TTL,
)
from .protocol import (
    build_config_default_ttl_set_pdu,
    build_config_network_transmit_get_pdu,
    build_get_max_brightness_pdu,
    build_get_uptime_brightness_pdu,
    build_blackout_pdu,
    build_set_max_brightness_pdu,
    build_set_uptime_pdu,
    build_vendor_model_app_bind_pdu,
    config_default_ttl_status_value,
    decode_config_network_transmit_status,
    format_milliseconds_as_clock,
    get_max_brightness_status_value,
    get_uptime_brightness_status_parameters,
    is_config_default_ttl_status,
    is_config_network_transmit_status,
    is_get_max_brightness_status,
    is_get_uptime_brightness_status,
    is_set_max_brightness_status,
    is_set_uptime_status,
    set_uptime_status_parameters,
    validate_uptime_milliseconds,
    validate_uptime_seconds,
)
from .sequence_recovery import MESH_SEQUENCE_MAX, RECOVERY_TARGET_MAX
from .max_brightness_policy import (
    GET_MAX_MAX_ATTEMPTS,
    GET_MAX_RETRY_DELAY_SECONDS,
    GET_MAX_STATUS_TIMEOUT_SECONDS,
    MAX_BRIGHTNESS_MISMATCH_EXIT_CODE,
    MAX_BRIGHTNESS_UNCONFIRMED_EXIT_CODE,
    SET_MAX_RETRY_DELAY_SECONDS,
    SET_MAX_STATUS_TIMEOUT_SECONDS,
    max_attempts_for_destination,
    set_max_status_rejection_reason,
    unicast_status_rejection_reason,
)
from .blackout_state import (
    BlackoutEntry,
    create_blackout_snapshot,
    mark_blackout_snapshot_restored,
)
from .traffic_safety import record_brightness_write
from .state import (
    StateError,
    read_state,
    token_from_state,
    validate_state_identity,
    write_state,
)

MESH_SERVICE = "org.bluez.mesh"
MESH_NETWORK_IFACE = "org.bluez.mesh.Network1"
MESH_NODE_IFACE = "org.bluez.mesh.Node1"
MESH_MGMT_IFACE = "org.bluez.mesh.Management1"
MESH_APPLICATION_IFACE = "org.bluez.mesh.Application1"
MESH_ELEMENT_IFACE = "org.bluez.mesh.Element1"
DBUS_OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

CONTROL_APP_ROOT = "/com/nibbels/sanlight_mesh_poc_provisioner"
CONTROL_ELEMENT_PATH = CONTROL_APP_ROOT + "/ele00"
SENDER_APP_ROOT = "/com/nibbels/sanlight_mesh_poc_appid2_sender"
SENDER_ELEMENT_PATH = SENDER_APP_ROOT + "/ele00"

CONFIG_CLIENT_MODEL_ID = 0x0001
APP_COMPANY_ID = SANLIGHT_COMPANY_ID
APP_VERSION_ID = 0x0004
CONTROL_PRODUCT_ID = 0x0001
SENDER_PRODUCT_ID = 0x0003


class BluezRuntimeError(RuntimeError):
    pass


def byte_array(data: bytes) -> dbus.Array:
    return dbus.Array([dbus.Byte(value) for value in data], signature="y")


def empty_options() -> dbus.Dictionary:
    return dbus.Dictionary({}, signature="sv")


def dbus_error_name(error: BaseException) -> str:
    getter = getattr(error, "get_dbus_name", None)
    return str(getter()) if callable(getter) else ""


def milliseconds_since_local_midnight(
    offset_seconds: int = 0, offset_milliseconds: int = 0
) -> tuple[int, datetime]:
    now = datetime.now().astimezone()
    milliseconds = (
        now.hour * 3_600_000
        + now.minute * 60_000
        + now.second * 1_000
        + now.microsecond // 1_000
        + offset_seconds * 1_000
        + offset_milliseconds
    )
    return milliseconds % 86_400_000, now


class ControlApplication(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus, runtime: "BluezRuntime") -> None:
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
    def __init__(self, bus: dbus.SystemBus, runtime: "BluezRuntime") -> None:
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
    def __init__(self, bus: dbus.SystemBus, runtime: "BluezRuntime") -> None:
        self.runtime = runtime
        super().__init__(bus, CONTROL_ELEMENT_PATH)

    def get_properties(self) -> dict[str, dict[str, Any]]:
        sig_models = dbus.Array(
            [(dbus.UInt16(CONFIG_CLIENT_MODEL_ID), dbus.Dictionary({}, signature="sv"))],
            signature="(qa{sv})",
        )
        return {
            MESH_ELEMENT_IFACE: {
                "Index": dbus.Byte(0),
                "Models": sig_models,
                "VendorModels": dbus.Array([], signature="(qqa{sv})"),
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
        source_int = int(source)
        payload = bytes(int(value) for value in data)
        print(
            f"Control RX DevKey: src=0x{source_int:04X} remote={bool(remote)} "
            f"netKey={int(net_index)} pdu={payload.hex()}"
        )

        if is_config_network_transmit_status(payload):
            if self.runtime.args.command != "get-net-tx":
                return
            if source_int != self.runtime.args.destination:
                print(
                    "Ignoring Config Network Transmit Status from unexpected source "
                    f"0x{source_int:04X}."
                )
                return
            transmissions, interval_ms = decode_config_network_transmit_status(payload)
            self.runtime.on_network_transmit_status(
                source_int, transmissions, interval_ms, payload[2]
            )
            return

        if len(payload) >= 6 and payload[:2] == bytes.fromhex("8003"):
            if source_int != self.runtime.sender_unicast:
                return
            status = payload[2]
            print(f"Config AppKey Status: 0x{status:02X}")
            if status == 0:
                self.runtime.on_sender_app_key_added()
            else:
                self.runtime.fail(f"Config AppKey Add returned Mesh status 0x{status:02X}")
            return

        if len(payload) >= 3 and payload[:2] == bytes.fromhex("803e"):
            if source_int != self.runtime.sender_unicast:
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
            if source_int != self.runtime.sender_unicast:
                return
            self.runtime.on_sender_ttl_status(config_default_ttl_status_value(payload))

    @dbus.service.method(MESH_ELEMENT_IFACE, in_signature="qa{sv}", out_signature="")
    def UpdateModelConfiguration(
        self, model_id: dbus.UInt16, config: dbus.Dictionary
    ) -> None:
        print(f"Control model configuration updated: model=0x{int(model_id):04X}")


class SenderElement(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus, runtime: "BluezRuntime") -> None:
        self.runtime = runtime
        super().__init__(bus, SENDER_ELEMENT_PATH)

    def get_properties(self) -> dict[str, dict[str, Any]]:
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
        source_int = int(source)
        payload = bytes(int(value) for value in data)
        try:
            destination_text = f"0x{int(destination):04X}"
        except (TypeError, ValueError):
            destination_text = str(destination)
        print(
            f"Sender RX access: src=0x{source_int:04X} dst={destination_text} "
            f"appKey={int(key_index)} pdu={payload.hex()}"
        )

        if is_set_max_brightness_status(payload):
            if self.runtime.args.command not in (
                "set-max", "blackout", "restore-blackout"
            ):
                print(
                    "Ignoring SANlight SetMaxBrightness status because no "
                    "set-max transaction is active."
                )
                return
            try:
                response_destination = int(destination)
            except (TypeError, ValueError):
                response_destination = None
            reason = set_max_status_rejection_reason(
                source=source_int,
                key_index=int(key_index),
                response_destination=response_destination,
                requested_destination=self.runtime.current_brightness_destination,
                expected_app_index=self.runtime.control.app_index,
                sender_unicast=self.runtime.sender_unicast,
                node_addresses=self.runtime.control.sanlight_nodes,
                group_addresses=self.runtime.control.groups,
            )
            if reason is not None:
                print(f"Ignoring unrelated SANlight 0x07 status: {reason}.")
                return
            self.runtime.on_set_max_status(source_int)
            return

        if is_get_max_brightness_status(payload):
            if (
                self.runtime.args.command not in (
                    "get-max", "set-max", "blackout", "restore-blackout"
                )
                or not self.runtime.get_max_started
            ):
                print(
                    "Ignoring SANlight GetMaxBrightness status because no "
                    "readback transaction is active."
                )
                return
            try:
                response_destination = int(destination)
            except (TypeError, ValueError):
                response_destination = None
            reason = unicast_status_rejection_reason(
                source=source_int,
                key_index=int(key_index),
                response_destination=response_destination,
                requested_destination=self.runtime.current_brightness_destination,
                expected_app_index=self.runtime.control.app_index,
                sender_unicast=self.runtime.sender_unicast,
                node_addresses=self.runtime.control.sanlight_nodes,
            )
            if reason is not None:
                print(f"Ignoring unrelated SANlight 0x09 status: {reason}.")
                return
            try:
                value = get_max_brightness_status_value(payload)
            except ValueError as exc:
                self.runtime.get_max_malformed_status_seen = True
                print(
                    "Ignoring malformed SANlight GetMaxBrightness status "
                    f"from 0x{source_int:04X}: {exc}; raw={payload.hex()}."
                )
                return
            self.runtime.on_get_max_status(source_int, value)
            return

        if is_set_uptime_status(payload):
            params = set_uptime_status_parameters(payload)
            detail = f"src=0x{source_int:04X} parameters={params.hex()}"
            if len(params) >= 4:
                milliseconds = int.from_bytes(params[:4], "little")
                detail += (
                    f"; uint32_le[0:4]={milliseconds} ms "
                    f"(~{format_milliseconds_as_clock(milliseconds)})"
                )
            print(f"Received SANlight SetUptime status (vendor opcode 0x0B): {detail}")
            self.runtime.uptime_status_seen.add(source_int)
            self.runtime.remote_status_seen = True
            return

        if is_get_uptime_brightness_status(payload):
            if (
                self.runtime.args.command == "get-live"
                and source_int != self.runtime.args.destination
            ):
                print(
                    f"Ignoring SANlight 0x0D status from unexpected source "
                    f"0x{source_int:04X}."
                )
                return
            params = get_uptime_brightness_status_parameters(payload)
            self.runtime.live_status = (source_int, params)
            self.runtime.finish_get_live()

    @dbus.service.method(MESH_ELEMENT_IFACE, in_signature="qbqay", out_signature="")
    def DevKeyMessageReceived(
        self,
        source: dbus.UInt16,
        remote: dbus.Boolean,
        net_index: dbus.UInt16,
        data: dbus.Array,
    ) -> None:
        source_int = int(source)
        payload = bytes(int(value) for value in data)
        print(
            f"Sender RX DevKey: src=0x{source_int:04X} remote={bool(remote)} "
            f"netKey={int(net_index)} pdu={payload.hex()}"
        )

        if (
            self.runtime.args.command == "get-net-tx-sender"
            and is_config_network_transmit_status(payload)
        ):
            if source_int != self.runtime.args.destination:
                print(
                    "Ignoring Config Network Transmit Status from unexpected source "
                    f"0x{source_int:04X}."
                )
                return
            transmissions, interval_ms = decode_config_network_transmit_status(payload)
            self.runtime.on_network_transmit_status(
                source_int, transmissions, interval_ms, payload[2]
            )

    @dbus.service.method(MESH_ELEMENT_IFACE, in_signature="qa{sv}", out_signature="")
    def UpdateModelConfiguration(
        self, model_id: dbus.UInt16, config: dbus.Dictionary
    ) -> None:
        config_dict = dict(config)
        vendor = int(config_dict.get("Vendor", 0xFFFF))
        bindings = [int(value) for value in config_dict.get("Bindings", [])]
        if (
            int(model_id) == SANLIGHT_MODEL_ID
            and vendor == SANLIGHT_COMPANY_ID
            and PRIMARY_APP_INDEX in bindings
        ):
            self.runtime.on_sender_binding_confirmed("UpdateModelConfiguration")


class BluezRuntime:
    def __init__(
        self, args: argparse.Namespace, control: MeshMaterial, sender: MeshMaterial
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
        self.sender_management: dbus.Interface | None = None
        self.sender_properties: dbus.Interface | None = None
        self.sender_bound = False
        self.sender_remote_key_ready = False
        self.app_key_added = False
        self.app_key_add_requested = False
        self.binding_requested = False
        self.ttl_requested = False
        self.ttl_confirmed = False
        self.remote_status_seen = False
        self.set_max_generation = 0
        self.set_max_attempt = 0
        self.set_max_max_attempts = 0
        self.set_max_status_sources: set[int] = set()
        self.get_max_started = False
        self.get_max_generation = 0
        self.get_max_attempt = 0
        self.get_max_status: tuple[int, int] | None = None
        self.get_max_malformed_status_seen = False
        self.get_max_retry_pending = False
        self.get_max_purpose = ""
        self.current_brightness_destination = int(
            getattr(args, "destination", 0) or 0
        )
        self.current_brightness_percent = getattr(args, "percent", None)
        self.brightness_write_recorded = False
        self.blackout_original_values: dict[int, int] = {}
        self.blackout_targets: list[int] = []
        self.preflight_queue: list[int] = []
        self.restore_desired: dict[int, int] = {}
        self.batch_write_queue: list[tuple[int, int]] = []
        self.batch_write_results: list[tuple[int, int]] = []
        self.blackout_snapshot_path: Path | None = None
        self.network_transmit_status: tuple[int, int, int, int] | None = None
        self.live_status: tuple[int, bytes] | None = None
        self.live_attempt = 0
        self.live_max_attempts = 2
        self.uptime_targets: set[int] = set()
        self.uptime_status_seen: set[int] = set()

        try:
            DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()
            self.control_element = ControlElement(self.bus, self)
            self.control_application = ControlApplication(self.bus, self)
            self.sender_element = SenderElement(self.bus, self)
            self.sender_application = SenderApplication(self.bus, self)
            mesh_object = self.bus.get_object(MESH_SERVICE, "/org/bluez/mesh")
            self.network = dbus.Interface(mesh_object, MESH_NETWORK_IFACE)
        except dbus.exceptions.DBusException as exc:
            raise BluezRuntimeError(
                "Cannot connect to org.bluez.mesh. Check "
                "sanlight-meshd-generic.service and journalctl."
            ) from exc

    def log_identity(self) -> None:
        import json

        print(
            json.dumps(
                safe_summary(
                    self.control,
                    self.sender,
                    self.args.control_app_id,
                    self.args.sender_app_id,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        print("Secret NetKey/AppKey/DeviceKey values are intentionally not printed.")
        print("Local BlueZ state tokens are intentionally not printed.")

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
        try:
            if self.args.command == "setup":
                self.start_setup()
            elif self.args.command in (
                "get-live",
                "get-max",
                "get-net-tx-sender",
                "show-sender-state",
                "set-max",
                "blackout",
                "restore-blackout",
                "set-uptime",
                "set-time",
                "sync-now",
            ):
                self.start_sender_command()
            elif self.args.command == "get-net-tx":
                self.start_control_command()
            elif self.args.command == "leave-sender":
                self.start_leave_sender()
            else:
                raise BluezRuntimeError(f"Unsupported runtime command: {self.args.command}")
            if not self.finished:
                self.mainloop.run()
            return self.exit_code
        except StateError as exc:
            raise BluezRuntimeError(str(exc)) from exc
        except dbus.exceptions.DBusException as exc:
            raise BluezRuntimeError(f"BlueZ D-Bus call failed: {exc}") from exc

    def _control_expected_state(self) -> dict[str, Any]:
        return {
            "role": "provisioner",
            "meshUUID": str(self.control.mesh_uuid),
            "provisionerUUID": str(self.control.provisioner.uuid),
            "unicast": self.control.provisioner.unicast,
            "appId": self.args.control_app_id,
        }

    def _sender_expected_state(self) -> dict[str, Any]:
        return {
            "role": "canonical-sender",
            "meshUUID": str(self.control.mesh_uuid),
            "senderProvisionerUUID": str(self.sender.provisioner.uuid),
            "senderAppId": self.args.sender_app_id,
            "unicast": self.sender_unicast,
        }

    def load_control_state(self) -> dict[str, Any] | None:
        state = read_state(self.args.provisioner_state)
        if state is not None:
            validate_state_identity(state, self._control_expected_state(), "Control provisioner")
        return state

    def load_sender_state(self) -> dict[str, Any] | None:
        state = read_state(self.args.sender_state)
        if state is not None:
            validate_state_identity(state, self._sender_expected_state(), "Canonical sender")
        return state

    def save_control_state(self, token: int) -> None:
        state = self._control_expected_state()
        state.update({"token": f"{token:016x}", "ivIndex": self.args.iv_index})
        write_state(self.args.provisioner_state, state)
        print(f"Control provisioner state stored securely in {self.args.provisioner_state}.")

    def save_sender_state(self, token: int) -> None:
        state = self._sender_expected_state()
        state.update({"token": f"{token:016x}", "ivIndex": self.args.iv_index})
        write_state(self.args.sender_state, state)
        print(f"Canonical sender state stored securely in {self.args.sender_state}.")

    @staticmethod
    def import_flags() -> dbus.Dictionary:
        return dbus.Dictionary(
            {"IvUpdate": dbus.Boolean(False), "KeyRefresh": dbus.Boolean(False)},
            signature="sv",
        )

    def start_setup(self) -> None:
        if self.args.iv_index is None:
            raise BluezRuntimeError("Initial setup requires a verified IV Index")
        self.ensure_control()

    def ensure_control(self) -> None:
        state = self.load_control_state()
        token = None if state is None else token_from_state(state, "Control provisioner")
        if token is not None:
            print("Control provisioner state found; attaching securely.")
            self.attach_control(token)
            return
        print(
            f"Importing control CDB provisioner {self.control.provisioner.name} at "
            f"0x{self.control.provisioner.unicast:04X}..."
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
            reply_handler=lambda: print("Control provisioner Import request accepted."),
            error_handler=lambda error: self.fail(f"Control Network1.Import failed: {error}"),
        )
        self.timeout(
            20,
            lambda: self.fail("Timed out waiting for control JoinComplete")
            if not self.finished and self.control_node is None
            else None,
        )

    def on_control_join_complete(self, token: int) -> None:
        if self.finished:
            return
        self.save_control_state(token)
        print("Control provisioner import completed; token value was not displayed.")
        self.attach_control(token)

    def attach_control(self, token: int) -> None:
        print("Attaching control provisioner using protected local state.")
        self.network.Attach(
            dbus.ObjectPath(CONTROL_APP_ROOT),
            dbus.UInt64(token),
            reply_handler=self.on_control_attach,
            error_handler=lambda error: self.fail(f"Control Network1.Attach failed: {error}"),
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
        self.control_management.ImportSubnet(
            dbus.UInt16(self.control.net_index),
            byte_array(self.control.net_key),
            reply_handler=self.on_control_subnet_ready,
            error_handler=self.on_control_subnet_error,
        )

    def on_control_subnet_error(self, error: BaseException) -> None:
        if dbus_error_name(error).endswith("AlreadyExists"):
            self.on_control_subnet_ready()
            return
        self.fail(f"Control Management1.ImportSubnet failed: {error}")

    def on_control_subnet_ready(self) -> None:
        if self.finished or self.control_management is None:
            return
        print(f"Control NetKey index {self.control.net_index} is available locally.")
        self.control_management.ImportAppKey(
            dbus.UInt16(self.control.net_index),
            dbus.UInt16(self.control.app_index),
            byte_array(self.control.app_key),
            reply_handler=self.on_control_app_key_ready,
            error_handler=self.on_control_app_key_error,
        )

    def on_control_app_key_error(self, error: BaseException) -> None:
        if dbus_error_name(error).endswith("AlreadyExists"):
            self.on_control_app_key_ready()
            return
        self.fail(f"Control Management1.ImportAppKey failed: {error}")

    def on_control_app_key_ready(self) -> None:
        if self.finished:
            return
        print(f"Control AppKey index {self.control.app_index} is available locally.")
        if self.args.command == "get-net-tx":
            self.prepare_network_transmit_probe()
        else:
            self.ensure_sender()

    def start_control_command(self) -> None:
        state = self.load_control_state()
        if state is None:
            raise BluezRuntimeError("No control provisioner state found; run setup first")
        token = token_from_state(state, "Control provisioner")
        if token is None:
            raise BluezRuntimeError("Control provisioner state has no token; rerun setup")
        self.attach_control(token)

    def prepare_network_transmit_probe(self) -> None:
        if self.control_management is None:
            self.fail("Control Management1 interface is unavailable")
            return
        target = self.args.destination
        device_key = load_cdb_node_device_key(self.args.cdb, target)
        print(f"Preparing read-only Config Network Transmit Get for 0x{target:04X}.")
        self.control_management.ImportRemoteNode(
            dbus.UInt16(target),
            dbus.Byte(1),
            byte_array(device_key),
            reply_handler=self.send_network_transmit_get,
            error_handler=self.on_network_probe_remote_key_error,
        )

    def on_network_probe_remote_key_error(self, error: BaseException) -> None:
        if dbus_error_name(error).endswith("AlreadyExists"):
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
            f"Sending read-only Config Network Transmit Get to "
            f"0x{self.args.destination:04X} ({description}); PDU={payload.hex()}"
        )
        self.control_node.DevKeySend(
            dbus.ObjectPath(CONTROL_ELEMENT_PATH),
            dbus.UInt16(self.args.destination),
            dbus.Boolean(True),
            dbus.UInt16(self.control.net_index),
            empty_options(),
            byte_array(payload),
            reply_handler=lambda: print("Config Network Transmit Get accepted."),
            error_handler=lambda error: self.fail(
                f"Control Node1.DevKeySend Network Transmit Get failed: {error}"
            ),
        )
        self.timeout(10, self.finish_network_transmit_probe)

    def on_network_transmit_status(
        self, source: int, transmissions: int, interval_ms: int, encoded: int
    ) -> None:
        if self.finished:
            return
        self.network_transmit_status = (source, transmissions, interval_ms, encoded)
        self.finish_network_transmit_probe()

    def finish_network_transmit_probe(self) -> None:
        if self.finished:
            return
        if self.network_transmit_status is None:
            self.finish(
                "GET-NET-TX COMPLETE. No Config Network Transmit Status was observed."
            )
            return
        source, transmissions, interval_ms, encoded = self.network_transmit_status
        self.finish(
            f"GET-NET-TX COMPLETE. Node 0x{source:04X}: "
            f"transmissions={transmissions}, interval={interval_ms} ms, "
            f"encoded=0x{encoded:02X}."
        )

    def ensure_sender(self) -> None:
        state = self.load_sender_state()
        token = None if state is None else token_from_state(state, "Canonical sender")
        if token is not None:
            print("Canonical sender state found; attaching securely.")
            self.attach_sender(token)
            return
        print(
            f"Importing canonical sender {self.sender.provisioner.name} at "
            f"0x{self.sender_unicast:04X}..."
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
            reply_handler=lambda: print("Canonical sender Import request accepted."),
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
        self.save_sender_state(token)
        print("Canonical sender import completed; token value was not displayed.")
        self.attach_sender(token)

    def attach_sender(self, token: int) -> None:
        print("Attaching canonical sender using protected local state.")
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
        self.sender_management = dbus.Interface(node_object, MESH_MGMT_IFACE)
        self.sender_properties = dbus.Interface(node_object, DBUS_PROPERTIES_IFACE)
        self.sender_bound = self.configuration_has_binding(configuration)
        print(f"Canonical sender AppKey-0 vendor binding present: {self.sender_bound}")
        if self.args.command == "setup":
            self.import_sender_device_key_into_control()
        elif not self.sender_bound:
            self.fail("Canonical sender vendor model is not bound; run setup first")
        else:
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
        self.control_management.ImportRemoteNode(
            dbus.UInt16(self.sender_unicast),
            dbus.Byte(1),
            byte_array(self.sender.provisioner.device_key),
            reply_handler=self.on_sender_remote_key_ready,
            error_handler=self.on_sender_remote_key_error,
        )

    def on_sender_remote_key_error(self, error: BaseException) -> None:
        if dbus_error_name(error).endswith("AlreadyExists"):
            self.on_sender_remote_key_ready()
            return
        self.fail(f"Control Management1.ImportRemoteNode failed: {error}")

    def on_sender_remote_key_ready(self) -> None:
        if self.finished:
            return
        self.sender_remote_key_ready = True
        if self.sender_bound:
            self.send_sender_ttl_set()
        else:
            self.send_sender_app_key_add()

    def send_sender_app_key_add(self) -> None:
        if self.control_node is None or self.app_key_add_requested:
            return
        self.app_key_add_requested = True
        self.control_node.AddAppKey(
            dbus.ObjectPath(CONTROL_ELEMENT_PATH),
            dbus.UInt16(self.sender_unicast),
            dbus.UInt16(self.control.app_index),
            dbus.UInt16(self.control.net_index),
            dbus.Boolean(False),
            reply_handler=lambda: print("Config AppKey Add accepted."),
            error_handler=lambda error: self.fail(f"Control Node1.AddAppKey failed: {error}"),
        )
        self.timeout(
            12,
            lambda: self.fail("No successful Config AppKey Status was observed")
            if not self.finished and not self.app_key_added
            else None,
        )

    def on_sender_app_key_added(self) -> None:
        if self.finished or self.app_key_added:
            return
        self.app_key_added = True
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
        print(f"Binding AppKey 0 to canonical sender vendor model; PDU={payload.hex()}")
        self.control_node.DevKeySend(
            dbus.ObjectPath(CONTROL_ELEMENT_PATH),
            dbus.UInt16(self.sender_unicast),
            dbus.Boolean(True),
            dbus.UInt16(self.control.net_index),
            empty_options(),
            byte_array(payload),
            reply_handler=lambda: print("Config Model App Bind accepted."),
            error_handler=lambda error: self.fail(
                f"Control Node1.DevKeySend bind failed: {error}"
            ),
        )
        self.timeout(
            12,
            lambda: self.fail("No successful model-binding confirmation was observed")
            if not self.finished and not self.sender_bound
            else None,
        )

    def on_sender_binding_confirmed(self, source: str) -> None:
        if self.finished or self.sender_bound:
            return
        self.sender_bound = True
        print(f"Canonical sender binding confirmed via {source}.")
        if self.sender_remote_key_ready:
            self.send_sender_ttl_set()

    def send_sender_ttl_set(self) -> None:
        if self.control_node is None or self.ttl_requested:
            return
        self.ttl_requested = True
        payload = build_config_default_ttl_set_pdu(TARGET_DEFAULT_TTL)
        print(f"Setting canonical sender Default TTL to {TARGET_DEFAULT_TTL}.")
        self.control_node.DevKeySend(
            dbus.ObjectPath(CONTROL_ELEMENT_PATH),
            dbus.UInt16(self.sender_unicast),
            dbus.Boolean(True),
            dbus.UInt16(self.control.net_index),
            empty_options(),
            byte_array(payload),
            reply_handler=lambda: print("Config Default TTL Set accepted."),
            error_handler=lambda error: self.fail(
                f"Control Node1.DevKeySend Default TTL Set failed: {error}"
            ),
        )
        self.timeout(
            12,
            lambda: self.fail("No Config Default TTL Status=5 was observed")
            if not self.finished and not self.ttl_confirmed
            else None,
        )

    def on_sender_ttl_status(self, ttl: int) -> None:
        if self.finished:
            return
        if ttl != TARGET_DEFAULT_TTL:
            self.fail(f"Canonical sender returned Default TTL {ttl}; expected 5")
            return
        self.ttl_confirmed = True
        self.finish(
            "SETUP OK: local BlueZ identities are configured, AppKey 0 is bound "
            "to vendor model 0x0A8B/0x0001, and sender Default TTL is 5. "
            "No lamp time or brightness command was sent."
        )

    def start_sender_command(self) -> None:
        state = self.load_sender_state()
        if state is None:
            raise BluezRuntimeError("No canonical sender state found; run setup first")
        token = token_from_state(state, "Canonical sender")
        if token is None:
            raise BluezRuntimeError("Canonical sender state has no token; rerun setup")
        self.attach_sender(token)

    def on_sender_ready(self) -> None:
        if self.args.command == "get-net-tx-sender":
            self.prepare_sender_network_transmit_probe()
        elif self.args.command == "show-sender-state":
            self.show_sender_state()
        elif self.args.command == "get-live":
            self.send_get_live()
        elif self.args.command == "get-max":
            self.start_get_max_readback()
        elif self.args.command == "set-max":
            self.prepare_single_brightness_write(
                self.args.destination, self.args.percent
            )
        elif self.args.command == "blackout":
            self.start_blackout_preflight()
        elif self.args.command == "restore-blackout":
            self.start_restore_preflight()
        elif self.args.command in ("set-uptime", "set-time", "sync-now"):
            self.send_set_uptime()
        else:
            self.fail(f"Unexpected command after sender attach: {self.args.command}")

    def show_sender_state(self) -> None:
        if self.sender_properties is None:
            self.fail("Canonical sender D-Bus properties interface is unavailable")
            return
        try:
            properties = dict(self.sender_properties.GetAll(MESH_NODE_IFACE))
        except dbus.exceptions.DBusException as exc:
            self.fail(f"Cannot read canonical sender Node1 properties: {exc}")
            return

        sequence = int(properties.get("SequenceNumber", 0))
        if not 0 <= sequence <= MESH_SEQUENCE_MAX:
            self.fail(
                "Canonical sender reports an invalid SequenceNumber outside "
                "the 24-bit Mesh range"
            )
            return
        iv_index = int(properties.get("IvIndex", 0))
        iv_update = bool(properties.get("IvUpdate", False))
        last_heard = int(properties.get("SecondsSinceLastHeard", 0))
        addresses = [int(value) for value in properties.get("Addresses", [])]
        address_text = ", ".join(f"0x{value:04X}" for value in addresses) or "none"
        remaining = max(0, MESH_SEQUENCE_MAX - sequence)

        print("Canonical sender live BlueZ state (non-secret):")
        print(f"  addresses={address_text}")
        print(f"  ivIndex={iv_index}")
        print(f"  ivUpdate={iv_update}")
        print(f"  sequenceNumber={sequence} (0x{sequence:06X})")
        print(f"  sequenceRemaining={remaining}")
        print(f"  secondsSinceLastHeard={last_heard}")
        one_message_days = remaining / 86_400
        verified_set_days_fast = remaining / (4 * 86_400)
        verified_set_days_best = remaining / (2 * 86_400)
        print(
            "  estimatedBudgetAtOneOutgoingMessagePerSecond="
            f"{one_message_days:.1f} days"
        )
        print(
            "  estimatedBudgetAtOneVerifiedSetMaxPerSecond="
            f"{verified_set_days_fast:.1f}..{verified_set_days_best:.1f} days "
            "(4..2 outgoing messages per transaction)"
        )
        print(
            "NOTE: use event-driven control and avoid per-second read or write "
            "loops. Routine MaxBrightness automation should normally update no "
            "more often than once per minute."
        )
        if sequence > RECOVERY_TARGET_MAX:
            print(
                "WARNING: sequenceNumber is above this project's recovery safety "
                "ceiling. Do not advance it further; plan a proper IV Update or "
                "a destructive Mesh rebuild."
            )
        self.finish("SHOW-SENDER-STATE COMPLETE. No secret value was displayed.")


    def prepare_sender_network_transmit_probe(self) -> None:
        if self.sender_management is None:
            self.fail("Canonical sender Management1 interface is unavailable")
            return
        target = self.args.destination
        device_key = load_cdb_node_device_key(self.args.cdb, target)
        print(
            "Preparing read-only Config Network Transmit Get from canonical "
            f"sender 0x{self.sender_unicast:04X} to 0x{target:04X}."
        )
        self.sender_management.ImportRemoteNode(
            dbus.UInt16(target),
            dbus.Byte(1),
            byte_array(device_key),
            reply_handler=self.send_sender_network_transmit_get,
            error_handler=self.on_sender_network_probe_remote_key_error,
        )

    def on_sender_network_probe_remote_key_error(self, error: BaseException) -> None:
        if dbus_error_name(error).endswith("AlreadyExists"):
            self.send_sender_network_transmit_get()
            return
        self.fail(f"Sender Management1.ImportRemoteNode failed: {error}")

    def send_sender_network_transmit_get(self) -> None:
        if self.sender_node is None:
            self.fail("Canonical sender Node1 interface is unavailable")
            return
        payload = build_config_network_transmit_get_pdu()
        description = validate_destination(self.control, self.args.destination)
        print(
            "Sending read-only Config Network Transmit Get via canonical sender "
            f"0x{self.sender_unicast:04X} to 0x{self.args.destination:04X} "
            f"({description}); PDU={payload.hex()}"
        )
        self.sender_node.DevKeySend(
            dbus.ObjectPath(SENDER_ELEMENT_PATH),
            dbus.UInt16(self.args.destination),
            dbus.Boolean(True),
            dbus.UInt16(self.control.net_index),
            empty_options(),
            byte_array(payload),
            reply_handler=lambda: print(
                "Sender Config Network Transmit Get accepted."
            ),
            error_handler=lambda error: self.fail(
                "Canonical sender Node1.DevKeySend Network Transmit Get failed: "
                f"{error}"
            ),
        )
        self.timeout(10, self.finish_network_transmit_probe)

    def send_get_live(self) -> None:
        if self.sender_node is None:
            self.fail("Canonical sender Node1 interface is unavailable")
            return
        self.live_attempt += 1
        payload = build_get_uptime_brightness_pdu()
        description = validate_destination(self.control, self.args.destination)
        print(
            f"Sending read-only GetUptimeAndBrightness attempt "
            f"{self.live_attempt}/{self.live_max_attempts} to "
            f"0x{self.args.destination:04X} ({description}); PDU={payload.hex()}"
        )
        self.sender_node.Send(
            dbus.ObjectPath(SENDER_ELEMENT_PATH),
            dbus.UInt16(self.args.destination),
            dbus.UInt16(self.control.app_index),
            empty_options(),
            byte_array(payload),
            reply_handler=self.on_get_live_send_accepted,
            error_handler=lambda error: self.fail(
                f"Node1.Send GetUptimeAndBrightness failed: {error}"
            ),
        )

    def on_get_live_send_accepted(self) -> None:
        print("GetUptimeAndBrightness accepted for Mesh transmission.")
        self.timeout(10, self.on_get_live_timeout)

    def on_get_live_timeout(self) -> None:
        if self.finished or self.live_status is not None:
            return
        if self.live_attempt < self.live_max_attempts:
            print("No SANlight 0x0D status after 10 seconds; retrying.")
            self.send_get_live()
        else:
            self.finish_get_live()

    def finish_get_live(self) -> None:
        if self.finished:
            return
        if self.live_status is None:
            self.finish(
                "GET-LIVE COMPLETE. No SANlight 0x0D status was observed after "
                f"{self.live_max_attempts} attempts."
            )
            return
        source, params = self.live_status
        detail = f"raw parameters={params.hex()}"
        if len(params) == 6:
            uptime_raw = int.from_bytes(params[:4], "little")
            brightness_raw = int.from_bytes(params[4:6], "little")
            detail += (
                f"; uint32_le[0:4]={uptime_raw} ms "
                f"(~{format_milliseconds_as_clock(uptime_raw)}); "
                f"uint16_le[4:6]={brightness_raw}"
            )
        self.finish(f"GET-LIVE COMPLETE. Status from 0x{source:04X}; {detail}.")

    def resolve_clock_destinations(self) -> list[int]:
        destination = getattr(self.args, "destination", None)
        if destination is None:
            if not self.control.sanlight_nodes:
                raise BluezRuntimeError("CDB contains no SANlight lamp nodes")
            return sorted(self.control.sanlight_nodes)
        return [destination]

    def command_clock_milliseconds(self) -> int:
        if self.args.command == "set-uptime":
            return validate_uptime_milliseconds(
                validate_uptime_seconds(self.args.seconds) * 1000
            )
        if self.args.command == "set-time":
            return validate_uptime_milliseconds(self.args.milliseconds)
        if self.args.command == "sync-now":
            milliseconds, now = milliseconds_since_local_midnight(
                self.args.offset_seconds, self.args.offset_milliseconds
            )
            print(
                f"Local system time: {now.isoformat(timespec='milliseconds')} -> "
                f"{format_milliseconds_as_clock(milliseconds)}."
            )
            return milliseconds
        raise BluezRuntimeError(f"Unsupported clock command: {self.args.command}")

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
                f"Sending SetUptime {format_milliseconds_as_clock(milliseconds)} "
                f"to 0x{destination:04X} ({description}); PDU={payload.hex()}"
            )
            self.sender_node.Send(
                dbus.ObjectPath(SENDER_ELEMENT_PATH),
                dbus.UInt16(destination),
                dbus.UInt16(self.control.app_index),
                empty_options(),
                byte_array(payload),
                reply_handler=lambda dest=destination: print(
                    f"SetUptime accepted for transmission to 0x{dest:04X}."
                ),
                error_handler=lambda error, dest=destination: self.fail(
                    f"Node1.Send SetUptime to 0x{dest:04X} failed: {error}"
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
            f"SET-UPTIME COMPLETE. Status seen from: {seen_text}. "
            f"Missing status from: {missing_text}."
        )

    def _cancel_get_max_transaction(self) -> None:
        """Invalidate every timeout/retry belonging to the previous readback."""
        self.get_max_generation += 1
        self.get_max_started = False
        self.get_max_status = None
        self.get_max_retry_pending = False
        self.get_max_purpose = ""

    def _reset_brightness_write_transaction(self) -> None:
        self.set_max_generation += 1
        self.set_max_attempt = 0
        self.set_max_max_attempts = max_attempts_for_destination(
            self.current_brightness_destination,
            self.control.sanlight_nodes,
        )
        self.set_max_status_sources = set()
        self._cancel_get_max_transaction()

    def prepare_single_brightness_write(self, destination: int, percent: int) -> None:
        self.current_brightness_destination = destination
        self.current_brightness_percent = percent
        self.batch_write_queue = []
        self.batch_write_results = []
        self._reset_brightness_write_transaction()
        self.send_max_brightness()

    def start_blackout_preflight(self) -> None:
        targets = (
            sorted(self.control.sanlight_nodes)
            if self.args.destination is None
            else [self.args.destination]
        )
        self.blackout_targets = targets
        self.blackout_original_values = {}
        self.preflight_queue = list(targets)
        print(
            "Starting read-only blackout preflight. Current MaxBrightness values "
            "must be read before any 0% command is sent."
        )
        self._start_next_blackout_preflight_query()

    def _start_next_blackout_preflight_query(self) -> None:
        if not self.preflight_queue:
            changing_targets = [
                address
                for address in self.blackout_targets
                if self.blackout_original_values[address] != 0
            ]
            self.batch_write_results = [
                (address, 0)
                for address in self.blackout_targets
                if self.blackout_original_values[address] == 0
            ]
            if self.batch_write_results:
                already_off = ", ".join(
                    f"0x{address:04X}" for address, _ in self.batch_write_results
                )
                print(f"Already off; no 0% write needed for: {already_off}.")

            if not changing_targets:
                self.finish(
                    "BLACKOUT COMPLETE. Every selected node already reports 0% "
                    "(off); no write and no restore snapshot were created."
                )
                return

            entries = [
                BlackoutEntry(
                    address=address,
                    name=self.control.sanlight_nodes[address],
                    percent=self.blackout_original_values[address],
                )
                for address in changing_targets
            ]
            snapshot = create_blackout_snapshot(
                state_dir=self.args.sender_state.parent,
                mesh_uuid=self.control.mesh_uuid,
                sender_uuid=self.sender.provisioner.uuid,
                sender_unicast=self.sender_unicast,
                entries=entries,
            )
            self.blackout_snapshot_path = snapshot.path
            print(
                f"Protected restore snapshot created at {snapshot.path}. "
                "It contains only nodes changed by this blackout, with their "
                "previous percentages; it contains no Mesh keys or tokens."
            )
            self.batch_write_queue = [(address, 0) for address in changing_targets]
            self.start_next_batch_brightness_write()
            return

        self.current_brightness_destination = self.preflight_queue.pop(0)
        self.start_get_max_readback("blackout-preflight")

    def _mark_restore_snapshot_completed(self) -> str | None:
        snapshot = self.args.restore_snapshot
        try:
            restored_at = mark_blackout_snapshot_restored(snapshot.path)
        except StateError as exc:
            self.fail(
                "Brightness values were restored, but the snapshot could not be "
                f"marked completed: {exc}"
            )
            return None
        print(
            f"Restore snapshot marked completed at {restored_at}. "
            "Future 'restore-blackout latest' calls will select the next active "
            "snapshot instead of replaying this one."
        )
        return restored_at

    def start_restore_preflight(self) -> None:
        snapshot = self.args.restore_snapshot
        self.restore_desired = {
            entry.address: entry.percent for entry in snapshot.entries
        }
        self.preflight_queue = [entry.address for entry in snapshot.entries]
        self.batch_write_queue = []
        self.batch_write_results = []
        print(
            f"Starting read-only restore preflight from {snapshot.path} "
            f"(created {snapshot.created_at})."
        )
        if snapshot.restored_at is not None:
            print(
                f"NOTE: this explicitly selected snapshot was previously marked "
                f"restored at {snapshot.restored_at}; applying it again is "
                "intentional and idempotent."
            )
        self._start_next_restore_preflight_query()

    def _start_next_restore_preflight_query(self) -> None:
        if not self.preflight_queue:
            if not self.batch_write_queue:
                if self._mark_restore_snapshot_completed() is None:
                    return
                self.finish(
                    "RESTORE-BLACKOUT COMPLETE. Every node already reports the "
                    "percentage stored in the snapshot; no brightness write was sent."
                )
                return
            self.start_next_batch_brightness_write()
            return
        self.current_brightness_destination = self.preflight_queue.pop(0)
        self.start_get_max_readback("restore-preflight")

    def start_next_batch_brightness_write(self) -> None:
        if self.finished:
            return
        if not self.batch_write_queue:
            summary = ", ".join(
                f"0x{address:04X}={percent}%"
                for address, percent in self.batch_write_results
            ) or "none"
            if self.args.command == "blackout":
                self.finish(
                    "BLACKOUT VERIFIED. All selected nodes report 0% (off). "
                    f"Verified nodes: {summary}. Restore snapshot: "
                    f"{self.blackout_snapshot_path}."
                )
            else:
                if self._mark_restore_snapshot_completed() is None:
                    return
                self.finish(
                    "RESTORE-BLACKOUT VERIFIED. Snapshot values were restored and "
                    f"read back successfully: {summary}."
                )
            return

        destination, percent = self.batch_write_queue.pop(0)
        self.current_brightness_destination = destination
        self.current_brightness_percent = percent
        self._reset_brightness_write_transaction()
        self.send_max_brightness()

    def send_max_brightness(self) -> None:
        if self.sender_node is None:
            self.fail("Canonical sender Node1 interface is unavailable")
            return
        destination = self.current_brightness_destination
        percent = self.current_brightness_percent
        if percent is None:
            self.fail("Brightness transaction has no requested percentage")
            return
        attempt = self.set_max_attempt + 1
        self.set_max_attempt = attempt
        generation = self.set_max_generation
        payload = build_blackout_pdu() if percent == 0 else build_set_max_brightness_pdu(percent)
        description = validate_destination(self.control, destination)
        mode = "Blackout/0%" if percent == 0 else "SetMaxBrightness"
        print(
            f"Sending {mode} {percent}% attempt "
            f"{attempt}/{self.set_max_max_attempts} to "
            f"0x{destination:04X} ({description}); PDU={payload.hex()}"
        )
        self.sender_node.Send(
            dbus.ObjectPath(SENDER_ELEMENT_PATH),
            dbus.UInt16(destination),
            dbus.UInt16(self.control.app_index),
            empty_options(),
            byte_array(payload),
            reply_handler=lambda current_generation=generation, current_attempt=attempt: self.on_set_max_send_accepted(
                current_generation, current_attempt
            ),
            error_handler=lambda error: self.fail(
                f"Canonical sender Node1.Send failed: {error}"
            ),
        )

    def on_set_max_send_accepted(self, generation: int, attempt: int) -> None:
        if self.finished or generation != self.set_max_generation:
            return
        if not self.brightness_write_recorded:
            destination_label = (
                "all"
                if self.args.command == "blackout" and self.args.destination is None
                else f"0x{self.current_brightness_destination:04X}"
            )
            record_brightness_write(
                self.args.brightness_write_rate_path,
                command=self.args.command,
                destination=destination_label,
            )
            self.brightness_write_recorded = True
        print(
            "Access message accepted for Mesh transmission "
            f"(attempt {attempt}/{self.set_max_max_attempts})."
        )
        self.timeout(
            SET_MAX_STATUS_TIMEOUT_SECONDS,
            lambda current_generation=generation, current_attempt=attempt: self.finish_or_retry_set_max(
                current_generation, current_attempt
            ),
        )

    def on_set_max_status(self, source: int) -> None:
        if self.finished:
            return
        self.set_max_status_sources.add(source)
        print(
            "Received matching SANlight SetMaxBrightness status "
            f"(vendor opcode 0x07) from 0x{source:04X}."
        )
        if self.current_brightness_destination in self.control.sanlight_nodes:
            self.start_get_max_readback("verification")

    def finish_or_retry_set_max(self, generation: int, attempt: int) -> None:
        if (
            self.finished
            or generation != self.set_max_generation
            or attempt != self.set_max_attempt
            or self.get_max_started
        ):
            return

        destination = self.current_brightness_destination
        if destination in self.control.groups:
            sources = ", ".join(
                f"0x{source:04X}" for source in sorted(self.set_max_status_sources)
            ) or "none"
            self.finish(
                "SET-MAX GROUP SEND COMPLETE. The group command was transmitted "
                f"once; matching status sources observed: {sources}. "
                "A group response cannot confirm that every member applied the value."
            )
            return

        if self.set_max_status_sources:
            self.start_get_max_readback("verification")
            return

        if self.set_max_attempt < self.set_max_max_attempts:
            print(
                "No matching SANlight 0x07 status after "
                f"{SET_MAX_STATUS_TIMEOUT_SECONDS} seconds. Retrying the same "
                f"idempotent value in {SET_MAX_RETRY_DELAY_SECONDS} second."
            )
            self.timeout(SET_MAX_RETRY_DELAY_SECONDS, self.retry_set_max)
            return

        print(
            "No matching SANlight 0x07 status was received after the bounded "
            "write attempts. Starting read-only GetMaxBrightness verification; "
            "the write may still have succeeded."
        )
        self.start_get_max_readback("verification")

    def retry_set_max(self) -> None:
        if self.finished or self.set_max_status_sources or self.get_max_started:
            return
        self.send_max_brightness()

    def start_get_max_readback(self, purpose: str | None = None) -> None:
        if self.finished or self.get_max_started:
            return
        if self.sender_node is None:
            self.fail("Canonical sender Node1 interface is unavailable")
            return
        if self.current_brightness_destination not in self.control.sanlight_nodes:
            self.fail("GetMaxBrightness requires a unicast lamp node")
            return

        self.get_max_generation += 1
        self.get_max_started = True
        self.get_max_purpose = purpose or (
            "query" if self.args.command == "get-max" else "verification"
        )
        self.get_max_attempt = 0
        self.get_max_status = None
        self.get_max_malformed_status_seen = False
        self.get_max_retry_pending = False

        if self.get_max_purpose == "verification":
            ack_text = (
                "matching 0x07 acknowledgement received"
                if self.set_max_status_sources
                else "no matching 0x07 acknowledgement received"
            )
            print(
                "Starting read-only GetMaxBrightness verification "
                f"({ack_text})."
            )
        elif self.get_max_purpose == "query":
            print("Starting read-only GetMaxBrightness query.")
        else:
            print(
                "Reading current MaxBrightness for "
                f"0x{self.current_brightness_destination:04X} "
                f"({self.get_max_purpose})."
            )

        self.send_get_max_brightness()

    def send_get_max_brightness(self) -> None:
        if self.finished:
            return
        if self.sender_node is None:
            self.fail("Canonical sender Node1 interface is unavailable")
            return

        self.get_max_attempt += 1
        attempt = self.get_max_attempt
        generation = self.get_max_generation
        payload = build_get_max_brightness_pdu()
        destination = self.current_brightness_destination
        description = validate_destination(self.control, destination)
        action = self.get_max_purpose.replace("-", " ")
        print(
            f"Sending read-only GetMaxBrightness {action} attempt "
            f"{attempt}/{GET_MAX_MAX_ATTEMPTS} to "
            f"0x{destination:04X} ({description}); PDU={payload.hex()}"
        )
        self.sender_node.Send(
            dbus.ObjectPath(SENDER_ELEMENT_PATH),
            dbus.UInt16(destination),
            dbus.UInt16(self.control.app_index),
            empty_options(),
            byte_array(payload),
            reply_handler=lambda current_generation=generation, current_attempt=attempt: self.on_get_max_send_accepted(
                current_generation, current_attempt
            ),
            error_handler=lambda error: self.fail(
                f"Canonical sender Node1.Send GetMaxBrightness failed: {error}"
            ),
        )

    def on_get_max_send_accepted(self, generation: int, attempt: int) -> None:
        if self.finished or generation != self.get_max_generation:
            return
        print(
            "GetMaxBrightness accepted for Mesh transmission "
            f"(attempt {attempt}/{GET_MAX_MAX_ATTEMPTS})."
        )
        self.timeout(
            GET_MAX_STATUS_TIMEOUT_SECONDS,
            lambda current_generation=generation, current_attempt=attempt: self.finish_or_retry_get_max(
                current_generation, current_attempt
            ),
        )

    @staticmethod
    def _reported_brightness_text(value: int) -> str:
        if value == 0:
            return "0% (off)"
        if 1 <= value <= 19:
            return f"{value}% (unexpected value below the supported on-range)"
        return f"{value}%"

    def on_get_max_status(self, source: int, value: int) -> None:
        if self.finished:
            return
        self.get_max_status = (source, value)
        value_text = self._reported_brightness_text(value)
        print(
            "Received matching SANlight GetMaxBrightness status "
            f"(vendor opcode 0x09) from 0x{source:04X}: {value_text}."
        )
        purpose = self.get_max_purpose

        if purpose == "query":
            self.finish(
                f"GET-MAX COMPLETE. Node 0x{source:04X} reports "
                f"MaxBrightness {value_text}."
            )
            return

        if purpose == "blackout-preflight":
            if 1 <= value <= 19:
                self.finish(
                    f"BLACKOUT ABORTED. Node 0x{source:04X} reports {value}%, "
                    "which this project cannot safely restore. No 0% command was sent.",
                    2,
                )
                return
            self.blackout_original_values[source] = value
            self._cancel_get_max_transaction()
            self._start_next_blackout_preflight_query()
            return

        if purpose == "restore-preflight":
            desired = self.restore_desired[source]
            if value == desired:
                print(
                    f"Node 0x{source:04X} already reports {value_text}; no restore "
                    "write is needed for this node."
                )
                self.batch_write_results.append((source, value))
            else:
                self.batch_write_queue.append((source, desired))
            self._cancel_get_max_transaction()
            self._start_next_restore_preflight_query()
            return

        requested = self.current_brightness_percent
        if value == requested:
            ack_text = (
                "matching 0x07 acknowledgement was also received"
                if self.set_max_status_sources
                else "0x07 acknowledgement was not observed"
            )
            if self.args.command == "set-max":
                self.finish(
                    f"SET-MAX VERIFIED. Node 0x{source:04X} reports "
                    f"MaxBrightness {value_text} as requested; {ack_text}."
                )
            else:
                self.batch_write_results.append((source, value))
                self._cancel_get_max_transaction()
                self.start_next_batch_brightness_write()
            return

        if self.get_max_attempt < GET_MAX_MAX_ATTEMPTS:
            print(
                f"Readback mismatch after attempt {self.get_max_attempt}/"
                f"{GET_MAX_MAX_ATTEMPTS}: requested {requested}%, "
                f"reported {value_text}. Retrying the read-only query in "
                f"{GET_MAX_RETRY_DELAY_SECONDS} second."
            )
            self.get_max_status = None
            self.schedule_get_max_retry()
            return

        self.finish(
            f"BRIGHTNESS VERIFICATION MISMATCH. Node 0x{source:04X} reports "
            f"MaxBrightness {value_text}, but {requested}% was requested.",
            MAX_BRIGHTNESS_MISMATCH_EXIT_CODE,
        )

    def finish_or_retry_get_max(self, generation: int, attempt: int) -> None:
        if (
            self.finished
            or generation != self.get_max_generation
            or attempt != self.get_max_attempt
        ):
            return
        if self.get_max_status is not None:
            return

        if self.get_max_attempt < GET_MAX_MAX_ATTEMPTS:
            detail = (
                " A malformed matching status was observed and ignored."
                if self.get_max_malformed_status_seen
                else ""
            )
            print(
                "No valid matching SANlight 0x09 status after "
                f"{GET_MAX_STATUS_TIMEOUT_SECONDS} seconds.{detail} "
                f"Retrying the read-only query in "
                f"{GET_MAX_RETRY_DELAY_SECONDS} second."
            )
            self.schedule_get_max_retry()
            return

        malformed_text = (
            " At least one malformed matching 0x09 status was ignored."
            if self.get_max_malformed_status_seen
            else ""
        )
        if self.get_max_purpose == "query":
            self.finish(
                "GET-MAX UNCONFIRMED. BlueZ accepted the read-only query, but "
                f"no valid matching 0x09 status was received after "
                f"{GET_MAX_MAX_ATTEMPTS} attempts.{malformed_text}",
                MAX_BRIGHTNESS_UNCONFIRMED_EXIT_CODE,
            )
            return

        if self.get_max_purpose in ("blackout-preflight", "restore-preflight"):
            self.finish(
                f"{self.args.command.upper()} ABORTED. A current MaxBrightness "
                "value could not be read safely; no further brightness write was "
                f"started.{malformed_text}",
                MAX_BRIGHTNESS_UNCONFIRMED_EXIT_CODE,
            )
            return

        ack_text = (
            "A matching 0x07 acknowledgement was received, but "
            if self.set_max_status_sources
            else "No matching 0x07 acknowledgement was received, and "
        )
        self.finish(
            f"BRIGHTNESS WRITE UNVERIFIED. {ack_text}no valid GetMaxBrightness "
            f"readback was received after {GET_MAX_MAX_ATTEMPTS} attempts."
            f"{malformed_text} Reconnect the SANlight app to verify the value.",
            MAX_BRIGHTNESS_UNCONFIRMED_EXIT_CODE,
        )

    def schedule_get_max_retry(self) -> None:
        if self.finished or self.get_max_retry_pending:
            return
        self.get_max_retry_pending = True
        self.timeout(GET_MAX_RETRY_DELAY_SECONDS, self.retry_get_max)

    def retry_get_max(self) -> None:
        if self.finished:
            return
        self.get_max_retry_pending = False
        self.get_max_status = None
        self.send_get_max_brightness()

    def start_leave_sender(self) -> None:
        state = self.load_sender_state()
        if state is None:
            raise BluezRuntimeError("No canonical sender state found; nothing to leave")
        token = token_from_state(state, "Canonical sender")
        if token is None:
            raise BluezRuntimeError("Canonical sender state has no token")
        print(
            f"Removing only canonical sender 0x{self.sender_unicast:04X}; "
            "control provisioner and lamp nodes remain untouched."
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
            self.fail(f"Sender left BlueZ, but state file deletion failed: {exc}")
            return
        self.finish("Canonical sender removed locally; sender state deleted.")
