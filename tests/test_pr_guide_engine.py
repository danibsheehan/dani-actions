from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import load_module

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / ".github/actions/pr-guide-engine/pr_guide_engine.py"
FIXTURES = Path(__file__).parent / "fixtures"

mod = load_module(".github/actions/pr-guide-engine/pr_guide_engine.py")


def load_grouped():
    return mod.load_config(str(FIXTURES / "pr-guide-areas-grouped.yml"))


def load_additive():
    return mod.load_config(str(FIXTURES / "pr-guide-areas-additive.yml"))


# -- matches / areas_for -----------------------------------------------------


def test_matches_prefix_only_requires_prefix():
    assert mod.matches("src/frontend/app.tsx", ["src/frontend/"], "prefix_only")
    assert not mod.matches("other/src/frontend/app.tsx", ["src/frontend/"], "prefix_only")


def test_matches_prefix_or_contains_also_matches_substring():
    assert mod.matches("other/src/frontend/app.tsx", ["src/frontend/"], "prefix_or_contains")


def test_areas_for_multi_area_match_and_other_fallback():
    config = load_grouped()
    assert mod.areas_for("src/frontend/app.tsx", config) == ["frontend"]
    assert mod.areas_for("docs/readme.md", config) == ["other"]


# -- analyze_paths / ordered_areas / format_touches --------------------------


def test_analyze_paths_and_ordered_areas_and_format_touches():
    config = load_grouped()
    paths = [
        "src/backend/api.py",
        "src/frontend/app.tsx",
        "src/frontend/app.tsx",
        "docs/readme.md",
    ]
    areas, counts = mod.analyze_paths(paths, config)
    assert areas == {"backend", "frontend", "other"}
    assert counts == {"backend": 1, "frontend": 2, "other": 1}

    ordered = mod.ordered_areas(areas, config)
    assert ordered == ["frontend", "backend", "other"]

    touches = mod.format_touches(areas, config)
    assert touches == "Frontend, Backend, Other"


def test_format_touches_empty_uses_no_touches_text():
    config = load_grouped()
    assert mod.format_touches(set(), config) == "none detected"


# -- verify_commands: grouped strategy ---------------------------------------


def test_verify_commands_grouped_first_touched_area_wins():
    config = load_grouped()
    commands = mod.verify_commands({"frontend", "backend"}, config)
    # frontend's group wins exclusively, but backend's verify_extra still
    # contributes additively regardless of which group won.
    assert commands == ["npm test", "make lint"]


def test_verify_commands_grouped_verify_extra_is_additive():
    config = load_grouped()
    commands = mod.verify_commands({"backend"}, config)
    assert commands == ["pytest", "make lint"]


def test_verify_commands_grouped_falls_back_when_no_group_matches():
    config = load_grouped()
    commands = mod.verify_commands({"tests"}, config)
    assert commands == ["echo no-op"]


# -- verify_commands: additive strategy ---------------------------------------


def test_verify_commands_additive_unions_and_dedupes_first_occurrence_order():
    config = load_additive()
    commands = mod.verify_commands({"backend", "openapi"}, config)
    assert commands == ["pytest", "make lint"]


def test_verify_commands_additive_single_area():
    config = load_additive()
    commands = mod.verify_commands({"frontend"}, config)
    assert commands == ["npm test"]


# -- checklist_items -----------------------------------------------------------


def test_checklist_items_always_items_at_start():
    config = load_grouped()
    items = mod.checklist_items({"frontend"}, config)
    assert items[0] == "Update CHANGELOG"
    assert "Check responsive layout" in items


def test_checklist_items_always_items_at_end():
    config = load_additive()
    items = mod.checklist_items({"frontend"}, config)
    assert items[-1] == "Update CHANGELOG"


def test_checklist_items_tests_missing_rule_fires_when_tests_area_absent():
    config = load_grouped()
    items = mod.checklist_items({"backend"}, config)
    assert "Add/adjust tests for this change" in items


def test_checklist_items_tests_missing_rule_does_not_fire_when_tests_touched():
    config = load_grouped()
    items = mod.checklist_items({"backend", "tests"}, config)
    assert "Add/adjust tests for this change" not in items


def test_checklist_items_unless_area_suppresses_item():
    config = load_grouped()
    with_openapi = mod.checklist_items({"backend", "openapi"}, config)
    without_openapi = mod.checklist_items({"backend"}, config)
    assert "Check API backward compatibility" not in with_openapi
    assert "Check API backward compatibility" in without_openapi


# -- reviewer_focus -------------------------------------------------------------


def test_reviewer_focus_test_file_rule_suffix_match():
    config = load_grouped()
    focus = mod.reviewer_focus({"backend"}, ["src/backend/api_test.py"], config)
    assert "Focus on test coverage of the new behavior" in focus


def test_reviewer_focus_test_file_rule_substring_match():
    config = load_grouped()
    focus = mod.reviewer_focus({"backend"}, ["src/backend/tests/helpers.py"], config)
    assert "Focus on test coverage of the new behavior" in focus


def test_reviewer_focus_fallback_text_when_empty():
    config = load_grouped()
    focus = mod.reviewer_focus(set(), [], config)
    assert focus == ["General review"]


# -- config validation: the engine intentionally does not validate config shape,
# it fails fast with a KeyError on the first missing required key. These tests
# pin down that behavior so a future change to it is a deliberate decision.


def test_areas_for_missing_areas_key_raises_key_error():
    with pytest.raises(KeyError, match="areas"):
        mod.areas_for("src/frontend/app.tsx", {})


def test_verify_commands_missing_fallback_key_raises_key_error_when_no_commands_match():
    config = load_grouped()
    del config["fallback"]
    with pytest.raises(KeyError, match="fallback"):
        mod.verify_commands({"tests"}, config)


def test_reviewer_focus_missing_fallback_key_raises_key_error_when_no_focus_matches():
    config = load_grouped()
    del config["fallback"]
    with pytest.raises(KeyError, match="fallback"):
        mod.reviewer_focus(set(), [], config)


# -- _resolve_items --------------------------------------------------------------


def test_resolve_items_unless_area_suppression():
    items = [
        "plain item",
        {"text": "conditional item", "unless_area": "openapi"},
    ]
    assert mod._resolve_items(items, {"backend"}) == ["plain item", "conditional item"]
    assert mod._resolve_items(items, {"backend", "openapi"}) == ["plain item"]


# -- body scaffolding / merging --------------------------------------------------


def test_is_legacy_template():
    config = load_grouped()
    assert mod.is_legacy_template("<!-- legacy-pr-template -->\nbody", config)
    assert not mod.is_legacy_template("some other body", config)


def test_summary_section_is_empty():
    empty = "## Summary\n\n\n## How to verify\n\n- step"
    filled = "## Summary\n\nActual summary text.\n\n## How to verify\n\n- step"
    assert mod.summary_section_is_empty(empty)
    assert not mod.summary_section_is_empty(filled)
    assert mod.summary_section_is_empty("no summary section at all")


def test_should_full_scaffold_empty_body():
    config = load_grouped()
    assert mod.should_full_scaffold("", config)
    assert mod.should_full_scaffold("   \n  ", config)


def test_should_full_scaffold_legacy_template():
    config = load_grouped()
    assert mod.should_full_scaffold("<!-- legacy-pr-template -->\nold body", config)


def test_should_full_scaffold_empty_summary_section():
    config = load_grouped()
    body = "## Summary\n\n\n## How to verify\n\n- old step"
    assert mod.should_full_scaffold(body, config)


def test_should_full_scaffold_false_when_already_scaffolded_with_meta():
    config = load_grouped()
    body = (
        "## Summary\n\n\n## How to verify\n\n- step\n\n"
        f"{config['meta_start']}\nTouches: Backend\n{config['meta_end']}\n"
    )
    assert not mod.should_full_scaffold(body, config)


def test_merge_pr_body_full_scaffold_for_empty_body():
    config = load_grouped()
    result = mod.merge_pr_body("", {"backend"}, ["pytest"], config)
    assert result is not None
    assert "## Summary" in result
    assert "- pytest" in result
    assert config["meta_start"] in result


def test_merge_pr_body_replaces_only_meta_block_when_present():
    config = load_grouped()
    current = (
        "## Summary\n\nReal summary written by a human.\n\n"
        "## How to verify\n\n- old step\n\n"
        f"{config['meta_start']}\nTouches: Frontend\n{config['meta_end']}\n"
    )
    result = mod.merge_pr_body(current, {"backend"}, ["pytest"], config)
    assert result is not None
    assert "Real summary written by a human." in result
    assert "Touches: Backend" in result
    assert "Touches: Frontend" not in result


def test_merge_pr_body_returns_none_when_neither_applies():
    config = load_grouped()
    current = "## Summary\n\nReal summary written by a human.\n\n## How to verify\n\n- old step\n"
    assert mod.merge_pr_body(current, {"backend"}, ["pytest"], config) is None


# -- CLI: cmd_body / cmd_guide ----------------------------------------------------


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_body_writes_full_scaffold(tmp_path):
    changed_paths_file = tmp_path / "paths.txt"
    changed_paths_file.write_text("src/backend/api.py\n", encoding="utf-8")
    current_body_file = tmp_path / "current_body.txt"
    current_body_file.write_text("", encoding="utf-8")
    result_file = tmp_path / "result.txt"

    result = run_cli(
        "body",
        "--config-file",
        str(FIXTURES / "pr-guide-areas-grouped.yml"),
        "--changed-paths-file",
        str(changed_paths_file),
        "--current-body-file",
        str(current_body_file),
        "--result-file",
        str(result_file),
    )

    assert result.returncode == 0
    body = result_file.read_text(encoding="utf-8")
    assert "## Summary" in body
    assert "- pytest" in body


def test_cli_body_missing_current_body_file_errors():
    result = run_cli(
        "body",
        "--config-file",
        str(FIXTURES / "pr-guide-areas-grouped.yml"),
        "--changed-paths-file",
        str(FIXTURES / "pr-guide-areas-grouped.yml"),
        "--result-file",
        "/dev/null",
    )
    assert result.returncode != 0
    assert "--current-body-file is required" in result.stderr


def test_cli_guide_writes_expected_sections(tmp_path):
    changed_paths_file = tmp_path / "paths.txt"
    changed_paths_file.write_text(
        "src/backend/api.py\nsrc/frontend/app.tsx\n", encoding="utf-8"
    )
    result_file = tmp_path / "guide.md"

    result = run_cli(
        "guide",
        "--config-file",
        str(FIXTURES / "pr-guide-areas-additive.yml"),
        "--changed-paths-file",
        str(changed_paths_file),
        "--result-file",
        str(result_file),
    )

    assert result.returncode == 0
    guide = result_file.read_text(encoding="utf-8")
    assert "## PR guide" in guide
    assert "### Suggested verify" in guide
    assert "- npm test" in guide
    assert "### Checklist (applies to this PR)" in guide
    assert "### Files by area" in guide
    assert "| Frontend | 1 |" in guide
    assert "| Backend | 1 |" in guide
