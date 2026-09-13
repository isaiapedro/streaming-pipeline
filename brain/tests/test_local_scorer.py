import pytest

from brain.local_scorer import _process, priority_for
from schema import vitals_pb2


def test_news2_priority_mapping():
    assert priority_for(4) is None
    assert priority_for(5) == "medium"
    assert priority_for(6) == "medium"
    assert priority_for(7) == "high"


def test_single_parameter_warning_gets_medium_priority():
    assert priority_for(3, "warning") == "medium"


@pytest.mark.asyncio
async def test_local_scorer_confirms_alarm_publish_before_source_ack():
    operations = []

    class JetStream:
        async def publish(self, subject, payload, headers=None):
            operations.append(("publish", subject, payload, headers))

    class Message:
        def __init__(self, signal_type, value):
            self.subject = f"vitals.P-TEST.{signal_type}"
            vital = vitals_pb2.VitalSign(
                patient_id="P-TEST",
                signal_type=signal_type,
                timestamp_ms=1_700_000_000_000,
                schema_version="1",
                pipeline_version="test",
            )
            if signal_type == "blood_pressure":
                vital.bp.systolic, vital.bp.diastolic = value
            else:
                vital.scalar_value = value
            self.data = vital.SerializeToString()

        async def ack_sync(self):
            operations.append(("ack", self.subject))

    readings = (
        ("heart_rate", 135.0),
        ("spo2", 85.0),
        ("respiratory_rate", 28.0),
        ("blood_pressure", (190.0, 70.0)),
        ("temperature", 39.2),
    )
    states = {}
    js = JetStream()
    for signal_type, value in readings:
        await _process(
            Message(signal_type, value),
            {"P-TEST": {"condition": "synthetic", "news2_spo2_scale": 1}},
            states,
            js,
        )

    alarm_indexes = [
        index for index, event in enumerate(operations)
        if event[0] == "publish" and event[1].startswith("alarms.")
    ]
    assert len(alarm_indexes) == 1
    alarm_index = alarm_indexes[0]
    assert operations[alarm_index][1] == "alarms.P-TEST.high"
    assert operations[alarm_index + 1] == ("ack", "vitals.P-TEST.temperature")
    event = vitals_pb2.AlertEvent()
    event.ParseFromString(operations[alarm_index][2])
    assert event.patient_id == "P-TEST"
    assert event.priority == "high"


@pytest.mark.asyncio
async def test_local_scorer_does_not_ack_when_alarm_publish_fails():
    class JetStream:
        async def publish(self, *_args, **_kwargs):
            raise RuntimeError("alarm stream unavailable")

    class Message:
        subject = "vitals.P-TEST.temperature"

        def __init__(self):
            vital = vitals_pb2.VitalSign(
                patient_id="P-TEST",
                signal_type="temperature",
                scalar_value=39.2,
                timestamp_ms=1_700_000_000_000,
                schema_version="1",
                pipeline_version="test",
            )
            self.data = vital.SerializeToString()

        async def ack_sync(self):
            pytest.fail("source acknowledged after alarm publish failure")

    # Seed a complete high-scoring state, then force an alarm on the test input.
    from brain.ews_window import PatientEWSState

    state = PatientEWSState("P-TEST", spo2_scale=1)
    for signal_type, value in (
        ("heart_rate", 135.0),
        ("spo2", 85.0),
        ("respiratory_rate", 28.0),
        ("systolic_bp", 190.0),
        ("temperature", 39.2),
    ):
        state.update(signal_type, value, 1_700_000_000_000)

    with pytest.raises(RuntimeError, match="alarm stream unavailable"):
        await _process(
            Message(),
            {"P-TEST": {"condition": "synthetic", "news2_spo2_scale": 1}},
            {"P-TEST": state},
            JetStream(),
        )
