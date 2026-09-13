"""Brain service entry point — MQTT consumer mode.

Second consumer mode for the NATS-vs-MQTT protocol comparison
(plan-detailed.md L2: "Brain service has two consumer modes"). Runs the
exact same per-signal (Approach A) + composite NEWS2 (Approach C) scoring
as `brain/main.py`'s NATS consumer — only the transport differs.

MQTT topics use the bounded `vitals/{patient_id}/{signal_type}` hierarchy.
QoS 1 messages are manually acknowledged only after a durable local outbox
handoff, or after a malformed payload has received a confirmed publish to the
separate `dlq/vitals/mqtt` topic.
"""

import asyncio
import copy
import json
import logging
import signal
import sys
from pathlib import Path

import paho.mqtt.client as mqtt

from brain.approaches import APPROACH_B, APPROACH_C, BatchScheduler, score_composite
from brain.evaluator import evaluate_message
from brain.ews_window import PatientEWSState
from brain.influx_writer import AlarmRecord, InfluxWriter, VitalRecord
from brain.validation import ValidationError, dead_letter, decode_and_validate
from config.settings import PIPELINE_VERSION
from config.thresholds import NEWS2_THRESHOLD_VERSION, get_threshold_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).parent.parent / "data" / "profiles"


def _load_profiles() -> dict[str, dict]:
    mapping = {}
    for path in sorted(PROFILES_DIR.glob("P-*.json")):
        p = json.loads(path.read_text())
        mapping[p["patient_id"]] = p
    if not mapping:
        log.error("No patient profiles found in %s", PROFILES_DIR)
        sys.exit(1)
    return mapping


async def main(host: str = "localhost", port: int = 1883) -> None:
    profiles = _load_profiles()
    ews_states: dict[str, PatientEWSState] = {}
    batch_scheduler = BatchScheduler()

    writer = InfluxWriter()
    await writer.start()

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _on_message(client, userdata, msg) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (msg.topic, msg.payload, msg.mid, msg.qos))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, manual_ack=True)
    client.on_message = _on_message
    client.connect(host, port)
    client.subscribe("vitals/#", qos=1)
    client.loop_start()

    stop_event = asyncio.Event()

    def _handle_signal(*_):
        log.info("Shutdown signal — draining MQTT brain service.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    log.info("MQTT brain service running (approaches A/B/C) on configured endpoint. Waiting for vitals…")
    processed = 0

    async def _drain_queue():
        nonlocal processed
        while not stop_event.is_set():
            try:
                topic, raw, message_id, qos = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            async def reject(error: ValidationError) -> None:
                info = client.publish(
                    "dlq/vitals/mqtt",
                    dead_letter(raw, error, topic, pipeline_version=PIPELINE_VERSION),
                    qos=1,
                )
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise RuntimeError(f"MQTT DLQ enqueue failed with result {info.rc}")
                await asyncio.to_thread(info.wait_for_publish, 5.0)
                if not info.is_published():
                    raise TimeoutError("MQTT DLQ PUBACK was not received before timeout")

            await _process(
                raw,
                profiles,
                ews_states,
                batch_scheduler,
                writer,
                source_subject=topic.replace("/", "."),
                reject_handler=reject,
            )
            # With QoS 1/manual acknowledgements, broker success follows the
            # same durable local handoff used by NATS.
            ack_result = client.ack(message_id, qos)
            if ack_result != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT acknowledgement failed with result {ack_result}")
            processed += 1

    await _drain_queue()

    log.info("Processed %d MQTT messages total. Shutting down.", processed)
    client.loop_stop()
    client.disconnect()
    await writer.stop()
    log.info("Done.")


async def _process(
    raw: bytes,
    profiles: dict[str, dict],
    ews_states: dict[str, PatientEWSState],
    batch_scheduler: BatchScheduler,
    writer: InfluxWriter,
    source_subject: str | None = None,
    reject_handler=None,
) -> None:
    try:
        vital = decode_and_validate(raw, profiles, source_subject=source_subject)
    except ValidationError as exc:
        log.warning("Rejected MQTT vital: %s", exc)
        if reject_handler is None:
            raise
        await reject_handler(exc)
        return

    patient_id, signal_type, value, timestamp = (
        vital.patient_id, vital.signal_type, vital.value, vital.timestamp_ms
    )
    scenario_id = vital.scenario_id
    profile     = profiles.get(patient_id, {})
    condition   = profile.get("condition", "unknown")
    spo2_scale  = int(profile.get("news2_spo2_scale", 1))

    threshold_snapshot = get_threshold_snapshot()
    records: list[VitalRecord | AlarmRecord] = []
    previous_state = copy.deepcopy(ews_states.get(patient_id))
    previous_tick = batch_scheduler._last_tick.get(patient_id)
    for sig, float_val, level in evaluate_message(signal_type, value, threshold_snapshot):
        if level != "ok":
            log.info("MQTT Approach A alarm: signal=%s level=%s scenario=%s",
                     sig, level.upper(), scenario_id)
        records.append(VitalRecord(
            patient_id=patient_id, signal_type=sig, condition=condition,
            alarm_level=level, value=float_val, timestamp_ms=timestamp,
            scoring_approach="A", scenario_id=scenario_id,
            schema_version=vital.schema_version, pipeline_version=vital.pipeline_version,
            threshold_version=threshold_snapshot.version, transport="mqtt",
        ))

    state = ews_states.setdefault(patient_id, PatientEWSState(patient_id, spo2_scale=spo2_scale))
    if signal_type == "blood_pressure" and isinstance(value, dict):
        state.update("systolic_bp", float(value["systolic"]), timestamp)
    elif signal_type in ("respiratory_rate", "spo2", "heart_rate", "temperature"):
        state.update(signal_type, float(value), timestamp)

    scored_c = score_composite(state, timestamp, APPROACH_C)
    if scored_c is not None:
        records.append(AlarmRecord(
            patient_id=patient_id, condition=condition, alarm_level=scored_c.alarm_level,
            scoring_approach=APPROACH_C, news2_score=scored_c.news2_score,
            scenario_id=scenario_id, timestamp_ms=timestamp,
            schema_version=vital.schema_version, pipeline_version=vital.pipeline_version,
            threshold_version=NEWS2_THRESHOLD_VERSION, transport="mqtt",
            window_complete=scored_c.window_complete,
        ))

    if batch_scheduler.due(patient_id, timestamp):
        scored_b = score_composite(state, timestamp, APPROACH_B)
        if scored_b is not None:
            records.append(AlarmRecord(
                patient_id=patient_id, condition=condition, alarm_level=scored_b.alarm_level,
                scoring_approach=APPROACH_B, news2_score=scored_b.news2_score,
                scenario_id=scenario_id, timestamp_ms=timestamp,
                schema_version=vital.schema_version, pipeline_version=vital.pipeline_version,
                threshold_version=NEWS2_THRESHOLD_VERSION, transport="mqtt",
                window_complete=scored_b.window_complete,
            ))

    try:
        await _durable_handoff(writer, records)
    except Exception:
        if previous_state is None:
            ews_states.pop(patient_id, None)
        else:
            ews_states[patient_id] = previous_state
        if previous_tick is None:
            batch_scheduler._last_tick.pop(patient_id, None)
        else:
            batch_scheduler._last_tick[patient_id] = previous_tick
        raise


async def _durable_handoff(writer: InfluxWriter, records: list[VitalRecord | AlarmRecord]) -> None:
    enqueue_many = getattr(writer, "enqueue_many", None)
    if enqueue_many is not None:
        await enqueue_many(records)
        return
    for record in records:
        await writer.enqueue(record)


if __name__ == "__main__":
    asyncio.run(main())
