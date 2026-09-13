#!/usr/bin/env python3
"""Validate ``nats consumer info --json`` against a named local contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.nats_consumers import CONSUMER_CONTRACTS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("consumer", choices=sorted(CONSUMER_CONTRACTS))
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    config = payload.get("config")
    if not isinstance(config, dict):
        raise RuntimeError("NATS consumer info did not contain a config object")
    CONSUMER_CONTRACTS[args.consumer].assert_matches(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
