from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conftest import load_module

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / ".github/actions/sweep-repo-pins/sweep_repo_pins.py"

mod = load_module(".github/actions/sweep-repo-pins/sweep_repo_pins.py")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_sweep_file_updates_outdated_ref(tmp_path):
    f = tmp_path / "verify.yml"
    f.write_text(
        "uses: danibsheehan/dani-actions/.github/workflows/npm-verify.yml@v27\n",
        encoding="utf-8",
    )
    changed = mod.sweep_file(f, "v31")
    assert changed is True
    assert "npm-verify.yml@v31" in f.read_text(encoding="utf-8")


def test_sweep_file_no_change_when_already_current(tmp_path):
    f = tmp_path / "verify.yml"
    content = "uses: danibsheehan/dani-actions/.github/workflows/npm-verify.yml@v31\n"
    f.write_text(content, encoding="utf-8")
    changed = mod.sweep_file(f, "v31")
    assert changed is False
    assert f.read_text(encoding="utf-8") == content


def test_sweep_file_leaves_unrelated_refs_untouched(tmp_path):
    f = tmp_path / "verify.yml"
    content = "uses: actions/checkout@v7\n"
    f.write_text(content, encoding="utf-8")
    changed = mod.sweep_file(f, "v31")
    assert changed is False
    assert f.read_text(encoding="utf-8") == content


def test_sweep_file_updates_multiple_refs_in_one_file(tmp_path):
    f = tmp_path / "verify.yml"
    f.write_text(
        "a: danibsheehan/dani-actions/.github/workflows/npm-verify.yml@v27\n"
        "b: danibsheehan/dani-actions/.github/workflows/go-verify.yml@v29\n",
        encoding="utf-8",
    )
    changed = mod.sweep_file(f, "v31")
    content = f.read_text(encoding="utf-8")
    assert changed is True
    assert "npm-verify.yml@v31" in content
    assert "go-verify.yml@v31" in content


def test_sweep_workflows_only_changes_outdated_files(tmp_path):
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    outdated = workflows_dir / "verify.yml"
    outdated.write_text(
        "uses: danibsheehan/dani-actions/.github/workflows/npm-verify.yml@v27\n",
        encoding="utf-8",
    )
    current = workflows_dir / "pr-guide.yml"
    current_content = "uses: danibsheehan/dani-actions/.github/workflows/pr-guide.yml@v31\n"
    current.write_text(current_content, encoding="utf-8")
    no_ref = workflows_dir / "codeql.yml"
    no_ref.write_text("name: CodeQL\n", encoding="utf-8")

    changed = mod.sweep_workflows(workflows_dir, "v31")

    assert changed == [outdated]
    assert "v31" in outdated.read_text(encoding="utf-8")
    assert current.read_text(encoding="utf-8") == current_content


def test_sweep_workflows_ignores_non_yaml_files(tmp_path):
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "README.md").write_text(
        "danibsheehan/dani-actions/.github/workflows/npm-verify.yml@v1\n", encoding="utf-8"
    )
    changed = mod.sweep_workflows(workflows_dir, "v31")
    assert changed == []


def test_cli_exits_zero_and_prints_changed_paths_when_changes_made(tmp_path):
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    f = workflows_dir / "verify.yml"
    f.write_text(
        "uses: danibsheehan/dani-actions/.github/workflows/npm-verify.yml@v27\n",
        encoding="utf-8",
    )
    result = run_cli(str(workflows_dir), "v31")
    assert result.returncode == 0
    assert str(f) in result.stdout


def test_cli_exits_one_when_nothing_changed(tmp_path):
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "verify.yml").write_text(
        "uses: danibsheehan/dani-actions/.github/workflows/npm-verify.yml@v31\n",
        encoding="utf-8",
    )
    result = run_cli(str(workflows_dir), "v31")
    assert result.returncode == 1
    assert result.stdout == ""


def test_cli_wrong_number_of_args_exits_2():
    result = run_cli()
    assert result.returncode == 2
    assert "usage:" in result.stderr

    result = run_cli("one", "two", "three")
    assert result.returncode == 2
