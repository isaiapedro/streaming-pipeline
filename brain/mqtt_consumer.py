"""Brain service entry point — MQTT consumer mode.

Second consumer mode for the NATS-vs-MQTT protocol comparison
(plan-detailed.md L2: "Brain service has two consumer modes"). Runs the
exact same per-signal (Approach A) + composite NEWS2 (Approach C) scoring
as `brain/main.py`'s NATS consumer — only the transport differs.

Topic note: the producer publishes using the same literal string as the
NATS subject (`vitals.{patient_id}.{signal_type}`, dot-separated) rather
than translating it to MQTT's `/`-delimited hierarchy, so a topic-level
wildcard subscribe (`vitals.+`) would not match — MQTT's `+`/`#` operate on
`/` boundaries, and there are none in this topic string. This consumer
subscribes to `#` (everything on the broker) instead. Acceptable for this
closed single-purpose demo broker; a real MQTT deployment would use
`vitals/{patient_id}/{signal_type}` topics and a proper `vitals/#` filter —
noted here rather than silently done, since it's a real difference from
the NATS subject convention.
"""

import asyncio
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
        loop.call_soon_threadsafe(queue.put_nowait, msg.payload)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = _on_message
    client.connect(host, port)
    client.subscribe("#")  # see module docstring — topic isn't `/`-hierarchical
    client.loop_start()

    stop_event = asyncio.Event()

    def _handle_signal(*_):
        log.info("Shutdown signal — draining MQTT brain service.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    log.info("MQTT brain service running (approaches A/B/C) on %s:%d. Waiting for vitals…", host, port)
    processed = 0

    async def _drain_queue():
        nonlocal processed
        while not stop_event.is_set():
            try:
                raw = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            await _process(raw, profiles, ews_states, batch_scheduler, writer)
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
) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("Bad JSON on MQTT: %s", exc)
        return

    patient_id  = data.get("patient_id", "unknown")
    signal_type = data.get("signal_type", "unknown")
    value       = data.get("value")
    timestamp   = data.get("timestamp", 0)
    scenario_id = data.get("scenario_id") or "none"
    profile     = profiles.get(patient_id, {})
    condition   = profile.get("condition", "unknown")
    copd_flag   = bool(profile.get("copd_flag", False))

    for sig, float_val, level in evaluate_message(signal_type, value):
        if level != "ok":
            log.info("[%s][A/mqtt] %s=%s → %s", patient_id, sig, float_val, level.upper())
        await writer.enqueue(VitalRecord(
            patient_id=patient_id, signal_type=sig, condition=condition,
            alarm_level=level, value=float_val, timestamp_ms=timestamp,
            scoring_approach="A", scenario_id=scenario_id,
        ))

    state = ews_states.setdefault(patient_id, PatientEWSState(patient_id, copd_flag=copd_flag))
    if signal_type == "blood_pressure" and isinstance(value, dict):
        state.update("systolic_bp", float(value["systolic"]), timestamp)
    elif signal_type in ("respiratory_rate", "spo2", "heart_rate", "temperature"):
        state.update(signal_type, float(value), timestamp)

    scored_c = score_composite(state, timestamp, APPROACH_C)
    if scored_c is not None:
        await writer.enqueue(AlarmRecord(
            patient_id=patient_id, condition=condition, alarm_level=scored_c.alarm_level,
            scoring_approach=APPROACH_C, news2_score=scored_c.news2_score,
            scenario_id=scenario_id, timestamp_ms=timestamp,
        ))

    if batch_scheduler.due(patient_id, timestamp):
        scored_b = score_composite(state, timestamp, APPROACH_B)
        if scored_b is not None:
            await writer.enqueue(AlarmRecord(
                patient_id=patient_id, condition=condition, alarm_level=scored_b.alarm_level,
                scoring_approach=APPROACH_B, news2_score=scored_b.news2_score,
                scenario_id=scenario_id, timestamp_ms=timestamp,
            ))


if __name__ == "__main__":
    asyncio.run(main())
