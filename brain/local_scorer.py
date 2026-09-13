"""NATS-local NEWS2 scorer that publishes priority-preserving alarm events."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

import nats

from config.nats_consumers import LOCAL_SCORER_CONSUMER, assert_server_consumer
from nats.errors import TimeoutError as NatsTimeout

from brain.approaches import APPROACH_C, score_composite
from brain.ews_window import PatientEWSState
from brain.validation import (
    DLQ_SUBJECT,
    ValidationError,
    dead_letter,
    dead_letter_message_id,
    decode_and_validate,
)
from config.settings import PIPELINE_VERSION, nats_connection_options
from config.thresholds import NEWS2_THRESHOLD_VERSION
from schema import vitals_pb2

log = logging.getLogger(__name__)
PROFILES_DIR = Path(__file__).parent.parent / "data" / "profiles"
_PULL_BATCH, _PULL_TIMEOUT = 50, 1.0


def _load_profiles() -> dict[str, dict]:
    profiles = {p["patient_id"]: p for p in (json.loads(path.read_text()) for path in PROFILES_DIR.glob("P-*.json"))}
    if not profiles:
        log.error("No patient profiles found in %s", PROFILES_DIR)
        sys.exit(1)
    return profiles


def priority_for(score: int, alarm_level: str | None = None) -> str | None:
    if score >= 7:
        return "high"
    if score >= 5 or alarm_level == "warning":
        return "medium"
    return None


def make_alarm_event(vital, priority: str, score: int):
    """Preserve validated provenance without extending the frozen Protobuf schema."""
    event = vitals_pb2.AlertEvent(
        patient_id=vital.patient_id,
        priority=priority,
        news2_score=score,
        timestamp_ms=vital.timestamp_ms,
        schema_version=vital.schema_version,
        pipeline_version=vital.pipeline_version,
    )
    headers = {
        "X-Scoring-Approach": APPROACH_C,
        "X-Scenario-Id": vital.scenario_id,
        "X-Threshold-Version": NEWS2_THRESHOLD_VERSION,
    }
    return event, headers


async def _process(msg, profiles: dict[str, dict], states: dict[str, PatientEWSState], js) -> None:
    """Process one message; local state is intentionally not a durable boundary."""
    try:
        vital = decode_and_validate(msg.data, profiles, source_subject=msg.subject)
    except ValidationError as exc:
        await js.publish(
            DLQ_SUBJECT,
            dead_letter(msg.data, exc, msg.subject, pipeline_version=PIPELINE_VERSION),
            headers={"Nats-Msg-Id": dead_letter_message_id(msg.data, msg.subject)},
        )
        await msg.ack_sync()
        return
    profile = profiles[vital.patient_id]
    state = states.setdefault(
        vital.patient_id,
        PatientEWSState(
            vital.patient_id,
            spo2_scale=int(profile.get("news2_spo2_scale", 1)),
        ),
    )
    if vital.signal_type == "blood_pressure":
        state.update("systolic_bp", vital.value["systolic"], vital.timestamp_ms)
    else:
        state.update(vital.signal_type, vital.value, vital.timestamp_ms)
    scored = score_composite(state, vital.timestamp_ms, APPROACH_C)
    if scored and (priority := priority_for(scored.news2_score, scored.alarm_level)):
        event, headers = make_alarm_event(vital, priority, scored.news2_score)
        await js.publish(
            f"alarms.{vital.patient_id}.{priority}",
            event.SerializeToString(),
            headers=headers,
        )
    await msg.ack_sync()


async def main() -> None:
    profiles, states = _load_profiles(), {}
    nc = await nats.connect(**nats_connection_options())
    js = nc.jetstream()
    sub = await js.pull_subscribe(
        "vitals.>",
        durable=LOCAL_SCORER_CONSUMER.durable_name,
        stream="VITALS",
        config=LOCAL_SCORER_CONSUMER.as_config(),
    )
    await assert_server_consumer(js, "VITALS", LOCAL_SCORER_CONSUMER)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    while not stop.is_set():
        try:
            messages = await sub.fetch(_PULL_BATCH, timeout=_PULL_TIMEOUT)
        except NatsTimeout:
            continue
        for msg in messages:
            await _process(msg, profiles, states, js)

    await nc.drain()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
