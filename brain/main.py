"""Brain service entry point.

Subscribes to all vitals subjects on NATS JetStream and runs all three
scoring approaches (A/B/C — see brain/approaches.py) per message, writing
batched records to InfluxDB Cloud tagged by `scoring_approach` so Grafana
can compare them side by side.
"""

import asyncio
import copy
import json
import logging
import signal
import sys
from pathlib import Path

import nats
from nats.errors import TimeoutError as NatsTimeout

from config.settings import NATS_URL, nats_connection_options
from config.nats_consumers import BRAIN_CONSUMER, assert_server_consumer
from brain.approaches import APPROACH_B, APPROACH_C, BatchScheduler, score_composite
from brain.config_watcher import watch_thresholds
from brain.evaluator import evaluate_message
from brain.ews_window import PatientEWSState
from brain.influx_writer import InfluxWriter, VitalRecord, AlarmRecord
from brain.validation import (
    DLQ_SUBJECT,
    ValidationError,
    dead_letter,
    dead_letter_message_id,
    decode_and_validate,
)
from config.settings import PIPELINE_VERSION
from config.thresholds import NEWS2_THRESHOLD_VERSION, get_threshold_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).parent.parent / "data" / "profiles"
_PULL_BATCH   = 50
_PULL_TIMEOUT = 1.0   # seconds


def _load_profiles() -> dict[str, dict]:
    """Returns {patient_id: profile_dict} from all profile JSONs."""
    mapping = {}
    for path in sorted(PROFILES_DIR.glob("P-*.json")):
        p = json.loads(path.read_text())
        mapping[p["patient_id"]] = p
    if not mapping:
        log.error("No patient profiles found in %s", PROFILES_DIR)
        sys.exit(1)
    log.info("Loaded %d synthetic patient profiles", len(mapping))
    return mapping


async def _process(
    msg,
    profiles: dict[str, dict],
    ews_states: dict[str, PatientEWSState],
    batch_scheduler: BatchScheduler,
    writer: InfluxWriter,
    js,
) -> None:
    try:
        vital = decode_and_validate(msg.data, profiles, source_subject=msg.subject)
    except ValidationError as exc:
        log.warning("Rejected NATS vital: %s", exc)
        await js.publish(
            DLQ_SUBJECT,
            dead_letter(msg.data, exc, msg.subject, pipeline_version=PIPELINE_VERSION),
            headers={"Nats-Msg-Id": dead_letter_message_id(msg.data, msg.subject)},
        )
        await msg.ack_sync()
        return

    patient_id, signal_type, value, timestamp = (
        vital.patient_id, vital.signal_type, vital.value, vital.timestamp_ms
    )
    scenario_id = vital.scenario_id
    profile        = profiles.get(patient_id, {})
    condition      = profile.get("condition", "unknown")
    spo2_scale     = int(profile.get("news2_spo2_scale", 1))

    # Capture values and version together. A concurrent hot reload can only
    # affect the next message, never the label on this decision.
    threshold_snapshot = get_threshold_snapshot()
    records: list[VitalRecord | AlarmRecord] = []
    previous_state = copy.deepcopy(ews_states.get(patient_id))
    previous_tick = batch_scheduler._last_tick.get(patient_id)

    # --- Approach A: per-signal threshold (existing behavior, tagged "A") ---
    for sig, float_val, level in evaluate_message(signal_type, value, threshold_snapshot):
        if level != "ok":
            log.info("Approach A alarm: signal=%s level=%s scenario=%s",
                     sig, level.upper(), scenario_id)
        records.append(VitalRecord(
            patient_id=patient_id, signal_type=sig, condition=condition,
            alarm_level=level, value=float_val, timestamp_ms=timestamp,
            scoring_approach="A", scenario_id=scenario_id,
            schema_version=vital.schema_version, pipeline_version=vital.pipeline_version,
            threshold_version=threshold_snapshot.version, transport="nats",
        ))

    # --- Update shared EWS window state (backs both B and C) ---
    state = ews_states.setdefault(patient_id, PatientEWSState(patient_id, spo2_scale=spo2_scale))
    if signal_type == "blood_pressure" and isinstance(value, dict):
        state.update("systolic_bp", float(value["systolic"]), timestamp)
    elif signal_type in ("respiratory_rate", "spo2", "heart_rate", "temperature"):
        state.update(signal_type, float(value), timestamp)

    # --- Approach C: streaming composite EWS, re-scored on every message ---
    scored_c = score_composite(state, timestamp, APPROACH_C)
    if scored_c is not None:
        if scored_c.alarm_level != "ok":
            log.info("Approach C alarm: level=%s scenario=%s", scored_c.alarm_level.upper(), scenario_id)
        records.append(AlarmRecord(
            patient_id=patient_id, condition=condition, alarm_level=scored_c.alarm_level,
            scoring_approach=APPROACH_C, news2_score=scored_c.news2_score,
            scenario_id=scenario_id, timestamp_ms=timestamp,
            schema_version=vital.schema_version, pipeline_version=vital.pipeline_version,
            threshold_version=NEWS2_THRESHOLD_VERSION, transport="nats",
            window_complete=scored_c.window_complete,
        ))

    # --- Approach B: batch composite EWS, re-scored on a fixed ~60s cadence ---
    # Cadence is approximated by message arrival rather than a wall-clock
    # timer — acceptable at v1 message rates (signals arrive every 2-10s).
    if batch_scheduler.due(patient_id, timestamp):
        scored_b = score_composite(state, timestamp, APPROACH_B)
        if scored_b is not None:
            if scored_b.alarm_level != "ok":
                log.info("Approach B alarm: level=%s scenario=%s", scored_b.alarm_level.upper(), scenario_id)
            records.append(AlarmRecord(
                patient_id=patient_id, condition=condition, alarm_level=scored_b.alarm_level,
                scoring_approach=APPROACH_B, news2_score=scored_b.news2_score,
                scenario_id=scenario_id, timestamp_ms=timestamp,
                schema_version=vital.schema_version, pipeline_version=vital.pipeline_version,
                threshold_version=NEWS2_THRESHOLD_VERSION, transport="nats",
                window_complete=scored_b.window_complete,
            ))

    # This atomic local commit is the declared durability boundary. If it
    # fails (including outbox capacity), JetStream receives no acknowledgement
    # and redelivers. Influx delivery may complete asynchronously afterward.
    try:
        await _durable_handoff(writer, records)
    except Exception:
        # Scoring state and the batch cadence are not authoritative until the
        # derived records commit. Restore them so a JetStream redelivery is
        # evaluated exactly as the original delivery would have been.
        if previous_state is None:
            ews_states.pop(patient_id, None)
        else:
            ews_states[patient_id] = previous_state
        if previous_tick is None:
            batch_scheduler._last_tick.pop(patient_id, None)
        else:
            batch_scheduler._last_tick[patient_id] = previous_tick
        raise
    await msg.ack_sync()


async def _durable_handoff(writer: InfluxWriter, records: list[VitalRecord | AlarmRecord]) -> None:
    """Persist a message's complete derived record set as one transaction."""
    enqueue_many = getattr(writer, "enqueue_many", None)
    if enqueue_many is not None:
        await enqueue_many(records)
        return
    # Compatibility for deliberately minimal test writers.
    for record in records:
        await writer.enqueue(record)


async def main() -> None:
    profiles = _load_profiles()
    ews_states: dict[str, PatientEWSState] = {}
    batch_scheduler = BatchScheduler()

    writer = InfluxWriter()
    await writer.start()

    log.info("Connecting to configured NATS endpoint")
    nc = await nats.connect(**nats_connection_options())
    js = nc.jetstream()

    # Durable pull consumer — survives brain restarts, picks up where it left off
    sub = await js.pull_subscribe(
        "vitals.>",
        durable=BRAIN_CONSUMER.durable_name,
        stream="VITALS",
        config=BRAIN_CONSUMER.as_config(),
    )
    await assert_server_consumer(js, "VITALS", BRAIN_CONSUMER)

    # Bidirectional config push — hot-reloads SIGNAL_THRESHOLDS from
    # JetStream KV without restarting the brain (see brain/config_watcher.py)
    config_task = asyncio.create_task(watch_thresholds(js), name="config-watcher")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal(*_):
        log.info("Shutdown signal — draining brain service.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    log.info("Brain service running (approaches A/B/C). Waiting for vitals messages…")
    processed = 0

    while not stop_event.is_set():
        try:
            msgs = await sub.fetch(_PULL_BATCH, timeout=_PULL_TIMEOUT)
        except NatsTimeout:
            continue
        except Exception as exc:
            log.error("NATS fetch error: %s", type(exc).__name__)
            await asyncio.sleep(1)
            continue

        for msg in msgs:
            await _process(msg, profiles, ews_states, batch_scheduler, writer, js)
            processed += 1

    log.info("Processed %d messages total. Shutting down.", processed)
    config_task.cancel()
    await writer.stop()
    try:
        await asyncio.wait_for(nc.drain(), timeout=5.0)
    except Exception:
        await nc.close()
    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
