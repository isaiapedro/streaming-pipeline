import csv
import io
import json

import pytest

from kafka_path.parity import (
    FIELDS,
    SYNTHETIC_PATIENT,
    TransportRun,
    canonical_payloads,
    compare_transports,
    main,
    render_results,
)


def test_both_runners_receive_the_same_canonical_protobuf_messages():
    messages = canonical_payloads(3)
    received = {}

    def runner(name, latencies):
        def run(candidate_messages, timeout_s):
            received[name] = candidate_messages
            assert timeout_s == 2.0
            return TransportRun(len(candidate_messages), latencies)

        return run

    results = compare_transports(
        messages,
        {
            "nats": runner("nats", (1.0, 3.0, None)),
            "kafka": runner("kafka", (2.0, 4.0, 8.0)),
        },
        timeout_s=2.0,
    )

    assert received == {"nats": messages, "kafka": messages}
    assert all(message.patient_id == SYNTHETIC_PATIENT for message in messages)
    assert all(message.pipeline_version == "transport-parity" for message in messages)
    assert results[0].as_dict() == {
        "transport": "nats",
        "published": 3,
        "accepted": 2,
        "rejected": 1,
        "p50_ms": 2.0,
        "p99_ms": 2.98,
    }
    assert results[1].accepted == 3


def test_results_are_json_and_csv_compatible_with_fixed_fields():
    results = compare_transports(
        canonical_payloads(1),
        {"nats": lambda _messages, _timeout: TransportRun(1, (1.23456,))},
        timeout_s=1.0,
    )

    json_rows = json.loads(render_results(results, "json"))
    csv_rows = list(csv.DictReader(io.StringIO(render_results(results, "csv"))))

    assert tuple(json_rows[0]) == tuple(sorted(FIELDS))
    assert tuple(csv_rows[0]) == FIELDS
    assert json_rows[0]["p50_ms"] == 1.235
    assert csv_rows[0]["transport"] == "nats"


@pytest.mark.parametrize("count", [0, 1001])
def test_payload_count_is_bounded(count):
    with pytest.raises(ValueError, match="between 1 and 1000"):
        canonical_payloads(count)


@pytest.mark.parametrize("timeout_s", [0.0, 60.1])
def test_live_timeout_is_bounded_before_runner_invocation(timeout_s):
    called = False

    def runner(_messages, _timeout):
        nonlocal called
        called = True
        return TransportRun(1, (1.0,))

    with pytest.raises(ValueError, match="between 0.1 and 60"):
        compare_transports(canonical_payloads(1), {"nats": runner}, timeout_s=timeout_s)
    assert called is False


def test_cli_requires_explicit_live_opt_in(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--count", "1"])

    assert exc.value.code == 2
    assert "--live is required" in capsys.readouterr().err
