#!/usr/bin/env python3
"""Validate Kafka ``kafka-topics --describe`` output against a topic contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kafka_path.topic_contracts import TOPIC_CONTRACTS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", choices=sorted(TOPIC_CONTRACTS))
    args = parser.parse_args()
    TOPIC_CONTRACTS[args.topic].assert_describe(sys.stdin.read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
