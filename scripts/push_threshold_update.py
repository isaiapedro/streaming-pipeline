#!/usr/bin/env python3
"""Cloud-operator-side helper: push a per-signal threshold update to the
JetStream KV bucket the running brain service watches (brain/config_watcher.py).

Demonstrates the L2 bidirectional config-push channel — run this while
`python -m brain.main` is running and watch its logs for the hot-reload
line + measured propagation latency, with no brain restart required.

Usage:
    python scripts/push_threshold_update.py --signal heart_rate --warning-high 110 --critical-high 130
"""

import argparse
import asyncio
import sys
from pathlib import Path

import nats

sys.path.insert(0, str(Path(__file__).parent.parent))

from brain.config_watcher import push_thresholds
from config.settings import NATS_URL
from config.thresholds import SIGNAL_THRESHOLDS


async def main(signal_type: str, overrides: dict) -> None:
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()

    new_thresholds = {k: dict(v) for k, v in SIGNAL_THRESHOLDS.items()}
    new_thresholds.setdefault(signal_type, {})
    new_thresholds[signal_type].update(overrides)

    print(f"Pushing new thresholds for {signal_type!r}: {new_thresholds[signal_type]}")
    await push_thresholds(js, new_thresholds)
    print("Pushed. Check the running brain service's logs for the hot-reload + propagation-latency line.")
    await nc.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal", required=True, choices=sorted(SIGNAL_THRESHOLDS))
    parser.add_argument("--warning-high", type=float)
    parser.add_argument("--critical-high", type=float)
    parser.add_argument("--warning-low", type=float)
    parser.add_argument("--critical-low", type=float)
    args = parser.parse_args()

    overrides = {
        k: v for k, v in {
            "warning_high": args.warning_high, "critical_high": args.critical_high,
            "warning_low": args.warning_low, "critical_low": args.critical_low,
        }.items() if v is not None
    }
    if not overrides:
        parser.error("Pass at least one of --warning-high/--critical-high/--warning-low/--critical-low")

    asyncio.run(main(args.signal, overrides))
