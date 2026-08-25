"""Bidirectional cloud->edge config push — JetStream KV watch for hot-reload
of per-signal thresholds without restarting the brain service.

plan-detailed.md L2: cloud operator writes to JetStream KV bucket
`CONFIG`, key `thresholds` -> brain watches -> updates in-memory
`config.thresholds.SIGNAL_THRESHOLDS` in place. Per-alarm cloud
*suppression* (`brain/suppress.{patient_id}`) is part of the two-tier
local/cloud split architecture from `plan.md` that doesn't exist yet in
this single-service brain — out of scope here; threshold hot-reload only.

`config.thresholds.SIGNAL_THRESHOLDS` is mutated **in place** (`.clear()` +
`.update()`), not rebound — `brain/evaluator.py` holds a reference to the
same dict object via `from config.thresholds import SIGNAL_THRESHOLDS`, so
an in-place mutation is visible to it immediately without re-importing.
"""

import asyncio
import json
import logging
import time

from nats.js.api import KeyValueConfig

import config.thresholds as thresholds_module

log = logging.getLogger(__name__)

BUCKET = "CONFIG"
KEY = "thresholds"


async def get_or_create_bucket(js):
    try:
        return await js.key_value(BUCKET)
    except Exception:
        return await js.create_key_value(config=KeyValueConfig(bucket=BUCKET))


async def push_thresholds(js, new_thresholds: dict) -> None:
    """Cloud-operator-side helper: write updated thresholds to the KV bucket.

    Embeds a wall-clock `_pushed_at` timestamp in the payload so a watcher
    in another process can compute propagation latency (see
    `scripts/demo_config_push.py`) — not part of the threshold schema
    itself, stripped by the watcher before applying.
    """
    kv = await get_or_create_bucket(js)
    payload = dict(new_thresholds)
    payload["_pushed_at"] = time.time()
    await kv.put(KEY, json.dumps(payload).encode())


async def watch_thresholds(js, on_update=None) -> None:
    """Runs forever — apply every threshold update as it arrives, in place.

    `on_update(new_thresholds, propagation_latency_s)` is called after each
    successful apply, for logging/metrics (propagation_latency_s is None if
    the update carried no `_pushed_at` marker, e.g. from a hand-written KV entry).
    """
    kv = await get_or_create_bucket(js)
    watcher = await kv.watch(KEY)
    async for entry in watcher:
        if entry is None or entry.value is None or entry.operation in ("DEL", "PURGE"):
            continue
        try:
            payload = json.loads(entry.value)
        except json.JSONDecodeError:
            log.warning("Bad JSON in %s/%s (revision %d), ignoring", BUCKET, KEY, entry.revision)
            continue

        pushed_at = payload.pop("_pushed_at", None)
        latency_s = (time.time() - pushed_at) if pushed_at is not None else None
        # A watcher that starts after the KV key already has a value replays
        # that value first (JetStream KV catch-up) — its `_pushed_at` is from
        # whenever it was originally written, not "just now", so a huge
        # latency here is a stale replay, not a real propagation delay.
        is_live_update = latency_s is not None and latency_s < 10.0

        thresholds_module.SIGNAL_THRESHOLDS.clear()
        thresholds_module.SIGNAL_THRESHOLDS.update(payload)
        if is_live_update:
            log.info("Thresholds hot-reloaded (KV revision %d) — propagation %.1fms: %s",
                      entry.revision, latency_s * 1000, payload)
        else:
            log.info("Thresholds loaded (KV revision %d, startup/replayed value): %s", entry.revision, payload)
        if on_update is not None:
            on_update(payload, latency_s if is_live_update else None)
