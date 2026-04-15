"""Batched async writer to InfluxDB Cloud.

Records are buffered in memory and flushed every FLUSH_INTERVAL_S seconds
or when the buffer reaches FLUSH_BUFFER_SIZE entries — whichever comes first.
"""

import asyncio
import logging
from dataclasses import dataclass

from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client import Point

from config.settings import (
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    FLUSH_INTERVAL_S, FLUSH_BUFFER_SIZE,
)

log = logging.getLogger(__name__)


@dataclass
class VitalRecord:
    patient_id:  str
    signal_type: str
    condition:   str
    alarm_level: str
    value:       float
    timestamp_ms: int


class InfluxWriter:
    def __init__(self) -> None:
        self._buffer: list[VitalRecord] = []
        self._lock = asyncio.Lock()
        self._client: InfluxDBClientAsync | None = None
        self._task:   asyncio.Task | None = None

    async def start(self) -> None:
        self._client = InfluxDBClientAsync(
            url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG
        )
        self._task = asyncio.create_task(self._flush_loop(), name="influx-flush")
        log.info("InfluxWriter started (flush every %ss, max buffer %d)",
                 FLUSH_INTERVAL_S, FLUSH_BUFFER_SIZE)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._flush()          # drain remaining records
        if self._client:
            await self._client.close()
        log.info("InfluxWriter stopped.")

    async def enqueue(self, record: VitalRecord) -> None:
        async with self._lock:
            self._buffer.append(record)
            should_flush = len(self._buffer) >= FLUSH_BUFFER_SIZE
        if should_flush:
            await self._flush()

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_S)
            await self._flush()

    async def _flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            batch, self._buffer = self._buffer, []

        points = [_to_point(r) for r in batch]
        try:
            write_api = self._client.write_api()
            await write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
            log.debug("Flushed %d records to InfluxDB", len(points))
        except Exception as exc:
            log.error("InfluxDB write failed (%d records dropped): %s", len(batch), exc)


def _to_point(r: VitalRecord) -> Point:
    return (
        Point("patient_vitals")
        .tag("patient_id",  r.patient_id)
        .tag("signal_type", r.signal_type)
        .tag("condition",   r.condition)
        .tag("alarm_level", r.alarm_level)
        .field("value",     r.value)
        .time(r.timestamp_ms * 1_000_000)   # ms → ns for InfluxDB line protocol
    )
