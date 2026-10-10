# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Jyotiprakash Mishra. Based on "xv6, line by line" by Jyotiprakash Mishra
# (https://xv6.jyotiprakash.org); see NOTICE for the attribution term (GPLv3 section 7(b)).
"""Pages for the extension labs: index, one page per lab, and the reveal tour."""

import re
from html import escape

from .annotations import Linker
from .labs import AREAS, BASE, LABS_REPO, PLAN, Lab, branch_name, diff_of, file_at
from .questions import render_question
from .render import HEAD, SCRIPTS, TOP, page_url
from .testrender import _Ctx
from .tourrender import _hud

C_KW = set("""if else while for do return break continue switch case default goto sizeof
static extern const volatile inline typedef struct union enum asm""".split())
C_KT = set("""void char short int long unsigned signed uint uint64 uint32 uint16 uint8 uchar ushort
pagetable_t pte_t""".split())
TOKEN = re.compile(r'(?P<cm>//.*$|/\*.*?(\*/|$))|(?P<st>"(\\.|[^"\\])*"|\'(\\.|[^\'\\])*\')'
                   r'|(?P<nu>\b(0x[0-9a-fA-F]+|\d+)[uUlL]*\b)|(?P<id>[A-Za-z_]\w*)')


class Highlighter:
    """Small C/asm highlighter for branch files; identifiers that exist in the base tree
    link to their annotated definition."""

    def __init__(self, linker: Linker, root: str):
        self.linker, self.root = linker, root

    def line(self, text: str, path: str, state: dict) -> str:
        asm = path.endswith(".S")
        out, i = [], 0
        if state.get("in_cm"):
            end = text.find("*/")
            if end < 0:
                return f'<span class="cm">{escape(text)}</span>'
            out.append(f'<span class="cm">{escape(text[:end + 2])}</span>')
            i = end + 2
            state["in_cm"] = False
        s = text[i:]
        stripped = s.lstrip()
        if stripped.startswith("#") and (not asm or re.match(r"#\s*(include|define|if|endif|else|elif|ifdef|ifndef|undef)\b", stripped)):
            return "".join(out) + f'<span class="pp">{escape(s)}</span>'
        if asm and "#" in s:
            k = s.index("#")
            return "".join(out) + self._code(s[:k], asm) + f'<span class="cm">{escape(s[k:])}</span>'
        return "".join(out) + self._code(s, asm, state)

    def _code(self, s: str, asm: bool, state: dict | None = None) -> str:
        out, pos = [], 0
        for m in TOKEN.finditer(s):
            out.append(escape(s[pos:m.start()]))
            tok = m.group(0)
            if m.group("cm"):
                if tok.startswith("/*") and not tok.endswith("*/") and state is not None:
                    state["in_cm"] = True
                out.append(f'<span class="cm">{escape(tok)}</span>')
            elif m.group("st"):
                out.append(f'<span class="st">{escape(tok)}</span>')
            elif m.group("nu"):
                out.append(f'<span class="nu">{escape(tok)}</span>')
            elif not asm and tok in C_KW:
                out.append(f'<span class="kw">{tok}</span>')
            elif not asm and tok in C_KT:
                out.append(f'<span class="kt">{tok}</span>')
            else:
                cands = self.linker.symbol(tok, None) if len(tok) > 2 else None
                if cands:
                    sy = cands[0]
                    out.append(f'<a class="sy" href="{self.root}{page_url(sy.defloc[0])}#L{sy.defloc[1]}" '
                               f'title="{escape(tok)} in the unmodified xv6">{escape(tok)}</a>')
                else:
                    out.append(escape(tok))
            pos = m.end()
        out.append(escape(s[pos:]))
        return "".join(out)

    def excerpt(self, text: str, path: str, a: int, b: int, fa: int, fb: int) -> str:
        lines = text.splitlines()
        st: dict = {}
        out = []
        for n, t in enumerate(lines, 1):
            h = self.line(t, path, st)
            if a <= n <= b:
                fx = " fx" if fa <= n <= fb else " cx"
                out.append(f'<div class="l{fx}"><span class="n2">{n}</span>'
                           f'<span class="t">{h or " "}</span></div>')
        return "\n".join(out)

    def diff(self, diff: str, path: str) -> str:
        out, old, new = [], 0, 0
        st: dict = {}
        for raw in diff.splitlines():
            if raw.startswith(("diff --git", "index ", "--- ", "+++ ", "new file", "deleted file")):
                continue
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", raw)
            if m:
                old, new = int(m.group(1)), int(m.group(2))
                out.append(f'<div class="dl hunk"><span class="dn"></span><span class="dn"></span>'
                           f'<span class="t">{escape(raw)}</span></div>')
                continue
            tag, body = raw[:1], raw[1:]
            h = self.line(body, path, st) or " "
            if tag == "+":
                out.append(f'<div class="dl add"><span class="dn"></span><span class="dn">{new}</span>'
                           f'<span class="t">{h}</span></div>')
                new += 1
            elif tag == "-":
                out.append(f'<div class="dl del"><span class="dn">{old}</span><span class="dn"></span>'
                           f'<span class="t">{h}</span></div>')
                old += 1
            else:
                out.append(f'<div class="dl"><span class="dn">{old}</span><span class="dn">{new}</span>'
                           f'<span class="t">{h}</span></div>')
                old += 1
                new += 1
        return f'<div class="code diff">{"".join(out)}</div>'


def _stars(n: int) -> str:
    return f'<span class="stars" title="difficulty {n} of 5">{"★" * n}{"☆" * (5 - n)}</span>'


def _page(title, crumb, body, root="../", scripts=("labs.js",)):
    return (HEAD.format(title=f"{escape(title)} · xv6, line by line", root=root)
            + f'<body class="test-page lab-page" data-root="{root}" data-file="">\n'
            + TOP.format(root=root, crumb=crumb) + body + SCRIPTS.format(root=root)
            + "".join(f'<script src="{root}assets/{s}" defer></script>\n' for s in scripts)
            + "</body>\n</html>\n")


def render_lab(lab: Lab, ctx: _Ctx, hl: Highlighter, tours, concepts) -> str:
    md, inline = ctx.md, ctx.inline
    r = lab.raw
    num = lab.num
    br = r.get("branch") or branch_name(num)
    pre = r.get("prerequisites") or {}
    tour_links = ", ".join(f"[[tour:{t}]]" for t in pre.get("tours") or [])
    con_links = ", ".join(f"[[concept:{c}]]" for c in pre.get("concepts") or [])
    prereq = ""
    if tour_links or con_links:
        prereq = ('<p class="prereq"><b>Read first:</b> '
                  + inline(" · ".join(x for x in (tour_links, con_links) if x)) + "</p>")
    learn = "".join(f"<li>{inline(x)}</li>" for x in r.get("learn") or [])
    phases = [("spec", "1. The spec"), ("think", "2. Think first"), ("build", "3. Build it"),
              ("clinic", "4. Debugging clinic"), ("reveal", "5. The reference solution"),
              ("verify", "6. Verify and measure"), ("further", "7. Go further")]
    nav = '<nav class="labnav">' + "".join(f'<a href="#{k}">{escape(t)}</a>' for k, t in phases) + "</nav>"
    head = (f'<header class="labhead"><p class="tkicker"><a href="index.html">Extension labs</a> · '
            f'lab {num} · {escape(r.get("area", ""))} · {_stars(int(r.get("stars", 1)))}</p>'
            f'<h1>{escape(r.get("title", ""))}</h1><div class="lede">{md(r.get("summary", ""))}</div>'
            f'{prereq}<div class="labmeta"><div><h3>What this lab teaches</h3><ul>{learn}</ul></div>'
            f'<div><h3>The reference branch</h3><p><a href="{LABS_REPO}/commits/{escape(br)}">'
            f'<code>{escape(br)}</code></a> in <a href="{LABS_REPO}">{LABS_REPO.split("github.com/")[1]}</a>, '
            f'branched from the frozen commit <code>{BASE}</code>; {len(lab.commits)} commits.</p>'
            f'<pre class="cmd">git clone {LABS_REPO}\n'
            f'cd xv6-riscv-labs\n'
            f'git checkout -b my-{escape(PLAN[num][0])} {BASE}   # start your own\n'
            f'git diff {BASE} origin/{escape(br)}   # only when you want the answer</pre></div></div>'
            f'</header>{nav}')

    think = []
    for i, t in enumerate(r.get("think") or [], 1):
        hints = "".join(f'<div class="hint" data-h="{j}" hidden><b>Hint {j}.</b> {md(h)}</div>'
                        for j, h in enumerate(t.get("hints") or [], 1))
        checks = "".join(render_question(_Q(q), k, ctx) for k, q in
                         enumerate(t.get("checks") or [], 1))
        think.append(f'<article class="think" data-t="{i}"><h3><span class="qn">{i}</span>'
                     f'{escape(t.get("title", ""))}</h3><div class="qq">{md(t.get("q", ""))}</div>'
                     f'{hints}<div class="qbtns"><button type="button" class="btn nexthint">Show hint 1</button>'
                     f'<button type="button" class="btn showans">Show the reference answer</button></div>'
                     f'<div class="ans" hidden><h4>The reference design</h4>{md(t.get("answer", ""))}</div>'
                     + (f'<div class="checks"><h4>Check yourself</h4><div class="qlist">{checks}</div></div>'
                        if checks else "") + "</article>")

    clinic = []
    for i, c in enumerate(r.get("clinic") or [], 1):
        clinic.append(f'<article class="bug" data-c="{i}"><h3><span class="qn">{i}</span>'
                      f'{inline(c.get("bug", ""))}</h3><div class="bugchange">{md(c.get("change", ""))}</div>'
                      f'<h4>What happened when we ran it</h4><pre class="symptom">'
                      f'{escape(str(c.get("symptom", "")).rstrip())}</pre>'
                      f'<p class="qbtns"><button type="button" class="btn showwhy">Can you explain it? '
                      f'Then show why</button></p><div class="why" hidden>{md(c.get("why", ""))}</div></article>')

    commits = "".join(
        f'<li><details><summary><a class="sha" href="{LABS_REPO}/commit/{sha}">{sha[:7]}</a> {escape(subj)}</summary>'
        + "".join(f'<p class="dfile">{escape(path)}</p>{hl.diff(diff_of(sha, path), path)}'
                  for path in _changed(sha)) + "</details></li>"
        for sha, subj in lab.commits)
    reveal = (f'<p>Take the guided tour through the reference solution, one commit at a time, '
              f'with the machine state at every step:</p><p><a class="btn big" '
              f'href="{num:02d}-{lab.slug}-reveal.html">Open the reveal tour →</a></p>'
              f'<h3>Or read the commits</h3><ol class="commits">{commits}</ol>')

    sec = lambda k, title, html: (f'<section class="labsec" id="{k}"><h2>{escape(title)}</h2>'
                                  f'{html}</section>')
    body = (head
            + sec("spec", "1. The spec", md(r.get("spec", "")))
            + sec("think", "2. Think first", '<p class="lede">Answer each question in your '
                  'head (or on paper) before opening a hint. Hints get more specific; the '
                  'reference answer comes last.</p>' + "".join(think))
            + sec("build", "3. Build it", md(r.get("build", "")))
            + sec("clinic", "4. Debugging clinic", '<p class="lede">Each bug below was built into '
                  'the reference solution and run on three harts; the symptom shown is exactly '
                  'what happened. Try to explain it before revealing why.</p>' + "".join(clinic))
            + sec("reveal", "5. The reference solution", reveal)
            + sec("verify", "6. Verify and measure", md(r.get("verify", "")) + md(r.get("measure", "")))
            + sec("further", "7. Go further", md(r.get("further", ""))))
    return _page(r.get("title", ""), f"lab {num}",
                 f'<main class="test-main lab" data-lab="{num}">{body}</main>',
                 scripts=("labs.js", "quiz.js"))


class _Q:
    def __init__(self, raw):
        self.raw, self.id, self.type, self.level = raw, raw.get("id", ""), raw.get("type"), raw.get("level", 2)


def _changed(sha: str) -> list[str]:
    from .labs import git
    return [p for p in git("show", "--format=", "--name-only", sha).splitlines() if p.strip()]


def render_reveal(lab: Lab, ctx: _Ctx, hl: Highlighter) -> str:
    r = lab.raw
    root = "../"
    md = ctx.md
    steps = r.get("reveal") or []
    n = len(steps)
    segs = "".join(f'<button class="seg" data-go="{i}" aria-label="{escape(t)}"></button>'
                   for i, t in enumerate(["Introduction"] + [f"{k}. {s.get('title', '')}"
                                                              for k, s in enumerate(steps, 1)] + ["Wrap-up"]))
    outline = "".join(f'<li><a href="#step-{k}" data-go="{k}"><span class="on">{k}</span>'
                      f'{escape(s.get("title", ""))}</a> <span class="ofile">{escape(s.get("file", ""))}'
                      f'</span></li>' for k, s in enumerate(steps, 1))
    intro = (f'<section class="tstep intro" data-i="0" id="ts-0"><div class="intro-inner">'
             f'<p class="tkicker"><a href="{lab.num:02d}-{lab.slug}.html">Lab {lab.num}</a> · reveal · '
             f'{n} steps · {len(lab.commits)} commits</p><h1>{escape(r.get("title", ""))}: the '
             f'reference solution</h1><div class="tsum">{md(r.get("summary", ""))}</div>'
             f'<p>Each step shows one change on the branch <code>{escape(r.get("branch") or branch_name(lab.num))}'
             f'</code>, the code around it, and the state of the machine when that code runs.</p>'
             f'<button class="btn big" data-go="1">Start →</button>'
             f'<details class="outline" open><summary>The route</summary><ol>{outline}</ol>'
             f'</details></div></section>')
    secs = []
    prev = None
    for k, s in enumerate(steps, 1):
        ci = s["commit"]
        sha, subj = lab.commits[ci - 1]
        text = file_at(sha, s["file"]) or ""
        a, _, b = str(s["lines"]).partition("-")
        a, b = int(a), int(b or a)
        fa, fb = (a, b)
        if s.get("focus"):
            x, _, y = str(s["focus"]).partition("-")
            fa, fb = int(x), int(y or x)
        code = hl.excerpt(text, s["file"], a, b, fa, fb)
        dif = ""
        if s.get("diff"):
            dif = (f'<details class="tdiff" open><summary>What commit {ci} changed in '
                   f'<code>{escape(s["file"])}</code></summary>{hl.diff(diff_of(sha, s["file"]), s["file"])}'
                   f'</details>')
        others = (f'<aside class="others"><h3><span class="dots"><i></i><i></i><i></i></span>'
                  f'Meanwhile, on other harts</h3>{md(s.get("others", ""))}</aside>' if s.get("others") else "")
        st = s.get("state") or {}
        secs.append(f'<section class="tstep" data-i="{k}" id="ts-{k}" hidden>'
                    f'{_hud(st, ctx.linker, root, None, ctx.problems, prev)}'
                    f'<div class="tgrid"><div class="tcode"><div class="tfile"><span>{escape(s["file"])} '
                    f'at commit {ci} <a class="sha" href="{LABS_REPO}/commit/{sha}">{sha[:7]}</a></span><span>lines {fa}–{fb}</span></div>'
                    f'<div class="code excerpt">{code}</div>{dif}</div>'
                    f'<div class="tnote"><p class="tstepno">Step {k} of {n} · commit {ci}: {escape(subj)}</p>'
                    f'<h2>{escape(s.get("title", ""))}</h2>{md(s.get("note", ""))}{others}</div></div></section>')
        prev = st
    outro = (f'<section class="tstep outro" data-i="{n + 1}" id="ts-{n + 1}" hidden><div class="intro-inner">'
             f'<p class="tkicker">Lab {lab.num} · wrap-up</p><h1>What you saw</h1>'
             f'{md(r.get("verify", ""))}<div class="outro-nav"><a class="btn" href="{lab.num:02d}-{lab.slug}.html#verify">'
             f'Back to the lab</a></div></div></section>')
    body = (f'<div class="tour" data-tour="lab-{lab.num}" data-steps="{n}">'
            f'<div class="tour-top"><a class="tback" href="{lab.num:02d}-{lab.slug}.html">Lab {lab.num}</a>'
            f'<span class="ttitle"><b>{lab.num}</b> {escape(r.get("title", ""))}</span>'
            f'<div class="segs" role="tablist" aria-label="Steps">{segs}</div>'
            f'<div class="tnav"><button class="icon-btn" data-step="-1" aria-label="Previous step">←</button>'
            f'<span class="count"></span><button class="icon-btn" data-step="1" aria-label="Next step">→</button>'
            f'</div></div><div class="tstage">{intro}{"".join(secs)}{outro}</div>'
            f'<p class="keys">Keys: <kbd>←</kbd> <kbd>→</kbd> step · <kbd>Home</kbd> start</p></div>')
    return (HEAD.format(title=f"Lab {lab.num} reveal: {escape(r.get('title', ''))} · xv6, line by line", root=root)
            + f'<body class="tour-page" data-root="{root}" data-file="">\n'
            + TOP.format(root=root, crumb=f"lab {lab.num}") + body + SCRIPTS.format(root=root)
            + f'<script src="{root}assets/tour.js" defer></script>\n</body>\n</html>\n')


def render_index(labs: list[Lab], ctx: _Ctx) -> str:
    built = {l.num: l for l in labs}
    groups = []
    for area in AREAS:
        cards = []
        for num, (slug, title, ar, stars) in PLAN.items():
            if ar != area:
                continue
            lab = built.get(num)
            if lab:
                cards.append(f'<a class="tcard labcard" href="{num:02d}-{slug}.html"><span class="tnum">{num}</span>'
                             f'<span class="tbody"><b>{escape(lab.get("title", title))}</b><span class="tdesc">'
                             f'{escape(re.sub("<[^>]+>", "", ctx.md(lab.get("summary", "")))[:200])}</span>'
                             f'<span class="tmeta">{_stars(stars)} · {len(lab.get("reveal") or [])} reveal steps</span>'
                             f'</span></a>')
            else:
                cards.append(f'<div class="tcard labcard planned"><span class="tnum">{num}</span>'
                             f'<span class="tbody"><b>{escape(title)}</b><span class="tmeta">{_stars(stars)} · '
                             f'in preparation</span></span></div>')
        groups.append(f'<h2>{escape(area)}</h2><div class="tcards">{"".join(cards)}</div>')
    body = ('<main class="test-main"><h1>Extension labs</h1><p class="lede">Twenty-five extensions '
            'to xv6, each a git branch from the frozen commit. Every lab runs the same way: read the '
            'spec, think through the design with hints that get more specific, build it yourself, '
            'study real bugs and the symptoms they caused, then walk through the reference solution '
            'one commit at a time, with the machine state at every step. Every reference branch '
            'passes xv6\'s full usertests on three harts.</p>' + "".join(groups) + "</main>")
    return _page("Extension labs", "labs", body)


def write(site, files, facts, table, linker: Linker, labs: list[Lab], tours, concepts) -> list[str]:
    problems: list[str] = []
    by_path = {f.path: f for f in files}
    ctx = _Ctx(linker, by_path, facts, table, "../", problems)
    hl = Highlighter(linker, "../")
    out = site / "labs"
    out.mkdir(exist_ok=True)
    # Only labs that have been written, independently reviewed and corrected carry
    # `published: true`; the rest show as "in preparation" on the index.
    live = [l for l in labs if l.commits and l.get("published")]
    for lab in live:
        (site / lab.url).write_text(render_lab(lab, ctx, hl, tours, concepts))
        (site / lab.reveal_url).write_text(render_reveal(lab, ctx, hl))
        problems += [f"lab {lab.num:02d}-{lab.slug}: {p}" for p in lab.problems]
    (out / "index.html").write_text(render_index(live, ctx))
    return problems
