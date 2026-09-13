"""MQTT publisher used to dual-publish the same vital-sign stream that goes
to NATS, for the NATS-vs-MQTT protocol comparison (plan-detailed.md L2).

paho-mqtt is callback/thread based, not asyncio-native — `loop_start()` runs
its network loop on a background thread; `publish()` itself is a fast
non-blocking enqueue, safe to call from the asyncio event loop directly.
"""

import logging

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(self, host: str = "localhost", port: int = 1883, client_id: str | None = None,
                 qos: int = 1) -> None:
        self.qos = qos
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self._client.on_disconnect = self._on_disconnect
        self._client.connect(host, port)
        self._client.loop_start()

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None) -> None:
        if reason_code != 0:
            log.warning("MQTT disconnected unexpectedly: %s", reason_code)

    def publish(self, topic: str, payload: bytes, *, timeout: float = 5.0) -> None:
        info = self._client.publish(topic, payload, qos=self.qos)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish enqueue failed: rc={info.rc}")
        info.wait_for_publish(timeout=timeout)
        if not info.is_published():
            raise TimeoutError("MQTT PUBACK was not received before timeout")

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
