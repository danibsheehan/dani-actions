#!/usr/bin/env python3
"""Rewrite every danibsheehan/dani-actions/...@vN ref in a repo's workflow files.

Exits 0 if any file changed (changed paths printed to stdout, one per line),
1 if every reference already points at the target tag -- not a failure, the
caller decides whether "no changes" means skipping a PR.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REF_PATTERN = re.compile(r"(danibsheehan/dani-actions/\S+?)@v\d+")


def sweep_file(path: Path, target_tag: str) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = REF_PATTERN.sub(rf"\1@{target_tag}", original)
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def sweep_workflows(workflows_dir: Path, target_tag: str) -> list[Path]:
    changed = []
    for path in sorted(workflows_dir.glob("*.y*ml")):
        if sweep_file(path, target_tag):
            changed.append(path)
    return changed


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: sweep_repo_pins.py <workflows-dir> <target-tag>", file=sys.stderr)
        return 2
    workflows_dir = Path(sys.argv[1])
    target_tag = sys.argv[2]

    changed = sweep_workflows(workflows_dir, target_tag)
    for path in changed:
        print(path)
    return 0 if changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
