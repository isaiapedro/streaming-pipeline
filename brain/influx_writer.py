"""Durable, batched async writer to InfluxDB.

``enqueue_many`` commits records to a local SQLite WAL before returning. That
commit is the broker acknowledgement boundary. Influx delivery is asynchronous;
failed writes remain in the outbox and are retried after restart. A replay after
an ambiguous remote success is safe because each point has deterministic tags
and timestamp, which form InfluxDB's idempotent point identity.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client import Point

from config.settings import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    INFLUX_TIMEOUT_MS,
    FLUSH_INTERVAL_S, FLUSH_BUFFER_SIZE, INFLUX_OUTBOX_PATH,
    INFLUX_OUTBOX_MAX_RECORDS, INFLUX_OUTBOX_MAX_ATTEMPTS,
    INFLUX_RETRY_BASE_S, INFLUX_RETRY_MAX_S,
)

log = logging.getLogger(__name__)
_SAFE_ERROR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?::status=[0-9]{3})?$")


def _safe_error_code(error: Exception) -> str:
    """Return bounded diagnostic metadata without persisting remote text."""
    name = type(error).__name__
    status = getattr(error, "status", None) or getattr(error, "status_code", None)
    return f"{name}:status={int(status)}" if isinstance(status, int) else name


def _is_retryable_error(error: Exception) -> bool:
    """Classify remote failures without inspecting or retaining error text."""
    status = getattr(error, "status", None) or getattr(error, "status_code", None)
    if not isinstance(status, int):
        return True
    return status in {408, 409, 425, 429} or status >= 500


def _require_metadata(**values: str) -> None:
    for name, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")


@dataclass
class VitalRecord:
    patient_id:  str
    signal_type: str
    condition:   str
    alarm_level: str
    value:       float
    timestamp_ms: int
    schema_version: str
    pipeline_version: str
    threshold_version: str
    scoring_approach: str = "A"
    scenario_id: str = "none"
    transport: str = "nats"

    def __post_init__(self) -> None:
        _require_metadata(
            schema_version=self.schema_version,
            pipeline_version=self.pipeline_version,
            threshold_version=self.threshold_version,
            scoring_approach=self.scoring_approach,
            scenario_id=self.scenario_id,
            transport=self.transport,
        )


@dataclass
class AlarmRecord:
    """Composite NEWS2 alarm event (Approach B/C) — separate measurement from
    per-signal vitals since it carries an aggregate score, not a raw reading.
    """
    patient_id:  str
    condition:   str
    alarm_level: str
    scoring_approach: str
    news2_score: int
    scenario_id: str
    timestamp_ms: int
    schema_version: str
    pipeline_version: str
    threshold_version: str
    transport: str = "nats"
    window_complete: bool = True

    def __post_init__(self) -> None:
        _require_metadata(
            schema_version=self.schema_version,
            pipeline_version=self.pipeline_version,
            threshold_version=self.threshold_version,
            scoring_approach=self.scoring_approach,
            scenario_id=self.scenario_id,
            transport=self.transport,
        )


class OutboxFullError(RuntimeError):
    """Raised before a transaction when the bounded durable queue is full."""


Record = VitalRecord | AlarmRecord


class InfluxWriter:
    def __init__(
        self,
        *,
        outbox_path: str | Path = INFLUX_OUTBOX_PATH,
        max_records: int = INFLUX_OUTBOX_MAX_RECORDS,
        max_attempts: int = INFLUX_OUTBOX_MAX_ATTEMPTS,
    ) -> None:
        self._outbox_path = Path(outbox_path)
        self._max_records = max_records
        self._max_attempts = max_attempts
        self._lock = asyncio.Lock()
        self._flush_lock = asyncio.Lock()
        self._client: InfluxDBClientAsync | None = None
        self._task:   asyncio.Task | None = None
        self._db: sqlite3.Connection | None = None

    async def start(self) -> None:
        if not INFLUX_TOKEN or not INFLUX_URL or not INFLUX_ORG or not INFLUX_BUCKET:
            raise RuntimeError(
                "Missing InfluxDB config — set INFLUX_URL/INFLUX_TOKEN/INFLUX_ORG/INFLUX_BUCKET "
                "in workspace/academic/.env (see .env for setup notes)."
            )
        self._open_outbox()
        self._client = InfluxDBClientAsync(
            url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=INFLUX_TIMEOUT_MS,
        )
        self._task = asyncio.create_task(self._flush_loop(), name="influx-flush")
        log.info(
            "InfluxWriter started (durable outbox configured; pending=%d flush=%ss batch=%d)",
            self.pending_count, FLUSH_INTERVAL_S, FLUSH_BUFFER_SIZE,
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # One forced attempt is bounded: failure leaves records durably queued
        # for the next process start instead of making shutdown hang or drop.
        await self._flush(force=True)
        try:
            if self._client:
                await self._client.close()
        finally:
            pending = self.pending_count
            if self._db:
                self._db.close()
                self._db = None
        log.info("InfluxWriter stopped (pending durable records=%d).", pending)

    async def enqueue(self, record: Record) -> None:
        await self.enqueue_many([record])

    async def enqueue_many(
        self,
        records: Iterable[Record],
        *,
        source_message_id: str | None = None,
    ) -> bool:
        """Atomically persist a source's records; return false for a redelivery."""
        batch = list(records)
        if not batch:
            return True
        async with self._lock:
            db = self._require_db()
            source_key = _source_key(source_message_id) if source_message_id else None
            if source_key and db.execute(
                "SELECT 1 FROM source_receipts WHERE source_key=?", (source_key,)
            ).fetchone():
                return False
            current = self._pending_count(db)
            encoded = [
                _encode_record(record, source_key=source_key, record_index=index)
                for index, record in enumerate(batch)
            ]
            new_keys = {item[0] for item in encoded}
            existing = 0
            if new_keys:
                placeholders = ",".join("?" for _ in new_keys)
                existing = db.execute(
                    f"SELECT COUNT(*) FROM outbox WHERE event_key IN ({placeholders})",
                    tuple(new_keys),
                ).fetchone()[0]
            additions = len(new_keys) - existing
            if current + additions > self._max_records:
                raise OutboxFullError(
                    f"Influx outbox capacity {self._max_records} would be exceeded; message remains unacked"
                )
            with db:
                before = db.total_changes
                db.executemany(
                    """INSERT OR IGNORE INTO outbox
                       (event_key, record_type, payload, created_at_ms, attempts, next_attempt_ms)
                       VALUES (?, ?, ?, ?, 0, 0)""",
                    [(key, kind, payload, int(time.time() * 1000)) for key, kind, payload in encoded],
                )
                inserted = db.total_changes - before
                if source_key:
                    db.execute(
                        "INSERT INTO source_receipts (source_key, accepted_at_ms) VALUES (?, ?)",
                        (source_key, int(time.time() * 1000)),
                    )
                    self._increment_counter(db, "accepted_source_messages", 1)
                self._increment_counter(db, "derived_records_enqueued", inserted)
            should_flush = self._pending_count(db) >= FLUSH_BUFFER_SIZE
        if should_flush:
            await self._flush()
        return True

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_S)
            await self._flush()

    async def _flush(self, *, force: bool = False) -> None:
        # Only one remote write may own a batch at a time. Enqueues remain free
        # to commit while the network call is in flight.
        async with self._flush_lock:
            async with self._lock:
                db = self._require_db()
                now_ms = int(time.time() * 1000)
                where = "" if force else "WHERE next_attempt_ms <= ?"
                params = () if force else (now_ms,)
                rows = db.execute(
                    f"SELECT id, record_type, payload, attempts FROM outbox {where} ORDER BY id LIMIT ?",
                    (*params, FLUSH_BUFFER_SIZE),
                ).fetchall()
                if not rows:
                    return
            points = [_to_point(_decode_record(kind, payload)) for _, kind, payload, _ in rows]
            try:
                if self._client is None:
                    raise RuntimeError("InfluxWriter is not started")
                write_api = self._client.write_api()
                await write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
                ids = [row[0] for row in rows]
                async with self._lock:
                    db = self._require_db()
                    placeholders = ",".join("?" for _ in ids)
                    with db:
                        db.execute(f"DELETE FROM outbox WHERE id IN ({placeholders})", ids)
                        self._increment_counter(db, "delivered_records", len(ids))
                log.debug("Flushed %d records to InfluxDB", len(points))
            except Exception as exc:
                retryable = _is_retryable_error(exc)
                error_code = _safe_error_code(exc)
                quarantined = 0
                async with self._lock:
                    db = self._require_db()
                    with db:
                        for row_id, kind, payload, attempts in rows:
                            next_attempt = attempts + 1
                            if not retryable or next_attempt >= self._max_attempts:
                                db.execute(
                                    """INSERT OR REPLACE INTO outbox_quarantine
                                       (event_key, record_type, payload, attempts, error_code, quarantined_at_ms)
                                       SELECT event_key, record_type, payload, ?, ?, ? FROM outbox WHERE id=?""",
                                    (next_attempt, error_code, now_ms, row_id),
                                )
                                db.execute("DELETE FROM outbox WHERE id=?", (row_id,))
                                quarantined += 1
                                continue
                            retry_s = min(
                                INFLUX_RETRY_MAX_S,
                                INFLUX_RETRY_BASE_S * (2 ** min(attempts, 30)),
                            )
                            db.execute(
                                "UPDATE outbox SET attempts=?, next_attempt_ms=?, last_error=? WHERE id=?",
                                (next_attempt, now_ms + int(retry_s * 1000), error_code, row_id),
                            )
                        if quarantined:
                            self._increment_counter(db, "quarantined_records", quarantined)
                retained = len(rows) - quarantined
                log.error(
                    "InfluxDB write failed (retained=%d quarantined=%d code=%s)",
                    retained, quarantined, error_code,
                )

    @property
    def pending_count(self) -> int:
        return self._pending_count(self._require_db())

    def _open_outbox(self) -> None:
        self._outbox_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._outbox_path.is_symlink():
            raise RuntimeError("INFLUX_OUTBOX_PATH must not be a symbolic link")
        try:
            os.chmod(self._outbox_path.parent, 0o700)
        except OSError:
            pass
        self._db = sqlite3.connect(self._outbox_path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA busy_timeout=5000")
        existing_tables = {
            row[0] for row in self._db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        accounting_complete = "outbox" not in existing_tables
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                record_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_ms INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            )"""
        )
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS source_receipts (
                source_key TEXT PRIMARY KEY,
                accepted_at_ms INTEGER NOT NULL
            )"""
        )
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS outbox_quarantine (
                event_key TEXT PRIMARY KEY,
                record_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                error_code TEXT NOT NULL,
                quarantined_at_ms INTEGER NOT NULL
            )"""
        )
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS outbox_counters (
                name TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )"""
        )
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS outbox_meta (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )"""
        )
        self._db.execute(
            "INSERT OR IGNORE INTO outbox_meta (name, value) VALUES ('accounting_started_at_ms', ?)",
            (str(int(time.time() * 1000)),),
        )
        self._db.execute(
            "INSERT OR IGNORE INTO outbox_meta (name, value) VALUES ('historical_accounting_complete', ?)",
            ("1" if accounting_complete else "0",),
        )
        # Earlier builds stored arbitrary exception text. Scrub legacy rows on
        # open so endpoints, query text, or credentials cannot survive locally.
        unsafe_error_ids = [
            row_id for row_id, error in self._db.execute(
                "SELECT id, last_error FROM outbox WHERE last_error IS NOT NULL"
            ).fetchall()
            if not _SAFE_ERROR_PATTERN.fullmatch(error)
        ]
        if unsafe_error_ids:
            with self._db:
                self._db.executemany(
                    "UPDATE outbox SET last_error='LegacyErrorRedacted' WHERE id=?",
                    [(row_id,) for row_id in unsafe_error_ids],
                )
        self._db.commit()
        integrity = self._db.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            self._db.close()
            self._db = None
            raise RuntimeError(f"Influx outbox integrity check failed: {integrity}")
        try:
            os.chmod(self._outbox_path, 0o600)
        except OSError:
            pass

    def _require_db(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError("InfluxWriter is not started")
        return self._db

    @staticmethod
    def _pending_count(db: sqlite3.Connection) -> int:
        return int(db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])

    @staticmethod
    def _increment_counter(db: sqlite3.Connection, name: str, amount: int) -> None:
        db.execute(
            """INSERT INTO outbox_counters (name, value) VALUES (?, ?)
               ON CONFLICT(name) DO UPDATE SET value=value+excluded.value""",
            (name, amount),
        )


def _source_key(source_message_id: str) -> str:
    if not isinstance(source_message_id, str) or not source_message_id.strip():
        raise ValueError("source_message_id must be a non-empty string")
    return hashlib.sha256(source_message_id.encode()).hexdigest()


def _encode_record(
    record: Record,
    *,
    source_key: str | None = None,
    record_index: int = 0,
) -> tuple[str, str, str]:
    kind = "alarm" if isinstance(record, AlarmRecord) else "vital"
    payload = json.dumps(asdict(record), sort_keys=True, separators=(",", ":"), allow_nan=False)
    identity = f"source:{source_key}:record:{record_index}" if source_key else f"{kind}:{payload}"
    event_key = hashlib.sha256(identity.encode()).hexdigest()
    return event_key, kind, payload


def _decode_record(kind: str, payload: str) -> Record:
    values = json.loads(payload)
    if kind == "alarm":
        return AlarmRecord(**values)
    if kind == "vital":
        return VitalRecord(**values)
    raise ValueError(f"Unsupported outbox record type: {kind}")


def _to_point(r: "VitalRecord | AlarmRecord") -> Point:
    if isinstance(r, AlarmRecord):
        return (
            Point("alarms")
            .tag("patient_id",       r.patient_id)
            .tag("condition",        r.condition)
            .tag("alarm_level",      r.alarm_level)
            .tag("scoring_approach", r.scoring_approach)
            .tag("scenario_id",      r.scenario_id)
            .tag("schema_version",   r.schema_version)
            .tag("pipeline_version", r.pipeline_version)
            .tag("threshold_version", r.threshold_version)
            .tag("transport",        r.transport)
            .field("news2_score",    r.news2_score)
            .field("window_complete", r.window_complete)
            .time(r.timestamp_ms * 1_000_000)
        )
    return (
        Point("patient_vitals")
        .tag("patient_id",       r.patient_id)
        .tag("signal_type",      r.signal_type)
        .tag("condition",        r.condition)
        .tag("alarm_level",      r.alarm_level)
        .tag("scoring_approach", r.scoring_approach)
        .tag("scenario_id",      r.scenario_id)
        .tag("schema_version",   r.schema_version)
        .tag("pipeline_version", r.pipeline_version)
        .tag("threshold_version", r.threshold_version)
        .tag("transport",        r.transport)
        .field("value",          r.value)
        .time(r.timestamp_ms * 1_000_000)   # ms → ns for InfluxDB line protocol
    )
