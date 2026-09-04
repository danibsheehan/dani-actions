#!/usr/bin/env python3
"""Generic PR-guide engine: path-to-area analysis, PR body scaffolding/merging, and sticky
guide comment content -- driven entirely by a repo-owned area-config YAML file (default
.github/pr-guide-areas.yml). See dani-actions' README for the full config schema.

Supports two verify-command strategies, since real callers genuinely differ here:
- "grouped" (default): named command groups, each area optionally triggers one group by
  name; the first touched area's group (in area-config order) wins exclusively, matching an
  if/elif "pick one full command block" pattern. Areas may also always-additively contribute
  `verify_extra` commands regardless of which group won.
- "additive": each area independently contributes its own `verify_commands` list; touched
  areas' contributions are unioned (de-duplicated, first-occurrence order) with no exclusive
  grouping.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict

import yaml


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def read_paths(paths_file: str) -> list[str]:
    with open(paths_file, encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]


def matches(path: str, prefixes: list[str], mode: str) -> bool:
    if mode == "prefix_only":
        return any(path == prefix or path.startswith(prefix) for prefix in prefixes)
    return any(path == prefix or path.startswith(prefix) or prefix in path for prefix in prefixes)


def _area_by_id(config: dict, area_id: str) -> dict | None:
    for area in config["areas"]:
        if area["id"] == area_id:
            return area
    return None


def ordered_area_ids(config: dict) -> list[str]:
    return [area["id"] for area in config["areas"]]


def contribution_order(config: dict, key: str) -> list[str]:
    """Order to iterate areas in for a given contribution (verify/checklist/reviewer_focus).
    Defaults to area-declaration order, but a real caller (caught-looking) has its own
    bespoke order for some functions that doesn't match declaration order at all -- e.g. its
    verify_commands/checklist_items put frontend/backend before openapi, while its
    reviewer_focus happens to match declaration order. Never assume one order fits all
    functions; this must be configurable per-function."""
    override = config.get(key)
    if override:
        return override
    return ordered_area_ids(config)


def _resolve_items(raw_items: list, areas: set[str]) -> list[str]:
    """Each item is either a plain string, or {text, unless_area} to conditionally suppress
    it when another specific area is also touched (e.g. a handler-shape note that's already
    covered by a more specific API-contract note when both areas change together)."""
    resolved: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            if item.get("unless_area") in areas:
                continue
            resolved.append(item["text"])
        else:
            resolved.append(item)
    return resolved


def areas_for(path: str, config: dict) -> list[str]:
    mode = config.get("match_mode", "prefix_or_contains")
    found = [area["id"] for area in config["areas"] if matches(path, area["prefixes"], mode)]
    return found or ["other"]


def analyze_paths(paths: list[str], config: dict) -> tuple[set[str], dict[str, int]]:
    area_counts: dict[str, int] = defaultdict(int)
    for path in paths:
        for area_id in areas_for(path, config):
            area_counts[area_id] += 1
    return set(area_counts), dict(area_counts)


def ordered_areas(areas: set[str], config: dict) -> list[str]:
    ordered = [area_id for area_id in ordered_area_ids(config) if area_id in areas]
    if "other" in areas:
        ordered.append("other")
    return ordered


def area_display(config: dict) -> dict[str, str]:
    display = {area["id"]: area["display"] for area in config["areas"]}
    display["other"] = config.get("other_display", "other")
    return display


def format_touches(areas: set[str], config: dict) -> str:
    ordered = ordered_areas(areas, config)
    if not ordered:
        return config.get("no_touches_text", "none detected")
    display = area_display(config)
    return ", ".join(display[area_id] for area_id in ordered)


def verify_commands(areas: set[str], config: dict) -> list[str]:
    strategy = config.get("verify_strategy", "grouped")
    commands: list[str] = []

    order = contribution_order(config, "verify_order")

    if strategy == "grouped":
        groups = config.get("verify_groups", {})
        chosen: str | None = None
        for area_id in order:
            if area_id not in areas:
                continue
            group_name = (_area_by_id(config, area_id) or {}).get("verify_group")
            if group_name:
                chosen = group_name
                break
        if chosen:
            commands.extend(groups.get(chosen, []))
        for area_id in order:
            if area_id not in areas:
                continue
            extras = (_area_by_id(config, area_id) or {}).get("verify_extra", [])
            for extra in _resolve_items(extras, areas):
                if extra not in commands:
                    commands.append(extra)
    else:  # additive
        for area_id in order:
            if area_id not in areas:
                continue
            raw = (_area_by_id(config, area_id) or {}).get("verify_commands", [])
            for command in _resolve_items(raw, areas):
                if command not in commands:
                    commands.append(command)

    if not commands:
        commands.append(config["fallback"]["verify"])
    return commands


def checklist_items(areas: set[str], config: dict) -> list[str]:
    items: list[str] = []
    always = config.get("always_checklist_items", [])
    position = config.get("checklist_position", "start")

    if position == "start":
        items.extend(always)

    for area_id in contribution_order(config, "checklist_order"):
        if area_id not in areas:
            continue
        raw = (_area_by_id(config, area_id) or {}).get("checklist", [])
        items.extend(_resolve_items(raw, areas))

    tests_rule = config.get("tests_missing_rule")
    if tests_rule:
        trigger_areas = set(tests_rule.get("trigger_areas", []))
        tests_area_id = tests_rule.get("tests_area_id", "tests")
        if tests_area_id not in areas and areas & trigger_areas:
            items.append(tests_rule["note"])

    if position == "end":
        items.extend(always)

    return items


def reviewer_focus(areas: set[str], paths: list[str], config: dict) -> list[str]:
    focus: list[str] = []
    for area_id in contribution_order(config, "reviewer_focus_order"):
        if area_id not in areas:
            continue
        raw = (_area_by_id(config, area_id) or {}).get("reviewer_focus", [])
        focus.extend(_resolve_items(raw, areas))

    test_file_rule = config.get("test_file_rule")
    if test_file_rule:
        suffixes = tuple(test_file_rule.get("suffixes", []))
        substrings = test_file_rule.get("substrings", [])
        if any(
            (suffixes and path.endswith(suffixes)) or any(s in path for s in substrings)
            for path in paths
        ):
            focus.append(test_file_rule["note"])

    if not focus:
        focus.append(config["fallback"]["reviewer_focus"])
    return focus


def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


def is_legacy_template(body: str, config: dict) -> bool:
    markers = config.get("legacy_template_markers", [])
    return any(marker in body for marker in markers)


def summary_section_is_empty(body: str) -> bool:
    match = re.search(r"## Summary\s*\n+(.*?)\n+## How to verify", body, re.DOTALL | re.IGNORECASE)
    if not match:
        return True
    return not _strip_html_comments(match.group(1))


def should_full_scaffold(body: str, config: dict) -> bool:
    stripped = body.strip()
    if not stripped:
        return True
    if is_legacy_template(body, config):
        return True
    if "## Summary" in body and "## How to verify" in body and summary_section_is_empty(body):
        return config["meta_start"] not in body
    return False


def has_meta_block(body: str, config: dict) -> bool:
    return config["meta_start"] in body and config["meta_end"] in body


def build_meta_block(areas: set[str], config: dict) -> str:
    return config["meta_block_template"].format(touches=format_touches(areas, config))


def build_full_body(areas: set[str], verify: list[str], config: dict) -> str:
    verify_lines = [config["verify_prompt"], ""] + [f"- {command}" for command in verify]
    lines = [
        "## Summary",
        "",
        config["summary_prompt"],
        "",
        "## How to verify",
        "",
        *verify_lines,
        "",
    ]
    extra_line = config.get("extra_body_line")
    if extra_line:
        lines.extend([extra_line, ""])
    lines.extend(
        [
            config["meta_start"],
            build_meta_block(areas, config),
            config["meta_end"],
            "",
        ]
    )
    return "\n".join(lines)


def merge_pr_body(current: str, areas: set[str], verify: list[str], config: dict) -> str | None:
    if should_full_scaffold(current, config):
        return build_full_body(areas, verify, config)
    if has_meta_block(current, config):
        meta = f"{config['meta_start']}\n{build_meta_block(areas, config)}\n{config['meta_end']}"
        return re.sub(
            re.escape(config["meta_start"]) + r".*?" + re.escape(config["meta_end"]),
            meta,
            current,
            count=1,
            flags=re.DOTALL,
        )
    return None


def cmd_body(args: argparse.Namespace) -> int:
    config = load_config(args.config_file)
    paths = read_paths(args.changed_paths_file)
    areas, _ = analyze_paths(paths, config)
    verify = verify_commands(areas, config)
    with open(args.current_body_file, encoding="utf-8") as handle:
        current = handle.read()
    new_body = merge_pr_body(current, areas, verify, config)
    if new_body is None:
        return 1
    with open(args.result_file, "w", encoding="utf-8") as handle:
        handle.write(new_body)
    return 0


def cmd_guide(args: argparse.Namespace) -> int:
    config = load_config(args.config_file)
    paths = read_paths(args.changed_paths_file)
    areas, area_counts = analyze_paths(paths, config)
    diff_stat = os.environ.get("DIFF_SHORTSTAT", "").strip()
    commit_lines = [
        line.strip() for line in os.environ.get("COMMIT_LINES", "").splitlines() if line.strip()
    ]

    lines: list[str] = [
        "## PR guide",
        "",
        config["guide_intro"],
        "",
        f"**Touches:** {format_touches(areas, config)}",
    ]
    if diff_stat:
        lines.extend(["", f"**Diff:** {diff_stat}"])

    lines.extend(["", "### Suggested verify", ""])
    lines.extend(f"- {command}" for command in verify_commands(areas, config))

    lines.extend(["", "### Checklist (applies to this PR)", ""])
    lines.extend(f"- [ ] {item}" for item in checklist_items(areas, config))

    lines.extend(["", "### Reviewer focus", ""])
    lines.extend(f"- {item}" for item in reviewer_focus(areas, paths, config))

    if commit_lines:
        lines.extend(["", "### Commits", ""])
        lines.extend(f"- `{line}`" for line in commit_lines[:15])
        if len(commit_lines) > 15:
            overflow_template = config.get("commit_overflow_note", "_...and {n} more_")
            lines.append(f"- {overflow_template.format(n=len(commit_lines) - 15)}")

    lines.extend(["", "### Files by area", "", "| Area | Files |", "| --- | ---: |"])
    display = area_display(config)
    for area_id in ordered_area_ids(config):
        if area_id in area_counts:
            lines.append(f"| {display[area_id]} | {area_counts[area_id]} |")
    if "other" in area_counts:
        lines.append(f"| {display['other']} | {area_counts['other']} |")

    repo_url = os.environ.get("GITHUB_REPO_URL", "").rstrip("/")
    ci_path = config.get("ci_workflow_path", ".github/workflows/verify.yml")
    template_path = config.get("pr_template_path", ".github/pull_request_template.md")
    if repo_url:
        ci_href = f"{repo_url}/blob/main/{ci_path}"
        template_href = f"{repo_url}/blob/main/{template_path}"
    else:
        ci_href = ci_path
        template_href = template_path

    lines.extend(
        [
            "",
            "### CI",
            "",
            config["required_checks_description"].format(ci_href=ci_href),
            "",
            "---",
            "",
            f"Template: [`{template_path.rsplit('/', 1)[-1]}`]({template_href})",
        ]
    )

    with open(args.result_file, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["body", "guide"])
    parser.add_argument("--config-file", required=True)
    parser.add_argument("--changed-paths-file", required=True)
    parser.add_argument("--current-body-file")
    parser.add_argument("--result-file", required=True)
    args = parser.parse_args()

    if args.mode == "body":
        if not args.current_body_file:
            parser.error("--current-body-file is required for mode=body")
        return cmd_body(args)
    return cmd_guide(args)


if __name__ == "__main__":
    raise SystemExit(main())
