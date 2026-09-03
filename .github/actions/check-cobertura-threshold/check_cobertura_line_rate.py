#!/usr/bin/env python3
"""Fail if a Cobertura XML root line-rate is below a minimum (CI default: 0.50)."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cobertura_xml", help="Path to Cobertura XML")
    parser.add_argument(
        "minimum",
        type=float,
        nargs="?",
        default=0.50,
        help="Minimum line-rate in [0, 1] (default: 0.50)",
    )
    parser.add_argument(
        "--label",
        default="Coverage",
        help="Label used in success/failure messages",
    )
    args = parser.parse_args()

    line_rate = float(ET.parse(args.cobertura_xml).getroot().get("line-rate", "0"))
    if line_rate < args.minimum:
        print(
            f"{args.label} {line_rate:.2%} is below {args.minimum:.0%}",
            file=sys.stderr,
        )
        return 1
    print(f"{args.label} {line_rate:.2%} (minimum {args.minimum:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
