# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Jyotiprakash Mishra. Based on "xv6, line by line" by Jyotiprakash Mishra
# (https://xv6.jyotiprakash.org); see NOTICE for the attribution term (GPLv3 section 7(b)).
"""Annotation sidecars: loading, checking and rendering.

annotations/<source path>.yaml holds the notes for one source file:

    summary: |                 # what the file is for (markdown)
      ...
    blocks:                    # notes about a range of lines
      - lines: 9-14
        title: Set up a stack
        note: |
          ...
    lines:                     # notes about a single line
      12: |
        ...

annotations/glossary.yaml holds the glossary. Notes link to things with
[[...]]:

    [[swtch]]              a symbol, looked up in this file's program first
    [[user:printf]]        a symbol in a specific program (kernel/user/mkfs/build)
    [[g:satp]]             a glossary entry
    [[kernel/start.c]]     a file;  [[kernel/start.c:25]] a line;  [[:25]] a line here
    [[anything|label]]     any of the above, shown as "label"

annotations/<source path>.lock.json records a hash of every annotated line, so
that if the source ever changes, notes on changed lines are reported as stale.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from html import escape

import yaml
from markdown_it import MarkdownIt

from .config import ANNOTATIONS, SrcFile

MD = MarkdownIt("commonmark", {"html": True, "typographer": True}).enable(["table", "replacements", "smartquotes"])
REF_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]")
GROUPS = ("kernel", "user", "mkfs", "build")


def line_hash(text: str) -> str:
    return hashlib.sha1(text.strip().encode()).hexdigest()[:8]


@dataclass
class Note:
    kind: str           # "block" or "line"
    a: int              # first line
    b: int              # last line
    title: str
    md: str
    html: str = ""


@dataclass
class FileNotes:
    path: str
    summary_md: str = ""
    summary_html: str = ""
    notes: list[Note] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    covered: set[int] = field(default_factory=set)
    coverable: int = 0


@dataclass
class GlossEntry:
    id: str
    term: str
    kind: str
    keys: list[str]
    short_md: str
    body_md: str
    short_html: str = ""
    body_html: str = ""


def _range(v) -> tuple[int, int]:
    if isinstance(v, int):
        return v, v
    a, _, b = str(v).partition("-")
    return int(a), int(b or a)


def sidecar(path: str):
    return ANNOTATIONS / f"{path}.yaml"


def lockfile(path: str):
    return ANNOTATIONS / f"{path}.lock.json"


GLOSSARY_PROBLEMS: list[str] = []


def load_glossary() -> dict[str, GlossEntry]:
    """annotations/glossary.yaml plus every annotations/glossary/*.yaml."""
    GLOSSARY_PROBLEMS.clear()
    paths = [ANNOTATIONS / "glossary.yaml"] + sorted((ANNOTATIONS / "glossary").glob("*.yaml"))
    out: dict[str, GlossEntry] = {}
    origin: dict[str, str] = {}
    key_owner: dict[str, str] = {}
    for p in paths:
        if not p.exists():
            continue
        raw = yaml.safe_load(p.read_text()) or {}
        for gid, e in raw.items():
            if gid in out:
                GLOSSARY_PROBLEMS.append(f"glossary id {gid!r} defined in both "
                                         f"{origin[gid]} and {p.name}")
                continue
            g = GlossEntry(gid, e.get("term", gid), e.get("kind", ""), e.get("keys", []),
                           (e.get("short") or "").strip(), (e.get("body") or "").strip())
            for k in g.keys:
                if k in key_owner:
                    GLOSSARY_PROBLEMS.append(f"glossary key {k!r} claimed by both "
                                             f"{key_owner[k]} and {gid}")
                key_owner[k] = gid
            out[gid] = g
            origin[gid] = p.name
    return out


def load(files: list[SrcFile]) -> dict[str, FileNotes]:
    out = {}
    for f in files:
        p = sidecar(f.path)
        # A big file's notes may be split: <path>.yaml plus <path>.partN.yaml.
        parts = sorted(p.parent.glob(p.name[:-len(".yaml")] + ".part*.yaml")) \
            if p.parent.exists() else []
        if not p.exists() and not parts:
            continue
        raw: dict = {"summary": "", "blocks": [], "lines": {}}
        for q in ([p] if p.exists() else []) + parts:
            r = yaml.safe_load(q.read_text()) or {}
            if r.get("summary"):
                raw["summary"] = (raw["summary"] + "\n\n" + r["summary"]).strip()
            raw["blocks"] += r.get("blocks") or []
            raw["lines"].update(r.get("lines") or {})
        fn = FileNotes(f.path, (raw.get("summary") or "").strip())
        n_lines = len(f.text_lines())
        for b in raw.get("blocks") or []:
            try:
                a, z = _range(b["lines"])
            except (ValueError, KeyError) as e:
                fn.problems.append(f"bad block range {b.get('lines')!r}: {e}")
                continue
            fn.notes.append(Note("block", a, z, b.get("title", ""), (b.get("note") or "").strip()))
        for k, v in (raw.get("lines") or {}).items():
            try:
                a, z = _range(k)
            except ValueError as e:
                fn.problems.append(f"bad line key {k!r}: {e}")
                continue
            text = v if isinstance(v, str) else v.get("note", "")
            fn.notes.append(Note("line", a, z, "", text.strip()))
        fn.notes.sort(key=lambda n: (n.a, n.kind != "block", -n.b))
        for n in fn.notes:
            if not (1 <= n.a <= n.b <= n_lines):
                fn.problems.append(f"lines {n.a}-{n.b} out of range (file has {n_lines})")
            fn.covered.update(range(n.a, n.b + 1))
        out[f.path] = fn
    return out


def coverage(f: SrcFile, fn: FileNotes | None) -> tuple[int, int, list[int]]:
    """(covered, coverable, uncovered line numbers) over non-blank lines."""
    lines = f.text_lines()
    want = [i for i, s in enumerate(lines, 1) if s.strip()]
    got = fn.covered if fn else set()
    missing = [i for i in want if i not in got]
    return len(want) - len(missing), len(want), missing


def stamp(f: SrcFile, fn: FileNotes) -> None:
    lines = f.text_lines()
    lock = {str(i): line_hash(lines[i - 1]) for i in sorted(fn.covered)
            if 1 <= i <= len(lines)}
    lockfile(f.path).write_text(json.dumps(lock, indent=0, sort_keys=True) + "\n")


def stale_lines(f: SrcFile, fn: FileNotes) -> list[int]:
    p = lockfile(f.path)
    if not p.exists():
        return sorted(fn.covered)
    lock = json.loads(p.read_text())
    lines = f.text_lines()
    return [i for i in sorted(fn.covered)
            if lock.get(str(i)) != (line_hash(lines[i - 1]) if i <= len(lines) else None)]


# ------------------------------------------------------------------ rendering

class Linker:
    """Turns [[...]] references into HTML links."""

    def __init__(self, table, files: list[SrcFile], glossary: dict[str, GlossEntry]):
        self.table = table
        self.paths = {f.path for f in files}
        self.glossary = glossary
        self.gkeys = {}
        for g in glossary.values():
            self.gkeys[g.id] = g
            for k in g.keys:
                self.gkeys[k] = g
        self.by_name: dict[str, list] = {}
        for s in table.syms:
            if s.kind in ("local", "parameter"):
                continue
            self.by_name.setdefault(s.name, []).append(s)

    def symbol(self, ref: str, group: str | None):
        name, _, at = ref.partition("@")
        g = None
        if ":" in name and name.split(":", 1)[0] in GROUPS:
            g, name = name.split(":", 1)
        cands = self.by_name.get(name, [])
        if at:
            cands = [s for s in cands if s.defloc[0] == at]
        if g:
            cands = [s for s in cands if s.group == g]
        elif len(cands) > 1:
            cands = [s for s in cands if s.group == (group or "kernel")] or cands
        if len(cands) > 1:
            # Prefer what a reader most likely means by a bare name: a function or
            # global over a struct tag over a struct field; a definition over a
            # prototype with no definition.
            def rank(s):
                k = s.kind.replace(" (declared only)", "")
                order = ["function", "label", "variable", "macro", "typedef", "linker symbol",
                         "make variable", "make target", "enumerator", "section", "struct",
                         "union", "enum", "output section", "field"]
                return (order.index(k) if k in order else len(order),
                        "declared only" in s.kind)
            best = min(rank(s) for s in cands)
            cands = [s for s in cands if rank(s) == best]
        return cands

    def render(self, md: str, root: str, here: str, group: str | None,
               problems: list[str]) -> str:
        def sub(m: re.Match) -> str:
            target, label = m.group(1).strip(), m.group(2)
            if target.startswith("tour:"):
                from .tours import PLAN, plan_url
                try:
                    num = int(target[5:])
                except ValueError:
                    num = -1
                if num not in PLAN:
                    problems.append(f"unknown tour {target}")
                    return escape(label or target)
                return (f'<a class="tourlink" href="{root}{plan_url(num)}">'
                        f'{escape(label or f"Tour {num}: {PLAN[num][1]}")}</a>')
            if target.startswith("concept:"):
                from .concepts import CONCEPTS
                slug, _, anchor = target[8:].partition("#")
                hits = sorted(CONCEPTS.glob(f"*-{slug}.md")) if CONCEPTS.exists() else []
                if not hits:
                    problems.append(f"unknown concept {target}")
                    return escape(label or slug)
                title = slug.replace("-", " ")
                head = hits[0].read_text().split("\n---\n", 1)[0]
                tm = re.search(r"^title:\s*(.+)$", head, re.M)
                if tm:
                    title = tm.group(1).strip().strip("\"'")
                frag = f"#{escape(anchor)}" if anchor else ""
                return (f'<a class="conceptlink" href="{root}concepts/{escape(slug)}.html{frag}">'
                        f'{escape(label or title)}</a>')
            if target.startswith("g:"):
                g = self.gkeys.get(target[2:])
                if not g:
                    problems.append(f"unknown glossary entry {target}")
                    return escape(label or target[2:])
                return (f'<a class="gl" data-gk="{escape(g.id)}" '
                        f'href="{root}glossary.html#{escape(g.id)}">{escape(label or g.term)}</a>')
            fm = re.fullmatch(r"([\w./-]*)(?::(\d+)(?:-(\d+))?)?", target)
            if fm and (fm.group(1) in self.paths or (fm.group(1) == "" and fm.group(2))):
                path = fm.group(1) or here
                line = fm.group(2)
                if line:
                    rng = line + (f"–{fm.group(3)}" if fm.group(3) else "")
                    if path == here:
                        text = label or f"line{'s' if fm.group(3) else ''} {rng}"
                        return (f'<a class="ln-ref" data-line="{line}" '
                                f'data-to="{fm.group(3) or line}" href="#L{line}">{escape(text)}</a>')
                    text = escape(label) if label else f"<code>{escape(path)}:{rng}</code>"
                    return f'<a class="fl" href="{root}src/{path}.html#L{line}">{text}</a>'
                text = escape(label) if label else f"<code>{escape(path)}</code>"
                return f'<a class="fl" href="{root}src/{path}.html">{text}</a>'
            cands = self.symbol(target, group)
            if not cands:
                problems.append(f"unknown symbol [[{target}]]")
                return f"<code>{escape(label or target)}</code>"
            if len(cands) > 1:
                problems.append(f"ambiguous [[{target}]]: " +
                                ", ".join(f"{s.group}:{s.name}@{s.defloc[0]}" for s in cands))
            s = cands[0]
            text = escape(label) if label else f"<code>{escape(s.name)}</code>"
            return (f'<a class="sy ref" data-s="{s.id}" '
                    f'href="{root}src/{s.defloc[0]}.html#L{s.defloc[1]}">{text}</a>')

        return MD.render(REF_RE.sub(sub, md))

    def render_inline(self, md: str, root: str, problems: list[str]) -> str:
        html = self.render(md, root, "", None, problems).strip()
        if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
            html = html[3:-4]
        return html
