"""Small Paho MQTT transport with retained availability and strict topic use."""
from __future__ import annotations

import json
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .gateway_config import GatewayConfig


class MqttTransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class IncomingMessage:
    topic: str
    payload: bytes
    qos: int
    retain: bool


class PahoMqttTransport:
    def __init__(
        self,
        config: GatewayConfig,
        *,
        on_message: Callable[[IncomingMessage], None],
        on_connected: Callable[[], None],
        on_disconnected: Callable[[str], None],
    ) -> None:
        try:
            import paho.mqtt.client as mqtt
            from paho.mqtt.subscribeoptions import SubscribeOptions
        except ImportError as exc:
            raise MqttTransportError(
                "python3-paho-mqtt is missing; run scripts/install-mqtt-gateway.sh"
            ) from exc
        self.mqtt_module = mqtt
        self.subscribe_options_class = SubscribeOptions
        self.config = config
        self._on_message_callback = on_message
        self._on_connected_callback = on_connected
        self._on_disconnected_callback = on_disconnected
        self.client = self._create_client()

    def _create_client(self) -> Any:
        mqtt = self.mqtt_module
        try:
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self.config.mqtt.client_id,
                protocol=mqtt.MQTTv5,
            )
        except (AttributeError, TypeError) as exc:
            raise MqttTransportError(
                "paho-mqtt 2.x with MQTT 5 support is required for safe "
                "retained-command detection"
            ) from exc
        if self.config.mqtt.username is not None:
            password: str | None = None
            if self.config.mqtt.password_file is not None:
                try:
                    password = self.config.mqtt.password_file.read_text(
                        encoding="utf-8"
                    ).rstrip("\r\n")
                except OSError as exc:
                    raise MqttTransportError(
                        f"cannot read MQTT password file: {exc}"
                    ) from exc
                if not password:
                    raise MqttTransportError("MQTT password file is empty")
            client.username_pw_set(self.config.mqtt.username, password)
        if self.config.mqtt.tls:
            client.tls_set(
                ca_certs=(
                    str(self.config.mqtt.ca_cert)
                    if self.config.mqtt.ca_cert is not None
                    else None
                ),
                cert_reqs=ssl.CERT_REQUIRED,
            )
        client.will_set(
            f"{self.config.topic_root}/availability",
            payload="offline",
            qos=self.config.mqtt.qos,
            retain=True,
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        try:
            client.reconnect_delay_set(min_delay=1, max_delay=60)
        except AttributeError:
            pass
        return client

    @staticmethod
    def _reason_success(reason_code: Any) -> bool:
        try:
            return int(reason_code) == 0
        except (TypeError, ValueError):
            return str(reason_code).lower() in {"success", "0"}

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, *extra: Any) -> None:
        if not self._reason_success(reason_code):
            print(f"MQTT connection rejected: {reason_code}", file=sys.stderr)
            return
        options = self.subscribe_options_class(
            qos=self.config.mqtt.qos,
            noLocal=False,
            retainAsPublished=True,
            retainHandling=self.subscribe_options_class.RETAIN_DO_NOT_SEND,
        )
        result, _mid = client.subscribe(
            self.config.command_topic,
            options=options,
        )
        if int(result) != 0:
            print(
                f"MQTT command subscription failed: rc={result}",
                file=sys.stderr,
            )
            return
        self._on_connected_callback()

    def _on_disconnect(self, client: Any, userdata: Any, *args: Any) -> None:
        reason = str(args[-2] if len(args) >= 2 else args[-1] if args else "unknown")
        self._on_disconnected_callback(reason)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        self._on_message_callback(
            IncomingMessage(
                topic=str(message.topic),
                payload=bytes(message.payload),
                qos=int(message.qos),
                retain=bool(message.retain),
            )
        )

    def publish_json(
        self,
        topic: str,
        payload: Mapping[str, Any],
        *,
        retain: bool = False,
    ) -> None:
        encoded = json.dumps(
            dict(payload), separators=(",", ":"), sort_keys=True, ensure_ascii=False
        )
        info = self.client.publish(
            topic,
            payload=encoded,
            qos=self.config.mqtt.qos,
            retain=retain,
        )
        if getattr(info, "rc", 0) != 0:
            raise MqttTransportError(f"MQTT publish failed for {topic}: rc={info.rc}")

    def publish_text(self, topic: str, payload: str, *, retain: bool = False) -> None:
        info = self.client.publish(
            topic,
            payload=payload,
            qos=self.config.mqtt.qos,
            retain=retain,
        )
        if getattr(info, "rc", 0) != 0:
            raise MqttTransportError(f"MQTT publish failed for {topic}: rc={info.rc}")

    def run_forever(self) -> None:
        try:
            self.client.connect_async(
                self.config.mqtt.host,
                self.config.mqtt.port,
                self.config.mqtt.keepalive_seconds,
            )
            self.client.loop_forever(retry_first_connection=True)
        except TypeError:
            self.client.connect(
                self.config.mqtt.host,
                self.config.mqtt.port,
                self.config.mqtt.keepalive_seconds,
            )
            self.client.loop_forever()

    def disconnect(self) -> None:
        try:
            self.publish_text(
                f"{self.config.topic_root}/availability", "offline", retain=True
            )
        finally:
            self.client.disconnect()
