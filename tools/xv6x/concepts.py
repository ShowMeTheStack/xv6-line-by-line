"""Concept pages, figures and stack-switch points.

annotations/concepts/NN-slug.md is one concept page:

    ---
    title: The stacks of xv6
    summary: One sentence for the index card.
    ---
    Markdown with [[links]]. A line {{fig:name|Caption text}} embeds
    annotations/figs/name.svg inline (so it follows the light/dark theme).

annotations/figs/*.svg are shared by concept pages and tour steps (`figure: name`).
SVGs should colour themselves with the site's CSS variables (var(--fg), var(--st-user)...).

annotations/stackswitch.yaml lists every instruction that moves sp to a different stack:

    - file: kernel/trampoline.S
      line: 75
      from: none
      to: kernel
      note: "uservec loads the process's kernel stack pointer from the trapframe."
"""

import re
from dataclasses import dataclass
from html import escape

import yaml

from .config import ANNOTATIONS

CONCEPTS = ANNOTATIONS / "concepts"
FIGS = ANNOTATIONS / "figs"
STACKSWITCH = ANNOTATIONS / "stackswitch.yaml"


@dataclass
class Concept:
    num: int
    slug: str
    title: str
    summary: str
    body: str

    @property
    def url(self) -> str:
        return f"concepts/{self.slug}.html"


def load() -> tuple[list[Concept], list[str]]:
    out, probs = [], []
    if not CONCEPTS.exists():
        return out, probs
    for p in sorted(CONCEPTS.glob("*.md")):
        m = re.fullmatch(r"(\d+)-([\w-]+)\.md", p.name)
        if not m:
            continue
        text = p.read_text()
        meta, body = {}, text
        if text.startswith("---\n"):
            head, _, body = text[4:].partition("\n---\n")
            try:
                meta = yaml.safe_load(head) or {}
            except yaml.YAMLError as e:
                probs.append(f"{p.name}: front matter: {e}")
        if not meta.get("title"):
            probs.append(f"{p.name}: missing title")
        out.append(Concept(int(m.group(1)), m.group(2), str(meta.get("title", m.group(2))),
                           str(meta.get("summary", "")), body))
    return out, probs


FIG_RE = re.compile(r"<p>\{\{fig:([\w-]+)(?:\|(.*?))?\}\}</p>", re.S)


def figure_html(name: str, caption_html: str, problems: list[str]) -> str:
    f = FIGS / f"{name}.svg"
    if not f.exists():
        problems.append(f"missing figure {name!r}")
        return ""
    svg = f.read_text()
    svg = re.sub(r"<\?xml.*?\?>\s*", "", svg)
    cap = f"<figcaption>{caption_html}</figcaption>" if caption_html else ""
    return f'<figure class="fig" id="fig-{escape(name)}">{svg}{cap}</figure>'


def embed_figures(html: str, render_inline, problems: list[str]) -> str:
    """Replace <p>{{fig:name|caption}}</p> (as left by markdown) with inline SVG figures."""
    def sub(m: re.Match) -> str:
        cap = render_inline(m.group(2)) if m.group(2) else ""
        return figure_html(m.group(1), cap, problems)
    return FIG_RE.sub(sub, html)


def load_stack_switches() -> tuple[dict[str, list[dict]], list[str]]:
    """path -> [{line, from, to, note}] for every sp-changing instruction."""
    out: dict[str, list[dict]] = {}
    probs: list[str] = []
    if not STACKSWITCH.exists():
        return out, probs
    try:
        raw = yaml.safe_load(STACKSWITCH.read_text()) or []
    except yaml.YAMLError as e:
        return out, [f"stackswitch.yaml: {e}"]
    for i, e in enumerate(raw, 1):
        if not all(k in e for k in ("file", "line", "to", "note")):
            probs.append(f"stackswitch.yaml entry {i}: needs file, line, to, note")
            continue
        out.setdefault(e["file"], []).append(
            {"line": int(e["line"]), "from": str(e.get("from", "")), "to": str(e["to"]),
             "note": str(e["note"])})
    return out, probs


LOCKS = ANNOTATIONS / "locks.yaml"
LOCK_OPS = ("acquire", "release", "acquiresleep", "releasesleep", "holding", "holdingsleep",
            "initlock", "initsleeplock")
IRQ_OPS = ("push_off", "pop_off", "intr_on", "intr_off")
_OP_RE = re.compile(r"\b(" + "|".join(LOCK_OPS + IRQ_OPS) + r")\(")


def load_locks() -> tuple[list[dict], list[str]]:
    """The lock inventory, annotations/locks.yaml."""
    if not LOCKS.exists():
        return [], []
    try:
        raw = yaml.safe_load(LOCKS.read_text()) or []
    except yaml.YAMLError as e:
        return [], [f"locks.yaml: {e}"]
    probs = []
    for i, e in enumerate(raw, 1):
        for k in ("id", "name", "kind", "match", "protects", "decl"):
            if k not in e:
                probs.append(f"locks.yaml entry {i}: needs {k}")
        if e.get("kind") not in ("spin", "sleep"):
            probs.append(f"locks.yaml entry {i}: kind must be spin or sleep")
    return raw, probs


def _arg(text: str, start: int) -> str:
    """The first argument of the call whose '(' is at text[start - 1]."""
    depth, i = 0, start
    while i < len(text):
        c = text[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            if depth == 0:
                break
            depth -= 1
        elif c == "," and depth == 0:
            break
        i += 1
    return text[start:i]


def load_lock_sites(files) -> tuple[dict[str, dict[int, list[dict]]], list[str]]:
    """path -> line -> [{op, id, name, kind}] for every lock and interrupt-state call in
    kernel/*.c (definitions, prototypes and comments are skipped)."""
    locks, probs = load_locks()
    out: dict[str, dict[int, list[dict]]] = {}
    for f in files:
        if not (f.path.startswith("kernel/") and f.path.endswith(".c")):
            continue
        for n, line in enumerate(f.text_lines(), 1):
            code = line.split("//")[0]
            s = code.strip()
            if not s or s.startswith("*") or s.startswith("/*"):
                continue
            for m in _OP_RE.finditer(code):
                op = m.group(1)
                arg = _arg(code, m.end()).strip()
                if "struct" in arg or arg == "void" or code[:m.start()].strip() in (
                        "void", "int", "static void", "static int"):
                    continue          # a definition or prototype, not a call
                if op in IRQ_OPS:
                    out.setdefault(f.path, {}).setdefault(n, []).append(
                        {"op": op, "id": "", "name": "", "kind": "irq"})
                    continue
                key = arg.replace("&", "").replace(" ", "")
                hits = [l for l in locks if key in l.get("match", [])
                        and (not l.get("files") or f.path in l["files"])]
                if len(hits) != 1:
                    probs.append(f"{f.path}:{n}: {op}({arg}) matches {len(hits)} locks in locks.yaml")
                    continue
                l = hits[0]
                out.setdefault(f.path, {}).setdefault(n, []).append(
                    {"op": op, "id": l["id"], "name": l["name"], "kind": l["kind"],
                     "protects": l.get("protects", "")})
    return out, probs
