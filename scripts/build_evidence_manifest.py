#!/usr/bin/env python3
"""Freeze reproducibility context for the privacy-safe evidence bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.scenarios.definitions import SCENARIOS
from scripts.run_benchmark import DEFAULT_NOISE_SEEDS, DEFAULT_SIGNAL_SEEDS, DEFAULT_STABLE_DURATION_S

ROOT = Path(__file__).parent.parent
TIERS = {"T1": (6, 1.0), "T2": (24, 100.0), "T3": (50, 250.0), "T4": (100, 250.0)}


def machine_context() -> dict:
    """Capture non-identifying machine context without importing live transports."""
    try:
        memory_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        memory_bytes = None
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "memory_bytes": memory_bytes,
        "python_version": platform.python_version(),
    }


def git_value(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def attestation_chain(implementation_commit: str | None, attestation_commit: str) -> list[str]:
    """Validate that HEAD only adds publishable evidence to the measured code."""

    if not implementation_commit:
        return ["run log does not identify one implementation commit"]
    try:
        git_value("merge-base", "--is-ancestor", implementation_commit, attestation_commit)
    except subprocess.CalledProcessError:
        return ["run-log implementation commit is not an ancestor of the attestation commit"]
    changed = git_value("diff", "--name-only", f"{implementation_commit}..{attestation_commit}").splitlines()
    unexpected = sorted(path for path in changed if not path.startswith("evidence/"))
    if unexpected:
        return [
            "implementation-to-attestation history changes non-evidence paths: "
            + ", ".join(unexpected)
        ]
    return []


def dependency_versions(requirements: Path) -> list[dict]:
    output = []
    for line in requirements.read_text().splitlines():
        declaration = line.strip()
        if not declaration or declaration.startswith("#"):
            continue
        requirement_name, separator, expected_version = declaration.partition("==")
        package = requirement_name.partition("[")[0]
        try:
            installed = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if not separator:
            status = "unpinned"
        elif installed is None:
            status = "missing"
        elif installed != expected_version:
            status = "mismatch"
        else:
            status = "exact"
        output.append({
            "requirement": declaration,
            "package": package,
            "expected_version": expected_version if separator else None,
            "installed_version": installed,
            "status": status,
        })
    return output


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _artifact(path: Path, record_count: int | None = None, role: str = "supporting_evidence") -> dict:
    return {
        "path": _display_path(path),
        "role": role,
        "exists": path.is_file(),
        "sha256": file_sha256(path) if path.is_file() else None,
        "record_count": record_count,
    }


def evidence_inventory(evidence_dir: Path) -> list[dict]:
    """Hash publishable inputs and outputs without creating a manifest hash cycle."""

    roles = {
        "experiment_runs.jsonl": "run_provenance",
        "benchmark_aggregate.csv": "derived_aggregate",
        "FIGURE_CAPTIONS.md": "figure_captions",
    }
    inventory = []
    for path in sorted(evidence_dir.rglob("*")):
        if not path.is_file() or path.name in {".gitkeep", "manifest.json", "SHA256SUMS"}:
            continue
        relative = path.relative_to(evidence_dir).as_posix()
        role = roles.get(relative, "figure" if relative.startswith("figures/") else "supporting_evidence")
        inventory.append({"path": f"evidence/{relative}", "role": role, "sha256": file_sha256(path)})
    return inventory


def benchmark_artifacts(
    benchmark_path: Path,
    run_log_path: Path,
    expected_commit: str | None = None,
) -> dict:
    """Describe and cross-check the raw benchmark and one-record-per-cell log."""

    errors: list[str] = []
    rows: list[dict] = []
    logs: list[dict] = []
    benchmark_schema_valid = False
    if benchmark_path.is_file():
        with benchmark_path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"run_id", "scenario", "signal_seed", "noise_seed", "approach", "duration_s"}
            missing = required.difference(reader.fieldnames or ())
            if missing:
                errors.append(f"raw benchmark is missing columns: {', '.join(sorted(missing))}")
            else:
                benchmark_schema_valid = True
            rows = list(reader)
    else:
        errors.append(f"missing raw benchmark: {_display_path(benchmark_path)}")
    if run_log_path.is_file():
        with run_log_path.open() as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    errors.append(f"invalid run-log JSON at line {line_number}: {exc.msg}")
    else:
        errors.append(f"missing run log: {_display_path(run_log_path)}")

    expected_scenarios = set(SCENARIOS)
    expected_approaches = {"A", "B", "C"}
    expected_cells = len(expected_scenarios) * len(DEFAULT_SIGNAL_SEEDS) * len(DEFAULT_NOISE_SEEDS)
    expected_rows = expected_cells * len(expected_approaches)
    if rows and benchmark_schema_valid:
        if len(rows) != expected_rows:
            errors.append(f"raw benchmark has {len(rows)} rows; expected {expected_rows}")
        if {row.get("scenario") for row in rows} != expected_scenarios:
            errors.append("raw benchmark scenario set does not match the registered scenario set")
        if {row.get("approach") for row in rows} != expected_approaches:
            errors.append("raw benchmark approach set must be exactly A/B/C")
        expected_pairs = {(str(signal), str(noise)) for signal in DEFAULT_SIGNAL_SEEDS for noise in DEFAULT_NOISE_SEEDS}
        for scenario in sorted(expected_scenarios):
            for approach in sorted(expected_approaches):
                observed_pairs = {
                    (row.get("signal_seed"), row.get("noise_seed"))
                    for row in rows
                    if row.get("scenario") == scenario and row.get("approach") == approach
                }
                if observed_pairs != expected_pairs:
                    errors.append(f"{scenario}/{approach} does not have the complete 5x5 seed matrix")
        for scenario_id, scenario in SCENARIOS.items():
            required_duration = DEFAULT_STABLE_DURATION_S if scenario_id == "stable_baseline" else int(scenario.duration_s)
            try:
                observed_durations = {
                    int(float(row["duration_s"])) for row in rows
                    if row.get("scenario") == scenario_id and row.get("duration_s")
                }
            except ValueError:
                errors.append(f"{scenario_id} contains a non-numeric duration_s")
                continue
            if observed_durations != {required_duration}:
                errors.append(
                    f"{scenario_id} duration is {sorted(observed_durations)} seconds; "
                    f"final protocol requires {required_duration}"
                )

    if logs:
        if len(logs) != expected_cells:
            errors.append(f"run log has {len(logs)} records; expected {expected_cells}")
        if {row.get("run_id") for row in rows} != {entry.get("run_id") for entry in logs}:
            errors.append("raw benchmark and run log contain different run_id sets")
        if any(entry.get("status") != "completed" for entry in logs):
            errors.append("run log contains incomplete or failed cells")
        if any(entry.get("worktree_dirty") is not False for entry in logs):
            errors.append("run log was generated from a dirty or unknown worktree")
        observed_commits = {entry.get("git_commit") for entry in logs}
        if len(observed_commits) != 1 or None in observed_commits:
            errors.append("run log must identify exactly one implementation commit")
        if expected_commit is not None and observed_commits != {expected_commit}:
            errors.append("run log commit does not match the measured implementation commit")

    return {
        "raw_benchmark": _artifact(
            benchmark_path, len(rows) if benchmark_path.is_file() else None, "raw_benchmark_input"
        ),
        "run_log": _artifact(run_log_path, len(logs) if run_log_path.is_file() else None, "run_provenance"),
        "expected_raw_rows": expected_rows,
        "expected_run_records": expected_cells,
        "validation_status": "valid" if not errors else "development_only",
        "validation_errors": errors,
    }


def build_manifest(
    reference_source_id: str | None,
    transformation_method: str | None,
    release_mode: str = "development",
    benchmark_path: Path | None = None,
    run_log_path: Path | None = None,
) -> dict:
    if release_mode not in {"development", "final"}:
        raise ValueError("release_mode must be 'development' or 'final'")
    requirements = ROOT / "requirements.txt"
    dirty = bool(git_value("status", "--porcelain"))
    commit = git_value("rev-parse", "HEAD")
    run_log = run_log_path or ROOT / "evidence" / "experiment_runs.jsonl"
    implementation_commit = None
    if run_log.is_file():
        commits = {
            json.loads(line).get("git_commit")
            for line in run_log.read_text().splitlines()
            if line.strip()
        }
        if len(commits) == 1:
            implementation_commit = next(iter(commits))
    dependencies = dependency_versions(requirements)
    dependency_issues = [item for item in dependencies if item["status"] != "exact"]
    artifact_context = benchmark_artifacts(
        benchmark_path or ROOT / "benchmark_results.csv",
        run_log,
        implementation_commit,
    )
    blockers = list(artifact_context["validation_errors"])
    blockers.extend(attestation_chain(implementation_commit, commit))
    if dirty:
        blockers.append("worktree is dirty")
    if dependency_issues:
        blockers.append("installed environment does not exactly match every pinned requirement")
    scale_by_tier = {}
    scale_path = ROOT / "evidence" / "scale_results.csv"
    if scale_path.exists():
        with scale_path.open(newline="") as handle:
            scale_by_tier = {row["tier"]: row for row in csv.DictReader(handle)}
    protocol_path = ROOT / "evidence" / "protocol_benchmark.csv"
    latency_path = ROOT / "evidence" / "live_latency.json"
    traceability_path = ROOT / "evidence" / "traceability_audit.json"
    outbox_health_path = ROOT / "evidence" / "outbox_health.json"
    traceability_status = "unexecuted"
    if traceability_path.exists():
        try:
            traceability_status = json.loads(traceability_path.read_text()).get("status", "invalid")
        except (OSError, json.JSONDecodeError):
            traceability_status = "invalid"
    return {
        "manifest_version": 4,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "privacy_classification": "aggregate and seed-level synthetic experimental evidence; no raw vital values, clinical rows, credentials, hostnames, or Personal-domain data",
        "code": {
            "implementation_commit": implementation_commit,
            "attestation_base_commit": commit,
            "worktree_dirty": dirty,
            "note": "The implementation commit produced the run log; the attestation base may add evidence/ artifacts only.",
        },
        "release": {
            "requested_mode": release_mode,
            "eligible_for_final_release": not blockers,
            "blockers": blockers,
            "policy": "Development mode records blockers; final mode exits without overwriting the manifest when any blocker exists.",
        },
        "runtime": {
            "python": platform.python_version(),
            "requirements_sha256": file_sha256(requirements),
            "dependencies": dependencies,
            "dependency_validation": {
                "status": "exact" if not dependency_issues else "mismatch",
                "issue_count": len(dependency_issues),
                "issues": [item["requirement"] for item in dependency_issues],
            },
            "machine": machine_context(),
        },
        "benchmark": {
            "scenario_set": [
                {
                    "scenario_id": scenario.scenario_id,
                    "duration_s": DEFAULT_STABLE_DURATION_S if scenario.scenario_id == "stable_baseline" else scenario.duration_s,
                    "onset_offset_ms": scenario.onset_offset_ms,
                    "expect_alarm": scenario.expect_alarm,
                }
                for scenario in SCENARIOS.values()
            ],
            "signal_seeds": list(DEFAULT_SIGNAL_SEEDS),
            "noise_seeds": list(DEFAULT_NOISE_SEEDS),
            "design": "fully crossed 5 x 5 signal/noise seeds; identical cells for A/B/C",
            "approaches": ["A", "B", "C"],
            "expected_source_rows": 450,
            "artifacts": artifact_context,
            "publishable_artifacts": evidence_inventory(ROOT / "evidence"),
            "alarm_episode_definition": "opens on first alarming observation; closes after 10 seconds continuously clear",
            "detection_definition": "first newly opened alarm episode at or after ground-truth onset",
            "confidence_interval": "Wilson 95% interval for run probabilities; deterministic 2,000-resample bootstrap 95% interval for metric means",
        },
        "scale_tiers": [
            ({
                "tier": tier,
                "patients": patients,
                "signal_rate_hz": hz,
                "target_rate_msg_s": patients * hz * 5,
                "status": "unexecuted",
                "reason": "Run on approved hardware and replace status only with generated CSV/JSON evidence.",
            } | ({
                "status": scale_by_tier[tier]["status"],
                "achieved_rate_msg_s": float(scale_by_tier[tier]["achieved_rate_msg_s"]),
                "p50_latency_ms": float(scale_by_tier[tier]["p50_latency_ms"]),
                "p99_latency_ms": float(scale_by_tier[tier]["p99_latency_ms"]),
                "backlog_messages": int(scale_by_tier[tier]["backlog_messages"]),
                "duration_s": float(scale_by_tier[tier]["duration_s"]),
                "reason": "Generated by scripts/run_scale_tier.py; full machine context is in the tier JSON.",
            } if tier in scale_by_tier else {}))
            for tier, (patients, hz) in TIERS.items()
        ],
        "live_experiments": {
            "protocol": {
                "status": "executed_partial" if protocol_path.exists() else "unexecuted",
                "artifact": "evidence/protocol_benchmark.csv" if protocol_path.exists() else None,
                "restart_dependent_dimensions": "unavailable (--skip-restarts)",
            },
            "pipeline_latency": {
                "status": "executed_partial" if latency_path.exists() else "unexecuted",
                "artifact": "evidence/live_latency.json" if latency_path.exists() else None,
                "storage_latency": "unexecuted (--skip-storage)",
            },
            "benchmark_run_provenance": {
                "status": "executed" if (ROOT / "evidence/experiment_runs.jsonl").exists() else "unexecuted",
                "artifact": "evidence/experiment_runs.jsonl",
                "records_expected": 150,
                "contains_raw_vitals": False,
            },
            "stored_traceability_audit": {
                "status": traceability_status,
                "artifact": "evidence/traceability_audit.json" if traceability_path.exists() else None,
                "privacy": "aggregate tag-presence counts only",
            },
            "outbox_health_audit": {
                "status": "executed" if outbox_health_path.exists() else "unexecuted",
                "artifact": "evidence/outbox_health.json" if outbox_health_path.exists() else None,
                "privacy": "aggregate SQLite health only",
            },
        },
        "compliance_controls": {
            "runtime_log_redaction": {"status": "implemented_and_tested", "test": "brain/tests/test_compliance_tools.py"},
            "dashboard_semantic_validation": {"status": "offline_tested", "live_render": "unexecuted"},
            "alert_delivery": {"status": "unexecuted", "reason": "approved destination required"},
            "credential_rotation": {"status": "owner_confirmation_pending"},
            "retention_policy": {"status": "owner_approval_pending"},
        },
        "distribution_reference": {
            "approved_source_id": reference_source_id,
            "transformation_method": transformation_method,
            "source_rows_committed": False,
            "metric": "KL(P_synthetic || P_reference) over 30 shared histogram bins with additive smoothing epsilon=1e-12",
            "direction": "synthetic_to_reference",
            "status": "configured" if reference_source_id and transformation_method else "unexecuted",
        },
        "commands": {
            "benchmark_raw": "python3 scripts/run_benchmark.py --signal-seeds 5 --noise-seeds 5 --stable-duration-s 86400 --out benchmark_results.csv --run-log evidence/experiment_runs.jsonl",
            "benchmark_aggregate": "python scripts/aggregate_benchmark.py --input benchmark_results.csv --output evidence/benchmark_aggregate.csv --figures-dir evidence/figures",
            "protocol": "python scripts/benchmark_protocol.py --n 100 --out evidence/protocol_benchmark.csv --skip-restarts",
            "live_latency": "python scripts/measure_live_latency.py --count 100 --skip-storage --csv-out evidence/live_latency.csv --json-out evidence/live_latency.json",
            "scale_tier": "python scripts/run_scale_tier.py --tier T1 --duration 10 --pull-timeout 0.1 --nats-url nats://localhost:4222 --csv-out evidence/scale_results.csv --json-out evidence/scale_T1.json",
            "distribution": "python scripts/validate_distributions.py --reference /approved/external/reference.csv --synthetic /approved/external/synthetic.csv --source-id SOURCE_ID --transformation-method METHOD --out-dir evidence/distribution",
            "development_manifest": "python3 scripts/build_evidence_manifest.py --mode development",
            "final_manifest": "python3 scripts/build_evidence_manifest.py --mode final",
            "checksums": "python3 scripts/build_evidence_manifest.py --checksum-only",
            "evidence_status_figure": "MPLCONFIGDIR=/tmp/matplotlib-academic python3 scripts/generate_evidence_status.py",
            "traceability_audit_export": "python3 scripts/audit_traceability.py --input-csv /approved/export.csv --output evidence/traceability_audit.json --require-complete",
            "traceability_audit_live": "python3 scripts/audit_traceability.py --live --range 1h --output evidence/traceability_audit.json --require-complete",
            "outbox_health": "python3 scripts/audit_outbox.py --database .runtime/influx_outbox.sqlite3 --output evidence/outbox_health.json --require-healthy",
            "tests": "python3 -m pytest -q",
        },
    }


def write_checksums(evidence_dir: Path) -> None:
    target = evidence_dir / "SHA256SUMS"
    files = sorted(
        path for path in evidence_dir.rglob("*")
        if path.is_file() and path != target and path.name != ".gitkeep"
    )
    lines = [f"{file_sha256(path)}  {path.relative_to(evidence_dir).as_posix()}" for path in files]
    target.write_text("\n".join(lines) + ("\n" if lines else ""))


def enforce_final_release(manifest: dict) -> None:
    """Refuse to publish evidence that cannot be independently reproduced."""

    blockers = manifest["release"]["blockers"]
    if blockers:
        formatted = "\n - ".join(blockers)
        raise RuntimeError(f"Final evidence release refused:\n - {formatted}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evidence/manifest.json"))
    parser.add_argument("--reference-source-id")
    parser.add_argument("--transformation-method")
    parser.add_argument("--mode", choices=("development", "final"), default="development")
    parser.add_argument("--benchmark-input", type=Path, default=ROOT / "benchmark_results.csv")
    parser.add_argument("--run-log", type=Path, default=ROOT / "evidence" / "experiment_runs.jsonl")
    parser.add_argument("--checksum-only", action="store_true")
    args = parser.parse_args()
    if args.checksum_only:
        write_checksums(args.output.parent)
        return
    manifest = build_manifest(
        args.reference_source_id,
        args.transformation_method,
        args.mode,
        args.benchmark_input,
        args.run_log,
    )
    if args.mode == "final":
        try:
            enforce_final_release(manifest)
        except RuntimeError as exc:
            parser.exit(2, f"{exc}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    write_checksums(args.output.parent)
    print(f"Wrote evidence manifest and checksums under {args.output.parent}")


if __name__ == "__main__":
    main()
