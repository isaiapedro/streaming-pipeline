#!/usr/bin/env python3
"""Produce a privacy-safe, read-only health summary for the SQLite outbox."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def audit_outbox(path: Path, now_ms: int | None = None) -> dict:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError("outbox database does not exist")
    now_ms = int(time.time() * 1_000) if now_ms is None else now_ms
    uri = f"file:{quote(str(resolved))}?mode=ro"
    database = sqlite3.connect(uri, uri=True)
    try:
        integrity = database.execute("PRAGMA quick_check").fetchone()[0]
        pending, attempted, max_attempts, oldest, due = database.execute(
            """SELECT COUNT(*),
                      SUM(CASE WHEN attempts > 0 THEN 1 ELSE 0 END),
                      COALESCE(MAX(attempts), 0),
                      MIN(created_at_ms),
                      SUM(CASE WHEN next_attempt_ms <= ? THEN 1 ELSE 0 END)
               FROM outbox""",
            (now_ms,),
        ).fetchone()
    finally:
        database.close()
    mode = os.stat(resolved).st_mode & 0o777
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "privacy_classification": "aggregate outbox health; no payloads, identifiers, paths, or error text",
        "integrity": integrity,
        "pending_records": int(pending),
        "records_with_attempts": int(attempted or 0),
        "max_attempts": int(max_attempts),
        "due_records": int(due or 0),
        "oldest_record_age_ms": max(0, now_ms - int(oldest)) if oldest is not None else None,
        "database_bytes": resolved.stat().st_size,
        "private_file_mode": mode & 0o077 == 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("evidence/outbox_health.json"))
    parser.add_argument("--require-healthy", action="store_true")
    args = parser.parse_args()
    result = audit_outbox(args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Wrote aggregate outbox health for {result['pending_records']} pending records to {args.output}")
    if args.require_healthy and (result["integrity"] != "ok" or not result["private_file_mode"]):
        parser.exit(2, "Outbox health audit failed closed\n")


if __name__ == "__main__":
    main()
