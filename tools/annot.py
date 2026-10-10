#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Jyotiprakash Mishra. Based on "xv6, line by line" by Jyotiprakash Mishra
# (https://xv6.jyotiprakash.org); see NOTICE for the attribution term (GPLv3 section 7(b)).
"""Annotation maintenance.

  python tools/annot.py check [PATH...]   coverage, stale notes, broken links
  python tools/annot.py stamp PATH...     record line hashes after a review
  python tools/annot.py todo              files with no annotations yet, by size
  python tools/annot.py tours [N...]      validate guided tours (all, or by number)
  python tools/annot.py concepts [--out DIR]
                                          validate concept pages, figures and
                                          stackswitch.yaml; with --out, also write the
                                          rendered pages there (open DIR/concepts/*.html)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from xv6x import annotations, config, pipeline, render  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "stamp", "todo", "tours", "concepts", "questions", "labs"):
        print(__doc__)
        return 2
    cmd, args = sys.argv[1], sys.argv[2:]
    config.generate_sources()
    files = {f.path: f for f in config.source_files()}
    notes = annotations.load(list(files.values()))

    if cmd == "tours":
        from xv6x import tours as tourmod
        _, _, table = pipeline.run(verbose=False)
        glossary = annotations.load_glossary()
        linker = annotations.Linker(table, list(files.values()), glossary)
        want = {int(a) for a in args}
        bad = False
        for t in tourmod.load(list(files.values())):
            if want and t.num not in want:
                continue
            probs = t.problems
            texts = [t.summary, t.cast] + [s.note + "\n\n" + s.others for s in t.steps] + \
                [str(q.get("q", "")) + "\n\n" + str(q.get("a", "")) for q in t.quiz] + \
                [str(l.get("where", "")) + " " + str(l.get("protects", "")) for l in t.locks]
            for i, s in enumerate(t.steps):
                group = files[s.file].group
                linker.render(s.note + "\n\n" + s.others, "../", "", group, probs)
                sps = tourmod.stack_state(s.state)
                if s.state.get("mode") and sps is None:
                    probs.append(f"step {i + 1}: has a mode but no sp (active stack)")
                if sps:
                    linker.render(sps["detail"] + " " + sps["switched"], "../", "", group, probs)
                if s.figure:
                    from xv6x.concepts import figure_html
                    figure_html(s.figure, "", probs)
                    linker.render(s.caption, "../", "", group, probs)
                for name in s.state.get("stack") or []:
                    if not linker.symbol(str(name), group):
                        probs.append(f"step {i + 1}: call-stack name {name!r} is not a symbol")
            for text in texts[:2] + texts[2 + len(t.steps):]:
                linker.render(text, "../", "", None, probs)
            words = sum(len(x.split()) for x in texts)
            real = [p for p in probs if "does not exist (yet)" not in p]
            print(f"tour {t.num:02d} {t.slug}: {len(t.steps)} steps, {words} words, "
                  f"{len(t.quiz)} questions, {len(real)} problems")
            for p in sorted(set(probs)):
                print("   ", p)
            bad |= bool(real)
        return 1 if bad else 0

    if cmd == "labs":
        from xv6x import labs as labmod, labrender, testrender
        _, facts, table = pipeline.run(verbose=False)
        glossary = annotations.load_glossary()
        linker = annotations.Linker(table, list(files.values()), glossary)
        want = {int(a) for a in args}
        bad = False
        for lab in labmod.load(list(files.values())):
            if want and lab.num not in want:
                continue
            probs = list(lab.problems)
            if lab.commits:
                ctx = testrender._Ctx(linker, files, facts, table, "../", probs)
                hl = labrender.Highlighter(linker, "../")
                labrender.render_lab(lab, ctx, hl, [], [])
                labrender.render_reveal(lab, ctx, hl)
            words = sum(len(str(v).split()) for v in lab.raw.values())
            print(f"lab {lab.num:02d} {lab.slug}: {len(lab.commits)} commits, "
                  f"{len(lab.get('think') or [])} think, {len(lab.get('clinic') or [])} clinic, "
                  f"{len(lab.get('reveal') or [])} reveal steps, ~{words} words, "
                  f"{len(set(probs))} problems")
            for p in sorted(set(probs)):
                print("   ", p)
            bad |= bool(probs)
        return 1 if bad else 0

    if cmd == "questions":
        from xv6x import questions as qmod, testrender
        _, facts, table = pipeline.run(verbose=False)
        glossary = annotations.load_glossary()
        linker = annotations.Linker(table, list(files.values()), glossary)
        cats = qmod.load(list(files.values()))
        want = {int(a) for a in args}
        bad = False
        import collections
        ctx = testrender._Ctx(linker, files, facts, table, "../", [])
        for c in cats:
            if want and c.num not in want:
                continue
            ctx.problems = list(c.problems)
            for k, q in enumerate(c.questions, 1):
                testrender.render_question(q, k, ctx)
            types = collections.Counter(q.type for q in c.questions)
            levels = collections.Counter(q.level for q in c.questions)
            print(f"questions {c.num:02d} {c.slug}: {len(c.questions)} questions, "
                  f"types {dict(types)}, levels {dict(sorted(levels.items()))}, "
                  f"{len(set(ctx.problems))} problems")
            for p in sorted(set(ctx.problems)):
                print("   ", p)
            bad |= bool(ctx.problems)
        print(f"total: {sum(len(c.questions) for c in cats)} questions in {len(cats)} categories")
        return 1 if bad else 0

    if cmd == "concepts":
        import shutil
        from xv6x import concepts as conmod
        _, _, table = pipeline.run(verbose=False)
        glossary = annotations.load_glossary()
        flist = list(files.values())
        linker = annotations.Linker(table, flist, glossary)
        out = None
        if "--out" in args:
            out = Path(args[args.index("--out") + 1]).resolve()
            (out / "concepts").mkdir(parents=True, exist_ok=True)
            (out / "assets").mkdir(exist_ok=True)
            for name in ("app.css", "app.js", "tour.js"):
                shutil.copy(config.WEB / name, out / "assets" / name)
        cl, probs = conmod.load()
        for c in cl:
            cp: list[str] = []
            html = render.render_concept(c, cl, flist, linker, cp)
            words = len(c.body.split())
            print(f"concept {c.num:02d} {c.slug}: {words} words, {len(set(cp))} problems")
            for p in sorted(set(cp)):
                print("   ", p)
            probs += cp
            if out:
                (out / c.url).write_text(html)
        sw, sprobs = conmod.load_stack_switches()
        for path, pts in sw.items():
            if path not in files:
                sprobs.append(f"stackswitch.yaml: unknown file {path}")
                continue
            n = len(files[path].text_lines())
            for pt in pts:
                if not 1 <= pt["line"] <= n:
                    sprobs.append(f"stackswitch.yaml: {path}:{pt['line']} out of range")
                lp: list[str] = []
                linker.render(pt["note"], "", "", files[path].group, lp)
                sprobs += [f"stackswitch.yaml {path}:{pt['line']}: {x}" for x in lp]
        print(f"stackswitch.yaml: {sum(len(v) for v in sw.values())} points, "
              f"{len(sprobs)} problems")
        for p in sprobs:
            print("   ", p)
        lsites, lprobs = conmod.load_lock_sites(list(files.values()))
        locks, _ = conmod.load_locks()
        lockpage = next((c for c in cl if c.slug == "locks"), None)
        if lockpage is not None:
            for l in locks:
                if "{#lock-" + l["id"] + "}" not in lockpage.body:
                    lprobs.append(f"concept locks: no section {{#lock-{l['id']}}} for {l['name']}")
            for a in ("noff", "sie"):
                if "{#" + a + "}" not in lockpage.body:
                    lprobs.append(f"concept locks: no section {{#{a}}} (the source view links to it)")
        for l in locks:
            path, _, ln = str(l.get("decl", "")).partition(":")
            if path not in files or not ln.isdigit() or not 1 <= int(ln) <= len(files[path].text_lines()):
                lprobs.append(f"locks.yaml {l.get('id')}: bad decl {l.get('decl')!r}")
        print(f"locks.yaml: {len(locks)} locks, "
              f"{sum(len(v) for d in lsites.values() for v in d.values())} call sites, "
              f"{len(lprobs)} problems")
        for p in lprobs:
            print("   ", p)
        return 1 if probs or sprobs or lprobs else 0

    if cmd == "todo":
        rest = [f for p, f in files.items() if p not in notes]
        for f in sorted(rest, key=lambda f: -len(f.text_lines())):
            print(f"{len(f.text_lines()):6}  {f.path}")
        return 0

    targets = args or sorted(notes)
    bad = [p for p in targets if p not in notes]
    if bad:
        print("no annotations for:", ", ".join(bad))
        return 1

    if cmd == "stamp":
        for p in targets:
            annotations.stamp(files[p], notes[p])
            print(f"stamped {p}")
        return 0

    # check: also render the links, which needs the symbol table
    _, _, table = pipeline.run(verbose=False)
    glossary = annotations.load_glossary()
    linker = annotations.Linker(table, list(files.values()), glossary)
    failed = False
    for prob in annotations.GLOSSARY_PROBLEMS:
        print("glossary problem:", prob)
    gprobs: list[str] = []
    for g in glossary.values():
        linker.render(g.short_md + "\n\n" + g.body_md, "", "", None, gprobs)
    for prob in sorted(set(gprobs)):
        print("glossary link problem:", prob)
    for p in targets:
        f, fn = files[p], notes[p]
        root = render.rel_root(p)
        linker.render(fn.summary_md, root, p, f.group, fn.problems)
        for n in fn.notes:
            linker.render(n.md, root, p, f.group, fn.problems)
        got, want, missing = annotations.coverage(f, fn)
        stale = annotations.stale_lines(f, fn)
        print(f"{p}: {got}/{want} lines covered, {len(stale)} unstamped or stale")
        if missing:
            print("   uncovered lines:", ", ".join(map(str, missing)))
        for prob in fn.problems:
            print("   problem:", prob)
        failed |= bool(missing or fn.problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
