"""Broker-free acknowledgement and rejection tests for optional MQTT transport."""

import paho.mqtt.client as mqtt
import pytest

from brain.approaches import BatchScheduler
from brain.mqtt_consumer import _handle_delivery
from producer.mqtt_producer import MqttPublisher
from schema import vitals_pb2


class PublishInfo:
    def __init__(self, *, rc=mqtt.MQTT_ERR_SUCCESS, published=True):
        self.rc = rc
        self.published = published
        self.waits = []

    def wait_for_publish(self, timeout=None):
        self.waits.append(timeout)

    def is_published(self):
        return self.published


class Client:
    def __init__(self, info):
        self.info = info
        self.calls = []
        self.on_disconnect = None

    def connect(self, host, port):
        self.calls.append(("connect", host, port))

    def loop_start(self):
        self.calls.append(("loop_start",))

    def publish(self, topic, payload, qos):
        self.calls.append(("publish", topic, payload, qos))
        return self.info

    def ack(self, message_id, qos):
        self.calls.append(("ack", message_id, qos))
        return mqtt.MQTT_ERR_SUCCESS


def test_mqtt_publish_waits_for_puback(monkeypatch):
    info = PublishInfo()
    client = Client(info)
    monkeypatch.setattr(mqtt, "Client", lambda *args, **kwargs: client)

    publisher = MqttPublisher(qos=1)
    publisher.publish("vitals/P-001/heart_rate", b"payload", timeout=2.0)

    assert ("publish", "vitals/P-001/heart_rate", b"payload", 1) in client.calls
    assert info.waits == [2.0]


def test_mqtt_publish_fails_without_puback(monkeypatch):
    client = Client(PublishInfo(published=False))
    monkeypatch.setattr(mqtt, "Client", lambda *args, **kwargs: client)

    publisher = MqttPublisher()
    with pytest.raises(TimeoutError, match="PUBACK"):
        publisher.publish("vitals/P-001/heart_rate", b"payload")


@pytest.mark.asyncio
async def test_invalid_mqtt_payload_is_dlq_confirmed_before_source_ack():
    info = PublishInfo()
    client = Client(info)

    await _handle_delivery(
        client,
        "vitals/P-001/heart_rate",
        b"not-protobuf",
        17,
        1,
        {"P-001": {"condition": "synthetic"}},
        {},
        BatchScheduler(),
        object(),
    )

    operations = [call[0] for call in client.calls]
    assert operations == ["publish", "ack"]
    assert client.calls[0][1] == "dlq/vitals/mqtt"
    assert info.waits == [5.0]
    envelope = vitals_pb2.DeadLetterEnvelope.FromString(client.calls[0][2])
    assert envelope.source_transport == "mqtt"
    assert envelope.source_topic == "vitals/P-001/heart_rate"


@pytest.mark.asyncio
async def test_mqtt_dlq_failure_prevents_source_ack():
    client = Client(PublishInfo(published=False))

    with pytest.raises(TimeoutError, match="DLQ PUBACK"):
        await _handle_delivery(
            client,
            "vitals/P-001/heart_rate",
            b"not-protobuf",
            17,
            1,
            {"P-001": {"condition": "synthetic"}},
            {},
            BatchScheduler(),
            object(),
        )

    assert all(call[0] != "ack" for call in client.calls)
