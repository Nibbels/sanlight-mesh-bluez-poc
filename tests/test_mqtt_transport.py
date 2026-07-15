import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from sanlight_mesh.gateway_config import GatewayConfig, MqttConfig
from sanlight_mesh.mqtt_transport import IncomingMessage, PahoMqttTransport


class FakePublishInfo:
    rc = 0


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.will = None
        self.subscriptions = []
        self.published = []
        self.credentials = None
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None

    def username_pw_set(self, username, password):
        self.credentials = (username, password)

    def tls_set(self, **kwargs):
        self.tls = kwargs

    def will_set(self, topic, payload, qos, retain):
        self.will = (topic, payload, qos, retain)

    def reconnect_delay_set(self, min_delay, max_delay):
        self.reconnect_delay = (min_delay, max_delay)

    def subscribe(self, topic, qos=0, options=None):
        self.subscriptions.append((topic, qos, options))
        return (0, 1)

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))
        return FakePublishInfo()

    def disconnect(self):
        pass


class FakeSubscribeOptions:
    RETAIN_SEND_ON_SUBSCRIBE = 0
    RETAIN_SEND_IF_NEW_SUB = 1
    RETAIN_DO_NOT_SEND = 2

    def __init__(
        self,
        qos=0,
        noLocal=False,
        retainAsPublished=False,
        retainHandling=RETAIN_SEND_ON_SUBSCRIBE,
    ):
        self.QoS = qos
        self.noLocal = noLocal
        self.retainAsPublished = retainAsPublished
        self.retainHandling = retainHandling


class FakeClientFactory:
    instances = []

    def __new__(cls, **kwargs):
        instance = FakeClient(**kwargs)
        cls.instances.append(instance)
        return instance


class MqttTransportTest(unittest.TestCase):
    def config(self):
        return GatewayConfig(
            config_path=Path("/tmp/config"),
            project_root=Path("/tmp/project"),
            gateway_id="test-pi",
            cdb_path=Path("/tmp/cdb"),
            control_app_id=1,
            sender_app_id=2,
            state_dir=Path("/tmp/state"),
            command_timeout_seconds=45,
            queue_max_size=10,
            dedup_ttl_seconds=3600,
            dedup_max_entries=32,
            coalesce_window_seconds=2,
            state_fresh_seconds=0,
            refresh_on_start=False,
            refresh_interval_seconds=0,
            topic_prefix="sanlightmesh/v1",
            mqtt=MqttConfig("broker", 1883, "client", None, None, 60, 1, False, None),
        )

    def fake_modules(self):
        client_module = types.ModuleType("paho.mqtt.client")
        client_module.Client = FakeClientFactory
        client_module.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
        client_module.MQTTv5 = 5
        subscribeoptions_module = types.ModuleType("paho.mqtt.subscribeoptions")
        subscribeoptions_module.SubscribeOptions = FakeSubscribeOptions
        mqtt_module = types.ModuleType("paho.mqtt")
        mqtt_module.client = client_module
        paho_module = types.ModuleType("paho")
        paho_module.mqtt = mqtt_module
        return {
            "paho": paho_module,
            "paho.mqtt": mqtt_module,
            "paho.mqtt.client": client_module,
            "paho.mqtt.subscribeoptions": subscribeoptions_module,
        }

    def test_will_subscription_and_non_retained_result(self):
        FakeClientFactory.instances.clear()
        connected = []
        incoming = []
        with patch.dict(sys.modules, self.fake_modules()):
            transport = PahoMqttTransport(
                self.config(),
                on_message=incoming.append,
                on_connected=lambda: connected.append(True),
                on_disconnected=lambda reason: None,
            )
        client = FakeClientFactory.instances[-1]
        self.assertNotIn("clean_session", client.kwargs)
        self.assertEqual(client.kwargs["protocol"], 5)
        self.assertEqual(
            client.will,
            ("sanlightmesh/v1/test-pi/availability", "offline", 1, True),
        )
        transport._on_connect(client, None, None, 0)
        self.assertEqual(len(client.subscriptions), 1)
        topic, qos, options = client.subscriptions[0]
        self.assertEqual(topic, "sanlightmesh/v1/test-pi/command")
        self.assertEqual(qos, 0)
        self.assertEqual(options.QoS, 1)
        self.assertFalse(options.noLocal)
        self.assertTrue(options.retainAsPublished)
        self.assertEqual(options.retainHandling, FakeSubscribeOptions.RETAIN_DO_NOT_SEND)
        self.assertEqual(connected, [True])

        transport.publish_json("sanlightmesh/v1/test-pi/result/x", {"ok": True})
        self.assertFalse(client.published[-1][3])

        message = types.SimpleNamespace(topic="t", payload=b"{}", qos=1, retain=False)
        transport._on_message(client, None, message)
        self.assertEqual(incoming[-1], IncomingMessage("t", b"{}", 1, False))

        retained = types.SimpleNamespace(topic="t", payload=b"{}", qos=1, retain=True)
        transport._on_message(client, None, retained)
        self.assertEqual(incoming[-1], IncomingMessage("t", b"{}", 1, True))
