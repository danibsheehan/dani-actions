from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / ".github/actions/check-cobertura-threshold/check_cobertura_line_rate.py"
FIXTURES = Path(__file__).parent / "fixtures"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_passes_default_minimum_when_above_it():
    result = run(str(FIXTURES / "cobertura_ok.xml"))
    assert result.returncode == 0
    assert "75.00%" in result.stdout
    assert "minimum 50%" in result.stdout


def test_passes_explicit_custom_minimum():
    result = run(str(FIXTURES / "cobertura_ok.xml"), "0.70")
    assert result.returncode == 0
    assert "minimum 70%" in result.stdout


def test_fails_default_minimum_when_below_it():
    result = run(str(FIXTURES / "cobertura_low.xml"))
    assert result.returncode == 1
    assert "30.00%" in result.stderr
    assert "below 50%" in result.stderr


def test_passes_when_line_rate_exactly_equals_minimum():
    # cobertura_ok.xml has line-rate="0.75"; the check is `< minimum`, so an
    # exact match should pass, not fail.
    result = run(str(FIXTURES / "cobertura_ok.xml"), "0.75")
    assert result.returncode == 0
    assert "minimum 75%" in result.stdout


def test_fails_explicit_custom_minimum():
    result = run(str(FIXTURES / "cobertura_ok.xml"), "0.90")
    assert result.returncode == 1
    assert "below 90%" in result.stderr


def test_label_override_appears_in_message():
    result = run(str(FIXTURES / "cobertura_low.xml"), "--label", "Backend coverage")
    assert result.returncode == 1
    assert "Backend coverage" in result.stderr


def test_missing_xml_path_is_nonzero_exit():
    result = run(str(FIXTURES / "does_not_exist.xml"))
    assert result.returncode != 0


def test_malformed_xml_is_nonzero_exit(tmp_path):
    malformed = tmp_path / "malformed.xml"
    malformed.write_text("<coverage line-rate=", encoding="utf-8")
    result = run(str(malformed))
    assert result.returncode != 0
