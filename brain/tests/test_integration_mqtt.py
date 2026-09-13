"""Optional live MQTT QoS/DLQ integration test against local Mosquitto."""

import asyncio
import os
import queue
import threading
from uuid import uuid4

import paho.mqtt.client as mqtt
import pytest

from brain.approaches import BatchScheduler
from brain.mqtt_consumer import _handle_delivery
from producer.mqtt_producer import MqttPublisher
from schema import vitals_pb2


def _skip_or_fail(message):
    if os.getenv("REQUIRE_MQTT_INTEGRATION", "false").lower() == "true":
        pytest.fail(message)
    pytest.skip(message)


def _subscriber(topic, messages):
    connected = threading.Event()
    subscribed = threading.Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, manual_ack=True)

    def on_connect(current, _userdata, _flags, reason_code, _properties):
        if reason_code == 0:
            connected.set()
            current.subscribe(topic, qos=1)

    def on_subscribe(_current, _userdata, _mid, _reason_codes, _properties):
        subscribed.set()

    def on_message(_current, _userdata, message):
        messages.put(message)

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    client.connect("127.0.0.1", 1883)
    client.loop_start()
    if not connected.wait(5) or not subscribed.wait(5):
        client.loop_stop()
        client.disconnect()
        raise TimeoutError(f"MQTT subscription was not ready for {topic}")
    return client


def test_live_mqtt_invalid_payload_is_dlq_confirmed_before_source_ack():
    suffix = uuid4().hex[:12]
    source_topic = f"vitals/P-MQTT-{suffix}/heart_rate"
    source_messages, dlq_messages = queue.Queue(), queue.Queue()
    source_client = dlq_client = publisher = None
    try:
        try:
            source_client = _subscriber(source_topic, source_messages)
            dlq_client = _subscriber("dlq/vitals/mqtt", dlq_messages)
            publisher = MqttPublisher(host="127.0.0.1", port=1883, qos=1)
        except Exception as error:
            _skip_or_fail(f"MQTT not reachable for required integration test: {error}")

        publisher.publish(source_topic, b"not-protobuf", timeout=5)
        incoming = source_messages.get(timeout=5)
        asyncio.run(
            _handle_delivery(
                source_client,
                incoming.topic,
                incoming.payload,
                incoming.mid,
                incoming.qos,
                {"P-001": {"condition": "synthetic"}},
                {},
                BatchScheduler(),
                object(),
            )
        )
        rejected = dlq_messages.get(timeout=5)
        envelope = vitals_pb2.DeadLetterEnvelope()
        envelope.ParseFromString(rejected.payload)
        assert envelope.original_payload == b"not-protobuf"
        assert envelope.source_subject == source_topic
        dlq_client.ack(rejected.mid, rejected.qos)
    except queue.Empty:
        pytest.fail("MQTT delivery or DLQ PUBACK path timed out")
    finally:
        if publisher is not None:
            publisher.close()
        for client in (source_client, dlq_client):
            if client is not None:
                client.loop_stop()
                client.disconnect()
