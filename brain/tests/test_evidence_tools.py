import csv
import json
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

from data.scenarios.definitions import SCENARIOS
from schema import vitals_pb2
from scripts.aggregate_benchmark import aggregate, load_rows, validate_full_matrix, write_aggregate
from scripts.benchmark_protocol import _benchmark_payload, _wire_overhead_table
from scripts.build_evidence_manifest import (
    attestation_chain,
    benchmark_artifacts,
    dependency_versions,
    evidence_inventory,
    enforce_final_release,
)
from scripts.measure_live_latency import percentile, summarize
from scripts.run_benchmark import (
    DEFAULT_NOISE_SEEDS,
    DEFAULT_SIGNAL_SEEDS,
    DEFAULT_STABLE_DURATION_S,
    scenario_for_benchmark,
)
from scripts.run_scale_tier import machine_context, write_result

ROOT = Path(__file__).parents[2]


def test_checked_full_benchmark_has_450_rows_and_18_groups():
    rows = load_rows(ROOT / "benchmark_results.csv")
    validate_full_matrix(rows, expected_signal_seeds=5, expected_noise_seeds=5)
    result = aggregate(rows)
    assert len(rows) == 450
    assert len(result) == 18
    assert all(row["source_rows"] == 25 for row in result)


def test_missing_metrics_remain_unavailable_in_aggregate(tmp_path):
    rows = load_rows(ROOT / "benchmark_results.csv")
    result = aggregate(rows)
    stable_a = next(row for row in result if row["scenario"] == "stable_baseline" and row["approach"] == "A")
    assert stable_a["detection_run_rate_n"] == 0
    assert stable_a["detection_run_rate_mean"] is None
    assert stable_a["scoring_detection_latency_ms_n"] == 0

    path = tmp_path / "aggregate.csv"
    write_aggregate(result, path)
    written = list(csv.DictReader(path.open()))
    output = next(row for row in written if row["scenario"] == "stable_baseline" and row["approach"] == "A")
    assert output["detection_run_rate_mean"] == ""
    assert output["scoring_detection_latency_ms_mean"] == ""


def test_full_matrix_rejects_duplicate_or_missing_seed_pair():
    rows = load_rows(ROOT / "benchmark_results.csv")
    rows[-1] = dict(rows[-2])
    with pytest.raises(ValueError, match="unique seed pairs|identical seed pairs"):
        validate_full_matrix(rows, expected_signal_seeds=5, expected_noise_seeds=5)


def test_benchmark_provenance_is_complete_privacy_safe_and_uses_24h_stable_runs():
    records = [json.loads(line) for line in (ROOT / "evidence/experiment_runs.jsonl").read_text().splitlines()]
    assert len(records) == 150
    assert all(record["status"] == "completed" for record in records)
    assert all("patient_id" not in record and "value" not in record for record in records)
    stable = [record for record in records if record["scenario"] == "stable_baseline"]
    assert len(stable) == 25
    assert {record["duration_s"] for record in stable} == {86_400}


def test_probability_intervals_are_bounded_and_missing_values_stay_missing():
    result = aggregate(load_rows(ROOT / "benchmark_results.csv"))
    for row in result:
        for metric in ("detection_run_rate", "false_alarm_run_probability"):
            low, high = row[f"{metric}_ci95_low"], row[f"{metric}_ci95_high"]
            if low is not None:
                assert 0.0 <= low <= high <= 1.0


def test_stable_baseline_selector_applies_24_hour_protocol_only_to_stable_scenario():
    stable = scenario_for_benchmark(SCENARIOS["stable_baseline"], DEFAULT_STABLE_DURATION_S)
    sepsis = scenario_for_benchmark(SCENARIOS["sepsis_progression"], DEFAULT_STABLE_DURATION_S)
    assert stable.duration_s == 86_400
    assert sepsis is SCENARIOS["sepsis_progression"]


def _write_artifact_pair(tmp_path: Path, stable_duration_s: int = 86_400) -> tuple[Path, Path]:
    benchmark_path = tmp_path / "benchmark.csv"
    run_log_path = tmp_path / "runs.jsonl"
    fields = ["run_id", "scenario", "signal_seed", "noise_seed", "approach", "duration_s"]
    with benchmark_path.open("w", newline="") as benchmark_handle, run_log_path.open("w") as log_handle:
        writer = csv.DictWriter(benchmark_handle, fieldnames=fields)
        writer.writeheader()
        for scenario in SCENARIOS:
            duration = stable_duration_s if scenario == "stable_baseline" else SCENARIOS[scenario].duration_s
            for signal_seed in DEFAULT_SIGNAL_SEEDS:
                for noise_seed in DEFAULT_NOISE_SEEDS:
                    run_id = f"{scenario}-{signal_seed}-{noise_seed}"
                    for approach in ("A", "B", "C"):
                        writer.writerow({
                            "run_id": run_id,
                            "scenario": scenario,
                            "signal_seed": signal_seed,
                            "noise_seed": noise_seed,
                            "approach": approach,
                            "duration_s": duration,
                        })
                    log_handle.write(json.dumps({
                        "run_id": run_id,
                        "status": "completed",
                        "worktree_dirty": False,
                        "git_commit": "implementation",
                    }) + "\n")
    return benchmark_path, run_log_path


def test_manifest_artifact_contract_hashes_and_validates_crossed_design(tmp_path):
    benchmark_path, run_log_path = _write_artifact_pair(tmp_path)
    result = benchmark_artifacts(benchmark_path, run_log_path)
    assert result["validation_status"] == "valid"
    assert result["raw_benchmark"]["record_count"] == 450
    assert result["run_log"]["record_count"] == 150
    assert len(result["raw_benchmark"]["sha256"]) == 64
    assert len(result["run_log"]["sha256"]) == 64
    assert result["raw_benchmark"]["role"] == "raw_benchmark_input"
    assert result["run_log"]["role"] == "run_provenance"


def test_evidence_inventory_assigns_roles_and_avoids_hash_cycle(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.build_evidence_manifest._is_tracked", lambda path: True)
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "abc_plot.png").write_bytes(b"plot")
    (tmp_path / "FIGURE_CAPTIONS.md").write_text("caption")
    (tmp_path / "manifest.json").write_text("self")
    (tmp_path / "SHA256SUMS").write_text("self")
    result = evidence_inventory(tmp_path)
    assert [(item["path"], item["role"]) for item in result] == [
        ("evidence/FIGURE_CAPTIONS.md", "figure_captions"),
        ("evidence/figures/abc_plot.png", "figure"),
    ]
    assert all(len(item["sha256"]) == 64 for item in result)
    assert all(item["tracked"] is True for item in result)
    assert result[1]["media_type"] == "image/png"
    assert result[1]["size_bytes"] == 4
    assert result[1]["generated_by"] == "scripts/aggregate_benchmark.py"


def test_manifest_artifact_contract_rejects_short_stable_baseline(tmp_path):
    benchmark_path, run_log_path = _write_artifact_pair(tmp_path, stable_duration_s=600)
    result = benchmark_artifacts(benchmark_path, run_log_path)
    assert result["validation_status"] == "development_only"
    assert any("final protocol requires 86400" in error for error in result["validation_errors"])


def test_final_release_fails_closed_with_actionable_blockers():
    with pytest.raises(RuntimeError, match="worktree is dirty"):
        enforce_final_release({"release": {"blockers": ["worktree is dirty"]}})


def test_attestation_chain_allows_only_evidence_changes(monkeypatch):
    def clean_chain(*args):
        if args[:3] == ("diff", "--name-only", "implementation..attestation"):
            return "benchmark_results.csv\nevidence/manifest.json\nevidence/SHA256SUMS"
        return ""

    monkeypatch.setattr("scripts.build_evidence_manifest.git_value", clean_chain)
    assert attestation_chain("implementation", "attestation") == []


def test_attestation_chain_rejects_code_changes(monkeypatch):
    def changed_code(*args):
        if args[:3] == ("diff", "--name-only", "implementation..attestation"):
            return "evidence/manifest.json\nbrain/main.py"
        return ""

    monkeypatch.setattr("scripts.build_evidence_manifest.git_value", changed_code)
    assert attestation_chain("implementation", "attestation") == [
        "implementation-to-attestation history changes non-evidence paths: brain/main.py"
    ]


def test_attestation_chain_rejects_non_ancestor(monkeypatch):
    def no_ancestor(*args):
        if args[:2] == ("merge-base", "--is-ancestor"):
            raise __import__("subprocess").CalledProcessError(1, args)
        return ""

    monkeypatch.setattr("scripts.build_evidence_manifest.git_value", no_ancestor)
    assert "not an ancestor" in attestation_chain("implementation", "attestation")[0]


def test_dependency_contract_reports_exact_missing_and_mismatch(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("alpha[extra]==1.0\nbeta==2.0\ngamma==3.0\n")

    def installed(package: str) -> str:
        if package == "alpha":
            return "1.0"
        if package == "beta":
            return "2.1"
        raise PackageNotFoundError(package)

    monkeypatch.setattr("scripts.build_evidence_manifest.importlib.metadata.version", installed)
    result = dependency_versions(requirements)
    assert [item["status"] for item in result] == ["exact", "mismatch", "missing"]
    assert result[0]["package"] == "alpha"


def test_protocol_benchmark_uses_canonical_protobuf_payload():
    payload = _benchmark_payload(timestamp_ms=1_750_000_000_000)
    decoded = vitals_pb2.VitalSign.FromString(payload)
    assert decoded.schema_version
    assert decoded.pipeline_version
    assert decoded.scenario_id == "protocol_benchmark"
    assert _wire_overhead_table()[0]["payload_bytes"] == len(payload)


def test_latency_summary_is_aggregate_and_marks_unavailable():
    assert percentile([4.0, 1.0, 3.0, 2.0], 0.50) == 2.0
    row = summarize("publish_to_storage", [], "unexecuted", "not requested")
    assert row["count"] == 0
    assert row["p99_ms"] is None
    assert row["method"] == "unavailable"


def test_scale_outputs_include_non_identifying_machine_context(tmp_path):
    context = machine_context()
    assert "hostname" not in context
    result = {
        "tier": "T1",
        "status": "executed",
        "target_rate_msg_s": 30.0,
        "achieved_rate_msg_s": 29.5,
        "p50_latency_ms": 10.0,
        "p99_latency_ms": 20.0,
        "backlog_messages": 0,
        "duration_s": 1.0,
        "patients": 6,
        "signal_rate_hz": 1.0,
        "pull_timeout_s": 0.1,
        "measured_at_utc": "2026-01-01T00:00:00+00:00",
        "machine": context,
    }
    csv_path, json_path = tmp_path / "scale.csv", tmp_path / "scale.json"
    write_result(result, csv_path, json_path)
    assert list(csv.DictReader(csv_path.open()))[0]["status"] == "executed"
    assert json.loads(json_path.read_text())["machine"] == context
