"""Integration test: real NATS JetStream -> scoring (Approach A + composite C),
exercising the actual wire path instead of in-process simulation.

Requires a local NATS with the VITALS stream already created (see
`scripts/create_streams.sh`) — skips cleanly rather than failing when no
broker is running, so this doesn't break a plain `pytest` run on a machine
without Docker up.

Does NOT touch InfluxDB — this test verifies the NATS transport + scoring
logic only, deliberately avoiding writes to the real InfluxDB Cloud bucket
that `brain/main.py` would otherwise make (this test has no test-specific
InfluxDB target to write to safely).
"""

import asyncio
import json
import time

import nats
import pytest

from brain.approaches import APPROACH_C, score_composite
from brain.evaluator import evaluate_message
from brain.ews_window import PatientEWSState
from config.settings import NATS_URL

TEST_PATIENT = "P-TEST-INTEGRATION"
TEST_DURABLE = "BRAIN_TEST_INTEGRATION"


async def _try_connect():
    try:
        return await asyncio.wait_for(nats.connect(NATS_URL), timeout=2.0)
    except Exception:
        return None


@pytest.mark.asyncio
async def test_nats_to_scoring_end_to_end():
    nc = await _try_connect()
    if nc is None:
        pytest.skip(
            f"NATS not reachable at {NATS_URL} — start it with "
            f"`docker compose up -d nats` and `bash scripts/create_streams.sh` to run this test"
        )

    js = nc.jetstream()

    # One full round of vitals, deliberately deteriorating so both Approach A
    # (per-signal) and the composite score should alarm.
    ts = int(time.time() * 1000)
    readings = {
        "heart_rate": 135,
        "spo2": 85,
        "respiratory_rate": 28,
        "blood_pressure": {"systolic": 190, "diastolic": 70},
        "temperature": 39.2,
    }
    for signal_type, value in readings.items():
        payload = {"patient_id": TEST_PATIENT, "signal_type": signal_type, "value": value, "timestamp": ts}
        await js.publish(f"vitals.{TEST_PATIENT}.{signal_type}", json.dumps(payload).encode())

    try:
        sub = await js.pull_subscribe(f"vitals.{TEST_PATIENT}.>", durable=TEST_DURABLE, stream="VITALS")
        msgs = await sub.fetch(len(readings), timeout=5.0)
        assert len(msgs) == len(readings), f"expected {len(readings)} messages, got {len(msgs)}"

        ews_state = PatientEWSState(TEST_PATIENT, copd_flag=False)
        approach_a_alarms = []
        for msg in msgs:
            data = json.loads(msg.data)
            signal_type, value, timestamp = data["signal_type"], data["value"], data["timestamp"]

            for sig, _val, level in evaluate_message(signal_type, value):
                if level != "ok":
                    approach_a_alarms.append((sig, level))

            if signal_type == "blood_pressure":
                ews_state.update("systolic_bp", value["systolic"], timestamp)
            else:
                ews_state.update(signal_type, value, timestamp)
            await msg.ack()

        score_c = score_composite(ews_state, ts, APPROACH_C)

        assert approach_a_alarms, "Approach A should have alarmed on at least one signal"
        assert score_c is not None and score_c.alarm_level != "ok", "Approach C composite score should alarm"
    finally:
        try:
            await js.delete_consumer("VITALS", TEST_DURABLE)
        except Exception:
            pass
        await nc.close()
