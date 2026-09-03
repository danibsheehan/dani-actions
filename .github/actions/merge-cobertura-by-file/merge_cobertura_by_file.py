#!/usr/bin/env python3
"""Merge Cobertura <class> entries that share the same filename within a package.

gocover-cobertura emits separate classes for methods on a type vs package-level
functions, so tools that list by file show duplicate rows. This collapses them
into one class per (package, filename) with merged <line> hits.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET


def _line_hits(classes_el: ET.Element) -> tuple[int, int]:
    covered = 0
    valid = 0
    for cl in classes_el:
        if cl.tag != "class":
            continue
        lines_el = cl.find("lines")
        if lines_el is None:
            continue
        for line in lines_el:
            if line.tag != "line":
                continue
            valid += 1
            if int(line.get("hits", 0)) > 0:
                covered += 1
    return covered, valid


def _merge_duplicate_classes(classes_el: ET.Element) -> None:
    by_file: dict[str, list[ET.Element]] = {}
    for cl in list(classes_el):
        if cl.tag != "class":
            continue
        fn = cl.get("filename")
        if not fn:
            continue
        by_file.setdefault(fn, []).append(cl)

    for fn, group in by_file.items():
        if len(group) <= 1:
            continue
        lines_by_num: dict[int, int] = {}
        for cl in group:
            lines_el = cl.find("lines")
            if lines_el is None:
                continue
            for line in lines_el:
                if line.tag != "line":
                    continue
                n = int(line.get("number", "0"))
                h = int(line.get("hits", "0"))
                lines_by_num[n] = max(lines_by_num.get(n, 0), h)

        keeper = group[0]
        for cl in group[1:]:
            classes_el.remove(cl)

        for child in list(keeper):
            keeper.remove(child)

        base = fn.split("/")[-1]
        keeper.set("name", base)
        keeper.set("branch-rate", group[0].get("branch-rate", "0"))
        keeper.set("complexity", group[0].get("complexity", "0"))

        lines_el = ET.SubElement(keeper, "lines")
        for n in sorted(lines_by_num):
            ET.SubElement(lines_el, "line", number=str(n), hits=str(lines_by_num[n]))

        cov = sum(1 for h in lines_by_num.values() if h > 0)
        total = len(lines_by_num)
        keeper.set("line-rate", str(cov / total) if total else "1")


def _recalc_package(pkg: ET.Element) -> tuple[int, int]:
    classes_el = pkg.find("classes")
    if classes_el is None:
        return 0, 0
    cov, total = _line_hits(classes_el)
    if total:
        pkg.set("line-rate", str(cov / total))
    else:
        pkg.set("line-rate", "1")
    return cov, total


def merge_cobertura(tree: ET.ElementTree) -> None:
    root = tree.getroot()
    for pkg in root.findall("packages/package"):
        classes_el = pkg.find("classes")
        if classes_el is not None:
            _merge_duplicate_classes(classes_el)
        _recalc_package(pkg)

    total_cov = 0
    total_valid = 0
    for pkg in root.findall("packages/package"):
        classes_el = pkg.find("classes")
        if classes_el is None:
            continue
        c, v = _line_hits(classes_el)
        total_cov += c
        total_valid += v

    if root.tag == "coverage" and total_valid:
        root.set("line-rate", str(total_cov / total_valid))
        root.set("lines-covered", str(total_cov))
        root.set("lines-valid", str(total_valid))


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: merge_cobertura_by_file.py <cobertura.xml>", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]
    tree = ET.parse(path)
    merge_cobertura(tree)
    ET.indent(tree.getroot(), space="  ")
    sys.stdout.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    tree.write(sys.stdout, encoding="unicode", xml_declaration=False)


if __name__ == "__main__":
    main()
