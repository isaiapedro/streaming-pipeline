"""Opt-in live transport parity harness for NATS JetStream and Kafka.

Both transports receive the same canonical ``VitalSign`` messages.  The
reported records contain only aggregate counts and latency percentiles; the
synthetic patient identifier never leaves the configured brokers.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import nats
from confluent_kafka import Consumer, KafkaException, Producer, TopicPartition
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

from brain.validation import (
    DLQ_SUBJECT,
    ValidationError,
    dead_letter,
    dead_letter_message_id,
    decode_and_validate,
)
from config.settings import SCHEMA_VERSION, nats_connection_options
from kafka_path.settings import KafkaSettings
from kafka_path.transport import (
    KafkaVitalConsumer,
    KafkaVitalProducer,
    _produce_and_wait,
)
from schema import vitals_pb2


SYNTHETIC_PATIENT = "P-TRANSPORT-PARITY"
FIELDS = ("transport", "published", "accepted", "rejected", "p50_ms", "p99_ms")
POISON_PAYLOAD = b"transport-parity-invalid-protobuf"


def _poison_payload(messages: Sequence[vitals_pb2.VitalSign]) -> bytes:
    return POISON_PAYLOAD + b":" + str(messages[0].timestamp_ms).encode()


@dataclass(frozen=True)
class TransportRun:
    published: int
    latencies_ms: tuple[float | None, ...]


@dataclass(frozen=True)
class ParityResult:
    transport: str
    published: int
    accepted: int
    rejected: int
    p50_ms: float | None
    p99_ms: float | None

    def as_dict(self) -> dict[str, str | int | float | None]:
        return {field: getattr(self, field) for field in FIELDS}


Runner = Callable[[Sequence[vitals_pb2.VitalSign], float], TransportRun]


def canonical_payloads(count: int) -> tuple[vitals_pb2.VitalSign, ...]:
    """Create synthetic, non-clinical payloads shared by both transports."""
    if not 1 <= count <= 1_000:
        raise ValueError("count must be between 1 and 1000")
    base_ms = int(time.time() * 1000)
    return tuple(
        vitals_pb2.VitalSign(
            patient_id=SYNTHETIC_PATIENT,
            signal_type="heart_rate",
            scalar_value=80.0,
            timestamp_ms=base_ms + index,
            schema_version=SCHEMA_VERSION,
            pipeline_version="transport-parity",
            scenario_id="synthetic_transport_parity",
        )
        for index in range(count)
    )


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    interpolated = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(interpolated, 3)


def summarize(transport: str, run: TransportRun) -> ParityResult:
    """Summarize delivery; deadline-expired messages count as rejected."""
    accepted_latencies = [value for value in run.latencies_ms if value is not None]
    accepted = len(accepted_latencies)
    if accepted > run.published:
        raise ValueError("accepted observations cannot exceed published messages")
    return ParityResult(
        transport=transport,
        published=run.published,
        accepted=accepted,
        rejected=run.published - accepted,
        p50_ms=_percentile(accepted_latencies, 0.50),
        p99_ms=_percentile(accepted_latencies, 0.99),
    )


def compare_transports(
    messages: Sequence[vitals_pb2.VitalSign],
    runners: Mapping[str, Runner],
    *,
    timeout_s: float,
) -> list[ParityResult]:
    if not 0.1 <= timeout_s <= 60.0:
        raise ValueError("timeout_s must be between 0.1 and 60")
    return [summarize(name, runner(messages, timeout_s)) for name, runner in runners.items()]


def render_results(results: Sequence[ParityResult], output_format: str) -> str:
    rows = [result.as_dict() for result in results]
    if output_format == "json":
        return json.dumps(rows, indent=2, sort_keys=True)
    if output_format != "csv":
        raise ValueError("output_format must be json or csv")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().rstrip("\n")


def _numeric_localhost(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.hostname != "localhost":
        return url
    auth, separator, _host = parsed.netloc.rpartition("@")
    prefix = f"{auth}{separator}" if separator else ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit(parsed._replace(netloc=f"{prefix}127.0.0.1{port}"))


async def _run_nats_async(
    messages: Sequence[vitals_pb2.VitalSign], timeout_s: float
) -> TransportRun:
    options = nats_connection_options()
    servers = options["servers"]
    options["servers"] = (
        _numeric_localhost(servers)
        if isinstance(servers, str)
        else [_numeric_localhost(server) for server in servers]
    )
    options.update(
        allow_reconnect=False,
        connect_timeout=min(2, timeout_s),
        max_reconnect_attempts=1,
        reconnect_time_wait=0,
    )
    nc = await nats.connect(**options)
    js = nc.jetstream()
    subject = f"vitals.{SYNTHETIC_PATIENT}.heart_rate"
    subscription = None
    durable = f"PARITY_{uuid4().hex}"
    published_at: dict[int, int] = {}
    latencies: list[float | None] = []
    published = 0
    deadline = time.monotonic() + timeout_s
    poison_payload = _poison_payload(messages)
    try:
        subscription = await js.pull_subscribe(
            subject,
            durable=durable,
            config=ConsumerConfig(
                ack_policy=AckPolicy.EXPLICIT,
                deliver_policy=DeliverPolicy.NEW,
            ),
            stream="VITALS",
        )
        for message in messages:
            published_at[message.timestamp_ms] = time.perf_counter_ns()
            await js.publish(subject, message.SerializeToString())
            published += 1
        await js.publish(subject, poison_payload)
        published += 1
        while len(latencies) < published and time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            try:
                records = await subscription.fetch(1, timeout=remaining)
            except TimeoutError:
                break
            record = records[0]
            try:
                vital = decode_and_validate(
                    record.data,
                    {SYNTHETIC_PATIENT: {}},
                    source_subject=subject,
                )
                started = published_at.get(vital.timestamp_ms)
                if started is not None:
                    latencies.append((time.perf_counter_ns() - started) / 1_000_000)
            except ValidationError as error:
                await js.publish(
                    DLQ_SUBJECT,
                    dead_letter(
                        record.data,
                        error,
                        subject,
                        pipeline_version="transport-parity",
                    ),
                    headers={"Nats-Msg-Id": dead_letter_message_id(record.data, subject)},
                )
                if record.data == poison_payload:
                    latencies.append(None)
            await record.ack()
    finally:
        try:
            if subscription is not None:
                await subscription.unsubscribe()
                await js.delete_consumer("VITALS", durable)
        finally:
            await nc.close()
    latencies.extend([None] * (published - len(latencies)))
    return TransportRun(published, tuple(latencies))


def run_nats(messages: Sequence[vitals_pb2.VitalSign], timeout_s: float) -> TransportRun:
    return asyncio.run(_run_nats_async(messages, timeout_s))


def run_kafka(messages: Sequence[vitals_pb2.VitalSign], timeout_s: float) -> TransportRun:
    settings = replace(KafkaSettings.from_env(), group_id=f"transport-parity-{uuid4().hex}")
    raw_consumer = Consumer({**settings.consumer_config(), "auto.offset.reset": "latest"})
    producer = KafkaVitalProducer(settings)
    consumer = KafkaVitalConsumer(
        {SYNTHETIC_PATIENT: {}},
        settings,
        consumer=raw_consumer,
        pipeline_version="transport-parity",
    )
    published_at: dict[int, int] = {}
    accepted: dict[int, float] = {}
    observed = 0
    published = 0
    poison_payload = _poison_payload(messages)

    def observe(vital) -> None:
        started = published_at.get(vital.timestamp_ms)
        if vital.patient_id == SYNTHETIC_PATIENT and started is not None:
            accepted[vital.timestamp_ms] = (time.perf_counter_ns() - started) / 1_000_000

    producer.start()
    consumer.start()
    deadline = time.monotonic() + timeout_s
    try:
        while not raw_consumer.assignment() and time.monotonic() < deadline:
            raw_consumer.poll(min(0.1, max(0.01, deadline - time.monotonic())))
        if not raw_consumer.assignment():
            return TransportRun(0, ())
        for partition in raw_consumer.assignment():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return TransportRun(0, ())
            _, high = raw_consumer.get_watermark_offsets(
                partition, timeout=min(5.0, remaining)
            )
            raw_consumer.seek(TopicPartition(partition.topic, partition.partition, high))
        for message in messages:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            published_at[message.timestamp_ms] = time.perf_counter_ns()
            producer.publish(message, timeout=min(10.0, remaining))
            published += 1
        remaining = deadline - time.monotonic()
        if remaining > 0:
            raw_producer = Producer(settings.producer_config())
            _produce_and_wait(
                raw_producer,
                topic=settings.vitals_topic,
                key=SYNTHETIC_PATIENT.encode(),
                value=poison_payload,
                timeout=min(10.0, remaining),
            )
            published += 1
        while observed < published and time.monotonic() < deadline:
            record = raw_consumer.poll(
                min(0.25, max(0.01, deadline - time.monotonic()))
            )
            if record is None:
                continue
            if record.error():
                raise KafkaException(record.error())
            matched_valid = False

            def observe_current(vital) -> None:
                nonlocal matched_valid
                before = len(accepted)
                observe(vital)
                matched_valid = len(accepted) > before

            result = consumer.process_record(record, observe_current)
            if matched_valid or (result is False and record.value() == poison_payload):
                observed += 1
    finally:
        consumer.close()
    latencies = tuple(accepted.get(message.timestamp_ms) for message in messages)
    if published > len(messages):
        latencies += (None,)
    return TransportRun(published, latencies)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="confirm intentional broker access")
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="number of valid messages per transport; one poison record is added",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live is required; this harness never contacts brokers implicitly")
    messages = canonical_payloads(args.count)
    results = compare_transports(
        messages,
        {"nats": run_nats, "kafka": run_kafka},
        timeout_s=args.timeout,
    )
    print(render_results(results, args.format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
