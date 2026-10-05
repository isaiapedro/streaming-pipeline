import csv

from scripts.analyze_transport_stress import _aggregate, _write_csv
from scripts.latency_percentiles import percentile_rows


def _row(transport, repetition, p50, p99, throughput=100.0):
    return {
        "transport": transport,
        "repetition": repetition,
        "elapsed_s": 1.0,
        "throughput_msg_s": throughput,
        "valid_delivery_ratio": 1.0,
        "p50_ms": p50,
        "p75_ms": p50,
        "p90_ms": p99,
        "p95_ms": p99,
        "p99_ms": p99,
        "tail_spread_ms": p99 - p50,
        "tail_amplification": p99 / p50,
    }


def test_three_transport_aggregate_retains_repetition_distribution():
    rows = []
    for transport, base in (("nats", 1.0), ("mqtt", 2.0), ("kafka", 3.0)):
        rows.extend((_row(transport, 1, base, base * 2), _row(transport, 2, base * 2, base * 3)))
    aggregate = _aggregate(rows)
    assert [row["transport"] for row in aggregate] == ["nats", "mqtt", "kafka"]
    assert all(row["repetitions"] == 2 for row in aggregate)
    assert aggregate[0]["valid_delivery_ratio_mean"] == 1.0


def test_percentile_export_contains_every_integer_p50_through_p99():
    rows = percentile_rows({"nats": [1.0, 2.0], "mqtt": [2.0, 3.0], "kafka": [3.0, 4.0]})
    assert len(rows) == 3 * 50
    assert {row["percentile"] for row in rows} == set(range(50, 100))


def test_csv_writer_preserves_aggregate_columns(tmp_path):
    path = tmp_path / "summary.csv"
    _write_csv(path, [{"transport": "nats", "p50_ms": 1.0}])
    with path.open(newline="") as handle:
        assert next(csv.DictReader(handle)) == {"transport": "nats", "p50_ms": "1.0"}
