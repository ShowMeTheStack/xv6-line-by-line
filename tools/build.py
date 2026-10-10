#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Jyotiprakash Mishra. Based on "xv6, line by line" by Jyotiprakash Mishra
# (https://xv6.jyotiprakash.org); see NOTICE for the attribution term (GPLv3 section 7(b)).
"""Build the static site into ./site.

Usage: python tools/build.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from xv6x import annotations, pipeline, render  # noqa: E402


def main() -> None:
    t = time.time()
    files, facts, table = pipeline.run()
    notes = annotations.load(files)
    glossary = annotations.load_glossary()
    problems = render.write_site(files, facts, table, notes, glossary)
    for f in files:
        fn = notes.get(f.path)
        if fn:
            got, want, missing = annotations.coverage(f, fn)
            stale = annotations.stale_lines(f, fn)
            print(f"  {f.path}: {got}/{want} lines annotated"
                  + (f", {len(stale)} unstamped/stale" if stale else ""))
    for p in annotations.GLOSSARY_PROBLEMS:
        print("  problem: glossary:", p)
    for p in problems:
        print("  problem:", p)
    print(f"site written to {render.SITE} in {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
