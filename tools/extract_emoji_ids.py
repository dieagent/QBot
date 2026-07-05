#!/usr/bin/env python3
"""Scan the workspace for Telegram custom emoji occurrences and list unique emoji IDs.

Usage:
  python tools/extract_emoji_ids.py

This prints one ID per line and a count summary.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Set


ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r"emoji-id=\s*['\"]([0-9]+)['\"]")


def find_files(root: Path) -> list[Path]:
    exts = {".py", ".md", ".html", ".txt"}
    files: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and (p.suffix in exts or p.match("*.py")):
            files.append(p)
    return files


def extract_ids_from_file(path: Path) -> Set[str]:
    ids: Set[str] = set()
    try:
        text = path.read_text(encoding="utf8")
    except Exception:
        return ids
    for m in PATTERN.finditer(text):
        ids.add(m.group(1))
    return ids


def main() -> None:
    files = find_files(ROOT)
    all_ids: Set[str] = set()
    for f in files:
        ids = extract_ids_from_file(f)
        if ids:
            for i in ids:
                print(f"{i}  # found in {f.relative_to(ROOT)}")
            all_ids.update(ids)

    print("\nSummary:")
    print(f"Total unique emoji IDs: {len(all_ids)}")


if __name__ == "__main__":
    main()
