#!/usr/bin/env python3
"""Run and retain the governed NATS/MQTT fault matrix.

Live broker control is intentionally supplied by an operator-approved adapter
module. The module must expose async ``create_nats_adapter(args)`` and
``create_mqtt_adapter(args)`` factories returning the FaultAdapter contract.
This runner never substitutes an in-memory simulation for a requested live run.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.protocol_fault_harness import run_pair

REQUIRED_TRANSPORTS = {"nats", "mqtt"}
REQUIRED_SCENARIOS = {
    "controlled_disconnect",
    "broker_restart_during_traffic",
    "offline_durable_recovery",
}


def _validate_results(results: list[dict]) -> tuple[str, list[str]]:
    errors: list[str] = []
    cells = {(row.get("transport"), row.get("scenario")) for row in results}
    expected = {(transport, scenario) for transport in REQUIRED_TRANSPORTS for scenario in REQUIRED_SCENARIOS}
    missing_cells = sorted(expected - cells)
    unexpected_cells = sorted(cells - expected)
    if missing_cells:
        errors.append(f"missing matrix cells: {missing_cells}")
    if unexpected_cells:
        errors.append(f"unexpected matrix cells: {unexpected_cells}")
    if len(cells) != len(results):
        errors.append("duplicate transport/scenario cells")
    for row in results:
        accounting = row.get("accounting") or {}
        if accounting.get("missing", 1) != 0:
            errors.append(f"{row.get('transport')}/{row.get('scenario')} has missing deliveries")
        if row.get("timed_out") is not False:
            errors.append(f"{row.get('transport')}/{row.get('scenario')} timed out")
    return ("passed" if not errors else "failed"), errors


def build_evidence(results: list[dict], *, messages: int, provenance: dict) -> dict:
    status, errors = _validate_results(results)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "record_count": len(results),
        "privacy_classification": "aggregate synthetic delivery and resource counters; no payloads, identifiers, credentials, endpoints, or hostnames",
        "messages_per_scenario": messages,
        "required_transports": sorted(REQUIRED_TRANSPORTS),
        "required_scenarios": sorted(REQUIRED_SCENARIOS),
        "validation_errors": errors,
        "provenance": provenance,
        "results": results,
    }


def write_atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _execute(args: argparse.Namespace) -> list[dict]:
    if not args.live:
        raise RuntimeError("fault evidence requires --live; simulation cannot satisfy the live matrix")
    if not args.adapter_module:
        raise RuntimeError("--live requires an operator-approved --adapter-module")
    module = importlib.import_module(args.adapter_module)
    for name in ("create_nats_adapter", "create_mqtt_adapter"):
        if not callable(getattr(module, name, None)):
            raise RuntimeError(f"adapter module must expose async {name}(args)")
    nats = await module.create_nats_adapter(args)
    mqtt = await module.create_mqtt_adapter(args)
    return await run_pair(nats, mqtt, args.messages, settle_timeout_s=args.timeout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--adapter-module", help="approved module containing live adapter factories")
    parser.add_argument("--messages", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--config", type=Path, help="non-secret frozen experiment configuration")
    parser.add_argument("--implementation-commit", required=True)
    parser.add_argument("--output", type=Path, default=Path("evidence/nats_mqtt_fault_matrix.json"))
    args = parser.parse_args()
    if args.messages < 2 or args.timeout <= 0:
        parser.error("--messages must be at least 2 and --timeout must be positive")
    if args.config and not args.config.is_file():
        parser.error("--config must identify a readable non-secret file")
    try:
        results = asyncio.run(_execute(args))
    except Exception as exc:
        parser.exit(2, f"Fault matrix was not executed: {type(exc).__name__}: {exc}\n")
    provenance = {
        "implementation_commit": args.implementation_commit,
        "adapter_module": args.adapter_module,
        "config_sha256": _file_hash(args.config) if args.config else None,
        "python_version": platform.python_version(),
        "platform": platform.system(),
    }
    evidence = build_evidence(results, messages=args.messages, provenance=provenance)
    write_atomic_json(args.output, evidence)
    print(f"Wrote {evidence['status']} fault matrix to {args.output}")
    if evidence["status"] != "passed":
        parser.exit(2, "Fault matrix failed validation; retained result remains non-passing.\n")


if __name__ == "__main__":
    main()
