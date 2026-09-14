#!/usr/bin/env python3
"""Reconcile aggregate source, outbox, delivery, and Influx record counts."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def reconcile_storage(database_path: Path, stored_records: int | None) -> dict:
    resolved = database_path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError("outbox database does not exist")
    database = sqlite3.connect(f"file:{quote(str(resolved))}?mode=ro", uri=True)
    try:
        integrity = database.execute("PRAGMA quick_check").fetchone()[0]
        tables = {
            row[0] for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required_tables = {
            "outbox", "outbox_quarantine", "source_receipts",
            "outbox_counters", "outbox_meta",
        }
        missing_tables = sorted(required_tables - tables)
        pending = int(database.execute(
            "SELECT COUNT(*) FROM outbox"
        ).fetchone()[0]) if "outbox" in tables else 0
        quarantined = int(database.execute(
            "SELECT COUNT(*) FROM outbox_quarantine"
        ).fetchone()[0]) if "outbox_quarantine" in tables else 0
        receipts = int(database.execute(
            "SELECT COUNT(*) FROM source_receipts"
        ).fetchone()[0]) if "source_receipts" in tables else 0
        counters = dict(database.execute(
            "SELECT name, value FROM outbox_counters"
        ).fetchall()) if "outbox_counters" in tables else {}
        metadata = dict(database.execute(
            "SELECT name, value FROM outbox_meta"
        ).fetchall()) if "outbox_meta" in tables else {}
    finally:
        database.close()

    accepted = int(counters.get("accepted_source_messages", 0))
    enqueued = int(counters.get("derived_records_enqueued", 0))
    delivered = int(counters.get("delivered_records", 0))
    quarantined_counter = int(counters.get("quarantined_records", 0))
    outbox_balance_ok = enqueued == delivered + pending + quarantined
    receipt_balance_ok = accepted == receipts
    quarantine_balance_ok = quarantined_counter == quarantined
    storage_balance_ok = stored_records is None or stored_records == delivered
    historical_accounting_complete = metadata.get("historical_accounting_complete") == "1"
    accounting_started_at_ms = metadata.get("accounting_started_at_ms")
    schema_compatible = not missing_tables and accounting_started_at_ms is not None
    complete = (
        integrity == "ok"
        and schema_compatible
        and historical_accounting_complete
        and outbox_balance_ok
        and receipt_balance_ok
        and quarantine_balance_ok
        and storage_balance_ok
        and pending == 0
        and quarantined == 0
        and stored_records is not None
    )
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "privacy_classification": "aggregate reconciliation; no payloads, identifiers, paths, or error text",
        "integrity": integrity,
        "accounting_started_at_ms": (
            int(accounting_started_at_ms) if accounting_started_at_ms is not None else None
        ),
        "schema_compatible": schema_compatible,
        "missing_tables": missing_tables,
        "historical_accounting_complete": historical_accounting_complete,
        "accepted_source_messages": accepted,
        "source_receipts": receipts,
        "derived_records_enqueued": enqueued,
        "pending_records": pending,
        "delivered_records": delivered,
        "quarantined_records": quarantined,
        "stored_records": stored_records,
        "checks": {
            "source_receipt_balance": receipt_balance_ok,
            "outbox_balance": outbox_balance_ok,
            "quarantine_balance": quarantine_balance_ok,
            "storage_balance": storage_balance_ok,
            "historical_accounting_complete": historical_accounting_complete,
            "schema_compatible": schema_compatible,
        },
        "status": "complete" if complete else "incomplete",
        "interpretation": (
            "Complete requires a database created with accounting enabled, an empty pending/quarantine "
            "queue, and an Influx count since accounting_started_at_ms equal to the delivered counter. "
            "Count one field per logical record: patient_vitals/value and alarms/news2_score."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--stored-count", type=int, required=True,
        help="Influx logical-record count for the same database lifetime",
    )
    parser.add_argument("--output", type=Path, default=Path("evidence/storage_reconciliation.json"))
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    if args.stored_count < 0:
        parser.error("--stored-count must be non-negative")
    result = reconcile_storage(args.database, args.stored_count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {result['status']} aggregate storage reconciliation to {args.output}")
    if args.require_complete and result["status"] != "complete":
        parser.exit(2, "Storage reconciliation is incomplete\n")


if __name__ == "__main__":
    main()
