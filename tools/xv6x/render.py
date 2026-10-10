"""Write the static site: one page per source file plus shared data files."""

import json
import re
import shutil
from collections import defaultdict
from html import escape

from .annotations import FileNotes, GlossEntry, Linker, coverage
from .config import COMMIT, MINOR, SITE, UPSTREAM, WEB, SrcFile
from .model import FileFacts
from .symbols import SymbolTable

ROLE_CODE = {"def": 0, "decl": 1, "assign": 2, "ref": 3}
LANG_NAME = {"c": "C", "h": "C header", "asm": "RISC-V assembly", "ld": "linker script",
             "make": "Makefile", "perl": "Perl", "python": "Python", "yaml": "YAML",
             "gdb": "GDB script", "elisp": "Emacs Lisp", "text": "text"}
GROUP_NAME = {"kernel": "kernel", "user": "user program / library",
              "mkfs": "host tool (runs on your computer, not in xv6)",
              "build": "build system"}


def page_url(path: str) -> str:
    return f"src/{path}.html"


def rel_root(path: str) -> str:
    return "../" * (path.count("/") + 1)


# ------------------------------------------------------------------ code lines

def render_lines(f: SrcFile, ff: FileFacts, table: SymbolTable, root: str,
                 fn: "FileNotes | None" = None, only: tuple[int, int] | None = None,
                 focus: tuple[int, int] | None = None) -> str:
    """Render a file's lines. With `only`, render just that range as an excerpt
    whose line numbers link to the full file page; `focus` marks lines inside it."""
    lines = f.text_lines()
    lcls: dict[int, set[str]] = defaultdict(set)
    for note in (fn.notes if fn else ()):
        for i in range(note.a, note.b + 1):
            lcls[i].add("hn" if note.kind == "line" else "ib")
        if note.kind == "block":
            lcls[note.a].add("bs")
    toks_by_line = defaultdict(list)
    for t in ff.toks:
        toks_by_line[t.line].append(t)
    links_by_line = defaultdict(list)
    for (line, c0, c1, syms, role) in table.links.get(f.path, []):
        links_by_line[line].append((c0, c1, ("s", syms, role)))
    for fl in ff.flinks:
        links_by_line[fl.line].append((fl.c0, fl.c1, ("f", fl.target, fl.title)))

    out = []
    for n, text in enumerate(lines, 1):
        if only and not (only[0] <= n <= only[1]):
            continue
        cls = [""] * len(text)
        gloss = [""] * len(text)
        for t in toks_by_line.get(n, ()):
            for i in range(t.c0, min(t.c1, len(text))):
                cls[i] = t.cls
                gloss[i] = t.gloss
        link = [None] * len(text)
        for c0, c1, target in links_by_line.get(n, ()):
            if any(link[i] is not None for i in range(c0, min(c1, len(text)))):
                continue
            for i in range(c0, min(c1, len(text))):
                link[i] = (c0, target)
        extra = "".join(" " + c for c in sorted(lcls.get(n, ())))
        body = _line_html(text, cls, gloss, link, n, root)
        if only:
            fx = " fx" if focus and focus[0] <= n <= focus[1] else " cx"
            out.append(f'<div class="l{fx}"><a class="n2" href="{root}{page_url(f.path)}#L{n}" '
                       f'title="Open {escape(f.path)} at line {n}">{n}</a>'
                       f'<span class="t">{body}</span></div>')
        else:
            out.append(f'<div class="l{extra}" id="L{n}"><a class="n" href="#L{n}">{n}</a>'
                       f'<span class="t">{body}</span></div>')
    return "\n".join(out)


def _open_link(target, n: int, root: str) -> str:
    if target[0] == "f":
        _, path, title = target
        return (f'<a class="fl" href="{root}{page_url(path)}" '
                f'title="{escape(title)}">')
    _, syms, role = target
    ids = ",".join(str(s.id) for s in syms)
    d = syms[0].defloc
    if role == "def":
        href = f"#L{n}"
    else:
        href = f"{root}{page_url(d[0])}#L{d[1]}"
    return f'<a class="sy {role}" data-s="{ids}" href="{href}">'


def _line_html(text, cls, gloss, link, n, root) -> str:
    parts, i, cur_link = [], 0, None
    while i < len(text):
        j = i + 1
        while j < len(text) and cls[j] == cls[i] and gloss[j] == gloss[i] and \
                link[j] == link[i]:
            j += 1
        if link[i] != cur_link:
            if cur_link is not None:
                parts.append("</a>")
            if link[i] is not None:
                parts.append(_open_link(link[i][1], n, root))
            cur_link = link[i]
        chunk = escape(text[i:j], quote=False)
        if cls[i] or gloss[i]:
            g = f' data-g="{escape(gloss[i])}"' if gloss[i] else ""
            parts.append(f'<span class="{cls[i]}"{g}>{chunk}</span>')
        else:
            parts.append(chunk)
        i = j
    if cur_link is not None:
        parts.append("</a>")
    return "".join(parts)


# ------------------------------------------------------------------ page chrome

ANNOTATED: set[str] = set()


def file_tree(files: list[SrcFile], current: str, root: str) -> str:
    dirs: dict[str, list[SrcFile]] = defaultdict(list)
    for f in files:
        d = f.path.rsplit("/", 1)[0] if "/" in f.path else ""
        dirs[d].append(f)
    order = ["", "kernel", "user", "mkfs"]
    order += sorted(d for d in dirs if d not in order)
    out = []
    for d in order:
        if d not in dirs:
            continue
        items = sorted(dirs[d], key=lambda f: (f.path in MINOR, f.path.lower()))
        is_open = d in ("", "kernel") or current.startswith(d + "/") or \
            (d == "" and "/" not in current)
        label = d + "/" if d else "top level"
        out.append(f'<details{" open" if is_open else ""}><summary>{escape(label)}</summary><ul>')
        for f in items:
            name = f.path.rsplit("/", 1)[-1]
            here = ' class="here" aria-current="page"' if f.path == current else ""
            minor = " minor" if f.path in MINOR else ""
            gen = ' <span class="badge">gen</span>' if f.generated else ""
            if f.path in ANNOTATED:
                gen += ' <span class="dot" title="annotated"></span>'
            out.append(f'<li class="lang-{f.lang}{minor}"><a{here} '
                       f'href="{root}{page_url(f.path)}">{escape(name)}</a>{gen}</li>')
        out.append("</ul></details>")
    return "\n".join(out)


HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{root}assets/app.css">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%232456b8'/%3E%3Ctext x='16' y='22' font-family='monospace' font-size='15' font-weight='700' fill='white' text-anchor='middle'%3Exv6%3C/text%3E%3C/svg%3E">
<script>try{{var t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
</head>
"""

TOP = """<header class="top">
  <button class="icon-btn" id="tree-toggle" aria-label="Show files" title="Files">&#9776;</button>
  <a class="brand" href="{root}index.html">xv6<span>, line by line</span></a>
  <div class="crumb">{crumb}</div>
  <nav class="toplinks" aria-label="Sections">
  <a class="toplink" href="{root}tours/index.html">Tours</a>
  <a class="toplink" href="{root}concepts/index.html">Concepts</a>
  <a class="toplink" href="{root}glossary.html">Glossary</a>
  <a class="toplink" href="{root}labs/index.html">Labs</a>
  <a class="toplink" href="{root}test/index.html">Test<span class="tlw"> yourself</span></a>
  <a class="toplink ab-top" href="{root}about.html">About<span class="tlw"> me</span></a>
  </nav>
  <div class="search">
    <input id="q" type="search" placeholder="Search files and symbols  ( / )" autocomplete="off" spellcheck="false" aria-label="Search files and symbols">
    <div id="results" role="listbox" hidden></div>
  </div>
  <button class="icon-btn" id="theme" aria-label="Toggle dark mode" title="Light / dark">&#9680;</button>
</header>
"""

SCRIPTS = """<script src="{root}assets/xref.js" defer></script>
<script src="{root}assets/src.js" defer></script>
<script src="{root}assets/app.js" defer></script>
"""


def render_notes(f: SrcFile, fn: FileNotes, linker: Linker, root: str) -> str:
    out = []
    for n in fn.notes:
        html = linker.render(n.md, root, f.path, f.group, fn.problems)
        rng = f"{n.a}" if n.a == n.b else f"{n.a}–{n.b}"
        label = f"Line{'s' if n.a != n.b else ''} {rng}"
        title = f"<h3>{escape(n.title)}</h3>" if n.title else ""
        out.append(f'<section class="note {n.kind}" data-a="{n.a}" data-b="{n.b}">'
                   f'<div class="nl"><a class="ln-ref" data-line="{n.a}" data-to="{n.b}" '
                   f'href="#L{n.a}">{label}</a></div>{title}{html}</section>')
    return "\n".join(out)


STACKPTS: dict[str, list[dict]] = {}


def _stackpts(path: str, linker: Linker, root: str) -> str:
    pts = STACKPTS.get(path)
    if not pts:
        return ""
    probs: list[str] = []
    data = {str(p["line"]): {"from": p["from"], "to": p["to"],
                             "note": linker.render_inline(p["note"], root, probs)} for p in pts}
    return ('<script type="application/json" id="stackpts">'
            + json.dumps(data).replace("</", "<\\/") + "</script>")


LOCKPTS: dict[str, dict[int, list[dict]]] = {}


def _lockpts(path: str, linker: Linker, root: str) -> str:
    pts = LOCKPTS.get(path)
    if not pts:
        return ""
    probs: list[str] = []
    data = {str(n): [{"op": o["op"], "id": o["id"], "name": o["name"], "kind": o["kind"],
                      "protects": linker.render_inline(o.get("protects", ""), root, probs)}
                     for o in ops] for n, ops in pts.items()}
    return ('<script type="application/json" id="lockpts">'
            + json.dumps(data).replace("</", "<\\/") + "</script>")


def render_file_page(f: SrcFile, ff: FileFacts, table: SymbolTable, files: list[SrcFile],
                     included_by: dict[str, list[str]], fn: FileNotes | None,
                     linker: Linker, tourlines: str = "") -> str:
    root = rel_root(f.path)
    lines = f.text_lines()
    meta = [LANG_NAME.get(f.lang, f.lang), f"{len(lines)} lines"]
    got, want, _ = coverage(f, fn)
    if fn and want:
        meta.append(f"annotated {100 * got // want}%")
    summary = notes_html = ""
    if fn:
        if fn.summary_md:
            summary = ('<details class="about" open><summary>About this file</summary>' +
                       linker.render(fn.summary_md, root, f.path, f.group, fn.problems) +
                       "</details>")
        notes_html = render_notes(f, fn, linker, root)
    if f.group:
        meta.append(GROUP_NAME[f.group])
    gen_note = ""
    if f.generated:
        gen_note = ('<p class="gen-note">This file is <b>generated</b> by the build '
                    '(it is not in the xv6 repository). It is shown here as the build '
                    f'produces it. See <a href="{root}{page_url("user/usys.pl")}">'
                    'user/usys.pl</a>.</p>')
    inc = ""
    if included_by.get(f.path):
        links = ", ".join(f'<a href="{root}{page_url(p)}">{escape(p)}</a>'
                          for p in included_by[f.path])
        inc = (f'<details class="incby"><summary>Included by {len(included_by[f.path])} '
               f'file{"s" if len(included_by[f.path]) != 1 else ""}</summary>{links}</details>')
    crumb = escape(f.path)
    upstream = f"{UPSTREAM}/blob/{COMMIT}/{f.path}" if not f.generated else ""
    up_link = f' &middot; <a href="{upstream}">upstream</a>' if upstream else ""
    return (HEAD.format(title=f"{escape(f.path)} · xv6, line by line", root=root) +
            f'<body data-root="{root}" data-file="{escape(f.path)}">\n' +
            TOP.format(root=root, crumb=crumb) +
            '<div class="layout">\n'
            f'<nav class="tree" id="tree" aria-label="Files">{file_tree(files, f.path, root)}</nav>\n'
            '<main class="main">\n'
            f'<div class="file-head"><h1>{escape(f.path)}</h1>'
            f'<p class="meta">{" &middot; ".join(escape(m) for m in meta)}{up_link}</p>'
            f'{gen_note}{inc}{summary}'
            + ('<div class="note-bar"><button id="read-start" class="btn">Start reading '
               'the notes</button><label class="inline-toggle"><input type="checkbox" '
               'id="inline"> Show notes inline</label></div>' if fn and fn.notes else "") +
            '</div>\n'
            f'<div class="code lang-{f.lang}">\n{render_lines(f, ff, table, root, fn)}\n</div>\n'
            f'<div id="notes-data" hidden>{notes_html}</div>{tourlines}{_stackpts(f.path, linker, root)}{_lockpts(f.path, linker, root)}\n'
            '</main>\n'
            '<aside class="panel" id="panel" aria-label="Details">'
            '<div class="panel-tabs" role="tablist">'
            '<button role="tab" data-tab="notes" aria-selected="true">Notes</button>'
            '<button role="tab" data-tab="refs" aria-selected="false">Symbol</button>'
            '<button class="icon-btn panel-close" id="panel-close" aria-label="Close panel">&times;</button>'
            '</div>'
            '<div class="panel-body" id="tab-notes"><p class="empty">' +
            ("Click any line of code to read its notes, or use <b>Start reading</b>. "
             "Keys: <kbd>j</kbd> next note, <kbd>k</kbd> previous note." if fn and fn.notes
             else "This file has not been annotated yet. Hover any highlighted name to "
             "see what it is; click it to jump to its definition. The <b>Symbol</b> tab "
             "lists every place a name is used.") + '</p></div>'
            '<div class="panel-body" id="tab-refs" hidden><p class="empty">Click a name in '
            'the code to see its definition and every place it is used.</p></div>'
            '</aside>\n'
            '</div>\n' + SCRIPTS.format(root=root) + "</body>\n</html>\n")


# ------------------------------------------------------------------ index page

READING_ORDER = [
    ("Makefile", "How the kernel, the user programs and the disk image are built."),
    ("kernel/kernel.ld", "Where in memory each part of the kernel is placed."),
    ("kernel/entry.S", "The first instructions every CPU runs."),
    ("kernel/start.c", "Machine mode setup, then the switch to supervisor mode."),
    ("kernel/main.c", "Initializes every kernel subsystem and starts the first process."),
    ("kernel/memlayout.h", "The physical and virtual memory map."),
    ("kernel/vm.c", "Page tables: how virtual addresses become physical ones."),
    ("kernel/proc.c", "Processes, the scheduler, fork/exit/wait."),
    ("kernel/trampoline.S", "The bridge between user space and the kernel."),
    ("kernel/trap.c", "Handling system calls, interrupts and faults."),
    ("kernel/syscall.c", "Dispatching a system call to its handler."),
    ("kernel/fs.c", "The file system: inodes, directories, path names."),
]


def render_index(files: list[SrcFile], table: SymbolTable, tour_list=()) -> str:
    root = ""
    from .tourrender import LEARNING_PATH
    by_num = {t.num: t for t in tour_list}
    tours_html = ""
    if tour_list:
        stops = "".join(f'<a class="pstop" href="{by_num[n].url}" data-tour="{n}"><span>{n}</span>'
                        f'{escape(by_num[n].title)}</a>' for n in LEARNING_PATH if n in by_num)
        tours_html = ('<h2>Start with a guided tour</h2><p>The <a href="tours/index.html">'
                      f'{len(tour_list)} guided tours</a> walk through the running system step '
                      'by step, showing the machine state and what the other CPUs are doing. '
                      f'A good path for beginners:</p><div class="lpath">{stops}</div>'
                      '<p>Lost? Four questions locate you at any moment: which privilege '
                      'mode, which stack, which page table, and which locks this CPU holds '
                      '(with interrupts on or off). The <a href="concepts/index.html">'
                      'concept pages</a> explain each one, and every tour step shows all four.'
                      '</p>')
    by_dir: dict[str, list[SrcFile]] = defaultdict(list)
    for f in files:
        by_dir[f.path.split("/")[0] if "/" in f.path else ""].append(f)
    total = sum(len(f.text_lines()) for f in files)
    order = "".join(
        f'<li><a href="{page_url(p)}"><code>{escape(p)}</code></a> &mdash; {escape(d)}'
        f'{" <span class=badge>annotated</span>" if p in ANNOTATED else ""}</li>'
        for p, d in READING_ORDER)
    sections = []
    for d, label in (("kernel", "The kernel"), ("user", "User programs and library"),
                     ("mkfs", "mkfs: builds the disk image"), ("", "Build and project files")):
        rows = "".join(
            f'<tr><td><a href="{page_url(f.path)}">{escape(f.path)}</a>'
            f'{" <span class=badge>gen</span>" if f.generated else ""}'
            f'{" <span class=badge>annotated</span>" if f.path in ANNOTATED else ""}</td>'
            f'<td>{LANG_NAME.get(f.lang, f.lang)}</td><td class="num">{len(f.text_lines())}</td></tr>'
            for f in sorted(by_dir.get(d, []), key=lambda f: (f.path in MINOR, f.path)))
        sections.append(f'<h2>{label}</h2><table class="files"><thead><tr><th>File</th>'
                        f'<th>Language</th><th class="num">Lines</th></tr></thead>'
                        f'<tbody>{rows}</tbody></table>')
    return (HEAD.format(title="xv6, line by line", root=root) +
            '<body data-root="" data-file="">\n' + TOP.format(root=root, crumb="") +
            '<div class="layout home">\n'
            f'<nav class="tree" id="tree" aria-label="Files">{file_tree(files, "", root)}</nav>\n'
            '<main class="main prose">\n'
            '<h1>xv6, line by line</h1>\n'
            '<p class="lede">xv6 is a small, complete Unix-like operating system written at MIT '
            'for teaching. It runs on RISC-V. This site presents every file of it, so you can '
            'read the whole thing, from the Makefile to the scheduler, and follow any name to '
            'where it is defined and everywhere it is used.</p>\n'
            '<h2>How to read this site</h2><ul class="howto">'
            '<li><b>Hover</b> over a highlighted name to see what it is and where it is defined.</li>'
            '<li><b>Click</b> a name to jump to its definition. The <b>Symbol</b> panel lists '
            'every place the name is used, across C, assembly, linker scripts and the Makefile.</li>'
            '<li>Press <kbd>/</kbd> to search for any file, function, struct, macro or label.</li>'
            '<li>In an annotated file, click any line to read its notes in the side panel, or '
            'press <b>Start reading</b> and step through with <kbd>j</kbd> / <kbd>k</kbd>. '
            '<b>Show notes inline</b> puts the notes between the lines instead.</li>'
            '<li>Dotted underlines are glossary terms; the <a href="glossary.html">glossary</a> '
            'lists them all.</li>'
            '<li>Your browser\'s Back button returns you to where you were.</li></ul>\n'
            + tours_html +
            '<a class="creator" href="about.html"><img src="img/jpm.jpg" alt="" width="64" height="88">'
            '<span><small>Created by</small><b>Jyotiprakash Mishra</b>'
            '<span>Author of <i>RISC-V Architecture and XV6</i> (De Gruyter Brill, 2026), '
            'the book this site accompanies. Meet the creator &rarr;</span></span></a>\n'
            f'<h2>A suggested reading order</h2><ol class="order">{order}</ol>\n'
            + "".join(sections) +
            f'<p class="foot">{len(files)} files &middot; {total:,} lines &middot; '
            f'{len(table.syms):,} named symbols. Source: <a href="{UPSTREAM}/tree/{COMMIT}">'
            f'mit-pdos/xv6-riscv @ {COMMIT}</a> (MIT license).</p>\n'
            '</main>\n</div>\n' + SCRIPTS.format(root=root) + "</body>\n</html>\n")


# ------------------------------------------------------------------ data files

def xref_js(files: list[SrcFile], table: SymbolTable, gloss: dict) -> str:
    fidx = {f.path: i for i, f in enumerate(files)}
    fl = [[f.path, f.lang, f.group or "", len(f.text_lines()), int(f.generated)] for f in files]
    syms = []
    for s in table.syms:
        occ = []
        for (path, line, col), (width, role) in sorted(s.occ.items()):
            occ += [fidx[path], line, col, ROLE_CODE[role]]
        syms.append([s.name, s.kind, s.type, s.group, s.lang, fidx[s.defloc[0]],
                     s.defloc[1], occ])
    data = {"files": fl, "syms": syms, "gloss": gloss, "commit": COMMIT}
    return "window.XREF=" + json.dumps(data, separators=(",", ":")) + ";\n"


def src_js(files: list[SrcFile]) -> str:
    return "window.SRC=" + json.dumps([f.text_lines() for f in files],
                                      separators=(",", ":")) + ";\n"


def render_glossary(files: list[SrcFile], glossary: dict[str, GlossEntry],
                    linker: Linker, problems: list[str]) -> str:
    root = ""
    kinds: dict[str, list[GlossEntry]] = defaultdict(list)
    for g in glossary.values():
        kinds[g.kind or "other"].append(g)
    parts = []
    for kind in sorted(kinds):
        parts.append(f"<h2>{escape(kind)}</h2>")
        for g in sorted(kinds[kind], key=lambda g: g.term.lower()):
            body = linker.render(g.body_md, root, "", None, problems) if g.body_md else ""
            parts.append(f'<section class="gloss" id="{escape(g.id)}"><h3>{escape(g.term)}</h3>'
                         f'<div class="gshort">{linker.render(g.short_md, root, "", None, problems)}'
                         f'</div>{body}</section>')
    return (HEAD.format(title="Glossary · xv6, line by line", root=root) +
            '<body data-root="" data-file="">\n' + TOP.format(root=root, crumb="glossary") +
            '<div class="layout home">\n'
            f'<nav class="tree" id="tree" aria-label="Files">{file_tree(files, "", root)}</nav>\n'
            '<main class="main prose glossary">\n<h1>Glossary</h1>\n'
            '<p class="lede">Every term the notes rely on, in plain language. Hovering a '
            'RISC-V instruction, register or CSR in the code shows its entry.</p>\n' +
            "".join(parts) + '</main>\n</div>\n' + SCRIPTS.format(root=root) +
            "</body>\n</html>\n")


def render_concept(c, concepts: list, files: list[SrcFile], linker: Linker,
                   problems: list[str]) -> str:
    from .concepts import embed_figures
    root = "../"
    body = linker.render(c.body, root, "", None, problems)
    body = embed_figures(body, lambda t: linker.render_inline(t, root, problems), problems)
    # "## Heading {#anchor}" gives the heading an id
    body = re.sub(r"<(h[2-4])>(.*?)\s*\{#([\w-]+)\}</\1>", r'<\1 id="\3">\2</\1>', body)
    i = concepts.index(c)
    nav = []
    if i > 0:
        nav.append(f'<a class="btn" href="{root}{concepts[i - 1].url}">&larr; '
                   f'{escape(concepts[i - 1].title)}</a>')
    nav.append(f'<a class="btn" href="index.html">All concepts</a>')
    if i + 1 < len(concepts):
        nav.append(f'<a class="btn" href="{root}{concepts[i + 1].url}">'
                   f'{escape(concepts[i + 1].title)} &rarr;</a>')
    return (HEAD.format(title=f"{c.title} · xv6, line by line", root=root) +
            f'<body data-root="{root}" data-file="">\n' + TOP.format(root=root, crumb="concepts") +
            '<div class="layout home">\n'
            f'<nav class="tree" id="tree" aria-label="Files">{file_tree(files, "", root)}</nav>\n'
            f'<main class="main prose concept">\n<p class="kicker">Concept {c.num}</p>'
            f'<h1>{escape(c.title)}</h1>\n{body}'
            f'<div class="outro-nav">{"".join(nav)}</div></main>\n</div>\n'
            + SCRIPTS.format(root=root) + "</body>\n</html>\n")


def render_concepts_index(concepts: list, files: list[SrcFile], linker: Linker,
                          problems: list[str]) -> str:
    root = "../"
    cards = "".join(
        f'<a class="tcard" href="{root}{c.url}"><span class="tnum">{c.num}</span>'
        f'<span class="ttitle">{escape(c.title)}</span>'
        f'<span class="tsumm">{linker.render_inline(c.summary, root, problems)}</span></a>'
        for c in concepts)
    return (HEAD.format(title="Concepts · xv6, line by line", root=root) +
            f'<body data-root="{root}" data-file="">\n' + TOP.format(root=root, crumb="concepts") +
            '<div class="layout home">\n'
            f'<nav class="tree" id="tree" aria-label="Files">{file_tree(files, "", root)}</nav>\n'
            '<main class="main prose concepts">\n<h1>Concepts</h1>\n'
            '<p class="lede">The ideas that cut across many files, each explained once, with '
            'diagrams, and linked to the code and the tours that use them.</p>\n'
            f'<div class="tcards">{cards}</div></main>\n</div>\n'
            + SCRIPTS.format(root=root) + "</body>\n</html>\n")


def gloss_js_data(glossary: dict[str, GlossEntry], linker: Linker, problems) -> dict:
    """key -> [id, term, kind, short html]; links use @@/ for the site root."""
    out = {}
    for g in glossary.values():
        short = linker.render_inline(g.short_md, "@@/", problems)
        for k in [g.id] + g.keys:
            out[k] = [g.id, g.term, g.kind, short]
    return out


def write_site(files: list[SrcFile], facts: dict[str, FileFacts], table: SymbolTable,
               notes: dict[str, FileNotes] | None = None,
               glossary: dict[str, GlossEntry] | None = None) -> list[str]:
    from . import tourrender, tours as tourmod
    notes = notes or {}
    glossary = glossary or {}
    linker = Linker(table, files, glossary)
    tour_list = tourmod.load(files)
    tour_index = tourmod.line_index(tour_list)
    tours_by_num = {t.num: t for t in tour_list}
    ANNOTATED.clear()
    ANNOTATED.update(p for p, fn in notes.items() if fn.notes)
    problems: list[str] = []
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "assets").mkdir(parents=True)
    for name in ("app.css", "app.js", "tour.js", "quiz.js", "labs.js", "about.js"):
        shutil.copy(WEB / name, SITE / "assets" / name)
    shutil.copytree(WEB / "img", SITE / "img")
    (SITE / ".nojekyll").write_text("")
    gl_problems: list[str] = []
    (SITE / "assets" / "xref.js").write_text(
        xref_js(files, table, gloss_js_data(glossary, linker, gl_problems)))
    (SITE / "glossary.html").write_text(render_glossary(files, glossary, linker, gl_problems))
    from . import concepts as conmod
    concept_list, cprobs = conmod.load()
    problems += [f"concepts: {p}" for p in cprobs]
    (SITE / "concepts").mkdir()
    for c in concept_list:
        cp: list[str] = []
        (SITE / c.url).write_text(render_concept(c, concept_list, files, linker, cp))
        problems += [f"concept {c.slug}: {p}" for p in cp]
    (SITE / "concepts" / "index.html").write_text(
        render_concepts_index(concept_list, files, linker, problems))
    switches, sprobs = conmod.load_stack_switches()
    problems += sprobs
    STACKPTS.clear()
    STACKPTS.update(switches)
    lsites, lprobs = conmod.load_lock_sites(files)
    problems += lprobs
    LOCKPTS.clear()
    LOCKPTS.update(lsites)
    (SITE / "tours").mkdir()
    by_path = {f.path: f for f in files}
    for t in tour_list:
        (SITE / t.url).write_text(tourrender.render_tour(t, tour_list, by_path, facts, table,
                                                        linker))
    (SITE / "tours" / "index.html").write_text(tourrender.render_index(tour_list, linker))
    for t in tour_list:
        problems += [f"tour {t.num:02d}-{t.slug}: {p}" for p in t.problems]
    problems += [f"glossary: {p}" for p in gl_problems]
    from . import questions as qmod, testrender
    problems += testrender.write(SITE, files, facts, table, linker, qmod.load(files))
    from . import labs as labmod, labrender
    problems += labrender.write(SITE, files, facts, table, linker, labmod.load(files), tour_list,
                                concept_list)
    (SITE / "assets" / "src.js").write_text(src_js(files))

    included_by: dict[str, list[str]] = defaultdict(list)
    for path, ff in facts.items():
        for fl in ff.flinks:
            if path not in included_by[fl.target] and fl.title.startswith("open") and \
                    not path == "Makefile":
                included_by[fl.target].append(path)

    for f in files:
        out = SITE / page_url(f.path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fn = notes.get(f.path)
        out.write_text(render_file_page(f, facts[f.path], table, files, included_by, fn,
                                        linker, tourrender.tour_lines_json(
                                            tour_index, f.path, tours_by_num)))
        if fn:
            problems += [f"{f.path}: {p}" for p in fn.problems]
    (SITE / "index.html").write_text(render_index(files, table, tour_list))
    from . import aboutrender
    (SITE / "about.html").write_text(aboutrender.render(linker, problems))
    return problems
