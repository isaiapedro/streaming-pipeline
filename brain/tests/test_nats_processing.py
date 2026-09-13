import time

import pytest

from brain.approaches import BatchScheduler
from brain.main import _process
from brain.validation import DLQ_SUBJECT
from schema import vitals_pb2


class FakeMessage:
    def __init__(self, subject: str, data: bytes) -> None:
        self.subject = subject
        self.data = data
        self.acks = 0

    async def ack_sync(self) -> None:
        self.acks += 1


class FakeWriter:
    def __init__(self) -> None:
        self.records = []

    async def enqueue(self, record) -> None:
        self.records.append(record)


class FakeJetStream:
    def __init__(self, publish_error: Exception | None = None) -> None:
        self.publications = []
        self.publish_error = publish_error

    async def publish(self, subject, payload, headers=None):
        if self.publish_error is not None:
            raise self.publish_error
        self.publications.append((subject, payload, headers))


def _encoded_vital() -> bytes:
    return vitals_pb2.VitalSign(
        patient_id="P-001",
        signal_type="heart_rate",
        scalar_value=80,
        timestamp_ms=int(time.time() * 1000),
        schema_version="1",
        pipeline_version="test",
    ).SerializeToString()


@pytest.mark.asyncio
async def test_subject_mismatch_is_dead_lettered_before_state_or_writer_mutation():
    message = FakeMessage("vitals.P-001.spo2", _encoded_vital())
    writer = FakeWriter()
    jetstream = FakeJetStream()
    states = {}

    await _process(
        message,
        {"P-001": {"condition": "test", "copd_flag": False}},
        states,
        BatchScheduler(),
        writer,
        jetstream,
    )

    assert writer.records == []
    assert states == {}
    assert message.acks == 1
    assert len(jetstream.publications) == 1
    subject, encoded, headers = jetstream.publications[0]
    assert subject == DLQ_SUBJECT
    assert headers["Nats-Msg-Id"].startswith("dlq:")
    envelope = vitals_pb2.DeadLetterEnvelope()
    envelope.ParseFromString(encoded)
    assert envelope.error_message == "subject_signal_mismatch"


@pytest.mark.asyncio
async def test_rejected_source_is_not_acked_when_dlq_publish_fails():
    message = FakeMessage("vitals.P-001.spo2", _encoded_vital())
    jetstream = FakeJetStream(publish_error=RuntimeError("broker unavailable"))

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await _process(
            message,
            {"P-001": {"condition": "test", "copd_flag": False}},
            {},
            BatchScheduler(),
            FakeWriter(),
            jetstream,
        )

    assert message.acks == 0
