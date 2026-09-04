from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from conftest import load_module

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / ".github/actions/merge-cobertura-by-file/merge_cobertura_by_file.py"
FIXTURES = Path(__file__).parent / "fixtures"

mod = load_module(".github/actions/merge-cobertura-by-file/merge_cobertura_by_file.py")


def test_line_hits_counts_covered_and_valid():
    classes_el = ET.fromstring(
        """
        <classes>
          <class filename="a.py">
            <lines>
              <line number="1" hits="1"/>
              <line number="2" hits="0"/>
              <line number="3" hits="5"/>
            </lines>
          </class>
        </classes>
        """
    )
    covered, valid = mod._line_hits(classes_el)
    assert covered == 2
    assert valid == 3


def test_merge_duplicate_classes_unions_line_hits_and_recalculates_rate():
    tree = ET.parse(FIXTURES / "cobertura_gocover_dup.xml")
    classes_el = tree.getroot().find("packages/package/classes")

    mod._merge_duplicate_classes(classes_el)

    classes = classes_el.findall("class")
    assert len(classes) == 1

    keeper = classes[0]
    lines = {int(l.get("number")): int(l.get("hits")) for l in keeper.find("lines")}
    assert lines == {10: 1, 11: 0, 20: 3, 30: 1}
    assert keeper.get("line-rate") == str(3 / 4)


def test_recalc_package_zero_valid_lines_is_full_rate():
    pkg = ET.fromstring(
        """
        <package>
          <classes>
            <class filename="empty.py"><lines/></class>
          </classes>
        </package>
        """
    )
    cov, total = mod._recalc_package(pkg)
    assert (cov, total) == (0, 0)
    assert pkg.get("line-rate") == "1"


def test_merge_cobertura_recomputes_root_totals_across_packages():
    xml = """
    <coverage line-rate="0" lines-covered="0" lines-valid="0">
      <packages>
        <package name="a">
          <classes>
            <class filename="a.py">
              <lines><line number="1" hits="1"/><line number="2" hits="0"/></lines>
            </class>
          </classes>
        </package>
        <package name="b">
          <classes>
            <class filename="b.py">
              <lines><line number="1" hits="1"/><line number="2" hits="1"/></lines>
            </class>
          </classes>
        </package>
      </packages>
    </coverage>
    """
    tree = ET.ElementTree(ET.fromstring(xml))
    mod.merge_cobertura(tree)
    root = tree.getroot()
    assert root.get("lines-covered") == "3"
    assert root.get("lines-valid") == "4"
    assert root.get("line-rate") == str(3 / 4)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_cli_merges_gocover_duplicate_and_prints_well_formed_xml():
    result = run_cli(str(FIXTURES / "cobertura_gocover_dup.xml"))
    assert result.returncode == 0
    root = ET.fromstring(result.stdout)
    classes = root.findall("packages/package/classes/class")
    assert len(classes) == 1
    assert classes[0].get("name") == "widget.go"


def test_cli_wrong_number_of_args_exits_2():
    result = run_cli()
    assert result.returncode == 2
    assert "usage:" in result.stderr

    result = run_cli("one", "two")
    assert result.returncode == 2
