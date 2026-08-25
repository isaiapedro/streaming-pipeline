"""Brain service entry point.

Subscribes to all vitals subjects on NATS JetStream and runs all three
scoring approaches (A/B/C — see brain/approaches.py) per message, writing
batched records to InfluxDB Cloud tagged by `scoring_approach` so Grafana
can compare them side by side.
"""

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

import nats
from nats.errors import TimeoutError as NatsTimeout

from config.settings import NATS_URL
from brain.approaches import APPROACH_B, APPROACH_C, BatchScheduler, score_composite
from brain.config_watcher import watch_thresholds
from brain.evaluator import evaluate_message
from brain.ews_window import PatientEWSState
from brain.influx_writer import InfluxWriter, VitalRecord, AlarmRecord

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
    log.info("Profiles loaded: %s", list(mapping))
    return mapping


async def _process(
    msg,
    profiles: dict[str, dict],
    ews_states: dict[str, PatientEWSState],
    batch_scheduler: BatchScheduler,
    writer: InfluxWriter,
) -> None:
    try:
        data = json.loads(msg.data)
    except json.JSONDecodeError as exc:
        log.warning("Bad JSON on subject %s: %s", msg.subject, exc)
        await msg.ack()
        return

    patient_id     = data.get("patient_id", "unknown")
    signal_type    = data.get("signal_type", "unknown")
    value          = data.get("value")
    timestamp      = data.get("timestamp", 0)
    scenario_id    = data.get("scenario_id") or "none"
    profile        = profiles.get(patient_id, {})
    condition      = profile.get("condition", "unknown")
    copd_flag      = bool(profile.get("copd_flag", False))

    # --- Approach A: per-signal threshold (existing behavior, tagged "A") ---
    for sig, float_val, level in evaluate_message(signal_type, value):
        if level != "ok":
            log.info("[%s][A] %s=%s → %s", patient_id, sig, float_val, level.upper())
        await writer.enqueue(VitalRecord(
            patient_id=patient_id, signal_type=sig, condition=condition,
            alarm_level=level, value=float_val, timestamp_ms=timestamp,
            scoring_approach="A", scenario_id=scenario_id,
        ))

    # --- Update shared EWS window state (backs both B and C) ---
    state = ews_states.setdefault(patient_id, PatientEWSState(patient_id, copd_flag=copd_flag))
    if signal_type == "blood_pressure" and isinstance(value, dict):
        state.update("systolic_bp", float(value["systolic"]), timestamp)
    elif signal_type in ("respiratory_rate", "spo2", "heart_rate", "temperature"):
        state.update(signal_type, float(value), timestamp)

    # --- Approach C: streaming composite EWS, re-scored on every message ---
    scored_c = score_composite(state, timestamp, APPROACH_C)
    if scored_c is not None:
        if scored_c.alarm_level != "ok":
            log.info("[%s][C] NEWS2=%s → %s", patient_id, scored_c.news2_score, scored_c.alarm_level.upper())
        await writer.enqueue(AlarmRecord(
            patient_id=patient_id, condition=condition, alarm_level=scored_c.alarm_level,
            scoring_approach=APPROACH_C, news2_score=scored_c.news2_score,
            scenario_id=scenario_id, timestamp_ms=timestamp,
        ))

    # --- Approach B: batch composite EWS, re-scored on a fixed ~60s cadence ---
    # Cadence is approximated by message arrival rather than a wall-clock
    # timer — acceptable at v1 message rates (signals arrive every 2-10s).
    if batch_scheduler.due(patient_id, timestamp):
        scored_b = score_composite(state, timestamp, APPROACH_B)
        if scored_b is not None:
            if scored_b.alarm_level != "ok":
                log.info("[%s][B] NEWS2=%s → %s", patient_id, scored_b.news2_score, scored_b.alarm_level.upper())
            await writer.enqueue(AlarmRecord(
                patient_id=patient_id, condition=condition, alarm_level=scored_b.alarm_level,
                scoring_approach=APPROACH_B, news2_score=scored_b.news2_score,
                scenario_id=scenario_id, timestamp_ms=timestamp,
            ))

    await msg.ack()


async def main() -> None:
    profiles = _load_profiles()
    ews_states: dict[str, PatientEWSState] = {}
    batch_scheduler = BatchScheduler()

    writer = InfluxWriter()
    await writer.start()

    log.info("Connecting to NATS at %s", NATS_URL)
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()

    # Durable pull consumer — survives brain restarts, picks up where it left off
    sub = await js.pull_subscribe("vitals.>", durable="BRAIN", stream="VITALS")

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
            log.error("fetch error: %s", exc)
            await asyncio.sleep(1)
            continue

        for msg in msgs:
            await _process(msg, profiles, ews_states, batch_scheduler, writer)
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
