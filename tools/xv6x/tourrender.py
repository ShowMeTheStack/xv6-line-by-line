"""HTML for the guided tours: one player page per tour plus the tours index."""

import json
import re
from collections import defaultdict
from html import escape

from .annotations import Linker
from .config import SrcFile
from .render import HEAD, SCRIPTS, TOP, page_url, render_lines
from .tours import MODES, SATP, STACKS, Tour, irq_state, stack_state

GROUP_ORDER = ["Boot and build", "Traps and system calls", "Time and scheduling",
               "Concurrency primitives", "Processes", "Memory", "File system",
               "Devices and putting it all together", "The dance of privilege",
               "Locks and interrupt state"]

# A suggested first path through the tours (by number).
LEARNING_PATH = [1, 2, 3, 4, 5, 11, 15, 16, 12, 20, 21, 22, 24, 25, 29, 31, 34, 35, 39, 40, 41, 45, 50]


def minutes(t: Tour) -> int:
    words = len(re.findall(r"\w+", " ".join(
        [t.summary] + [s.note + " " + s.others for s in t.steps])))
    return max(5, round(words / 180 + len(t.steps) * 0.5))


# Frames that begin a trap handler on top of whatever was running.
TRAP_ENTRIES = {"kernelvec", "kerneltrap"}


def _hart_word(h) -> str:
    if isinstance(h, list):
        return "harts " + ", ".join(str(x) for x in h)
    if h is None or str(h) == "any":
        return "this hart"
    return f"hart {h}"


def _stack_meter(state: dict, prev: dict | None, linker: Linker, root: str, problems) -> str:
    """The highlighted 'running on' strip: which stack sp points into right now."""
    sps = stack_state(state)
    if sps is None:
        return ""
    on = sps["on"]
    proc = str(state.get("proc") or "").strip()
    hart = _hart_word(state.get("hart"))
    if on in ("user", "kernel"):
        who = f" of {escape(proc)}" if proc else ""
    elif on in ("boot", "scheduler"):
        who = f" &middot; {escape(hart)}'s slice of <code>stack0</code>"
    else:
        who = ""
    det = linker.render_inline(sps["detail"], root, problems) if sps["detail"] else ""
    psps = stack_state(prev) if prev else None
    # Only claim a change when the previous step is the same thread on the same hart;
    # otherwise the two steps are different stories and "was:" would be false.
    same_thread = prev is not None and str(prev.get("hart")) == str(state.get("hart")) \
        and str(prev.get("proc") or "") == str(state.get("proc") or "")
    changed = psps is not None and psps["on"] != on and same_thread
    sw = ""
    if sps["switched"]:
        sw = (f'<span class="sw"><span class="swi" aria-hidden="true">&#8644;</span>'
              f'{linker.render_inline(sps["switched"], root, problems)}</span>')
    elif changed:
        sw = (f'<span class="sw"><span class="swi" aria-hidden="true">&#8644;</span>'
              f'was: {escape(STACKS[psps["on"]] if psps["on"] in STACKS else psps["on"])}</span>')
    lane = lambda key, label, sub="": (
        f'<span class="ln ln-{key}">{label}{f"<small>{sub}</small>" if sub else ""}</span>')
    lanes = (lane("user", "user stack") + lane("kernel", "kernel stack")
             + lane("s0", "stack0", "boot &rarr; scheduler"))
    title = ("Which stack the hart's sp register points into at this step. "
             "boot and scheduler are the same memory: the hart's slice of stack0.")
    return (f'<div class="stk on-{escape(on)}{" changed" if changed or sps["switched"] else ""}" '
            f'title="{escape(title)}"><span class="hk">running on</span>'
            f'<span class="lanes" aria-hidden="true">{lanes}</span>'
            f'<span class="stkv"><a class="g" href="{root}concepts/stacks.html#{escape(on)}">'
            f'{escape(STACKS.get(on, on))}</a>{who}'
            f'{f"<span class=det>{det}</span>" if det else ""}</span>{sw}</div>')


def _irq_meter(state: dict, prev: dict | None, linker: Linker, root: str, problems) -> str:
    """The interrupt-state strip: SIE, this hart's push_off depth (noff) and intena."""
    irq = irq_state(state)
    if irq is None:
        return ""
    noff, ie = irq["noff"], irq["intena"]
    i = state.get("intr")
    sie = None if i is None else i in ("on", True)
    pirq = irq_state(prev) if prev else None
    same_thread = prev is not None and str(prev.get("hart")) == str(state.get("hart")) \
        and str(prev.get("proc") or "") == str(state.get("proc") or "")
    changed = same_thread and pirq is not None and pirq["noff"] != noff
    pips = "".join(f'<span class="pip{" f" if k < noff else ""}"></span>'
                   for k in range(max(3, noff)))
    sie_html = ""
    if sie is not None:
        sie_html = (f'<span class="sie {"on" if sie else "off"}" title="sstatus.SIE: may a device '
                    f'or timer interrupt be taken on this hart right now?">'
                    f'<i aria-hidden="true"></i>SIE {"on" if sie else "off"}</span>')
    if noff == 0:
        iev = '<span class="ie na" title="intena only matters while noff &gt; 0">intena &mdash;</span>'
    else:
        what = ("the last pop_off turns interrupts back on" if ie == 1
                else "interrupts stay off after the last pop_off")
        iev = (f'<span class="ie v{ie}" title="{escape(what)}">intena {ie}'
               f'<small>{escape(what)}</small></span>')
    note = linker.render_inline(irq["note"], root, problems) if irq["note"] else ""
    was = f'<span class="was">was noff {pirq["noff"]}</span>' if changed else ""
    title = ("This hart's interrupt state. noff counts nested push_off calls (every held "
             "spinlock is one); intena remembers whether interrupts were on before the "
             "outermost push_off.")
    return (f'<div class="irq{" changed" if changed else ""}" title="{escape(title)}">'
            f'<span class="hk"><a href="{root}concepts/locks.html#noff">interrupts</a></span>'
            f'{sie_html}<span class="noff" title="mycpu()-&gt;noff"><b>noff {noff}</b>'
            f'<span class="pips" aria-hidden="true">{pips}</span></span>{iev}{was}'
            f'{f"<span class=det>{note}</span>" if note else ""}</div>')


def _hud(state: dict, linker: Linker, root: str, group: str | None, problems,
         prev: dict | None = None) -> str:
    def pill(cls, label, value, title=""):
        t = f' title="{escape(title)}"' if title else ""
        return (f'<span class="hp {cls}"{t}><span class="hk">{escape(label)}</span>'
                f'<span class="hv">{value}</span></span>')

    parts = []
    h = state.get("hart")
    if h is not None:
        if isinstance(h, list):
            hv = "harts " + ", ".join(str(x) for x in h)
        elif str(h) == "any":
            hv = "any hart"
        else:
            hv = f"hart {h}"
        parts.append(pill("h-hart", "on", escape(hv), "Which CPU core is executing this step"))
    m = state.get("mode")
    if m:
        parts.append(pill(f"h-mode m-{m}", "mode", escape(m), MODES[m]))
    i = state.get("intr")
    if i is not None:
        on = i in ("on", True)
        parts.append(pill("h-intr " + ("on" if on else "off"), "interrupts",
                          "on" if on else "off",
                          "Whether this hart can be interrupted right now"))
    sp = state.get("satp")
    if sp:
        parts.append(pill("h-satp", "page table", escape(SATP[sp]),
                          "Which address translation is active (satp)"))
    pr = state.get("proc")
    if pr:
        parts.append(pill("h-proc", "process", escape(str(pr))))
    locks = state.get("locks")
    if locks is not None:
        if locks:
            chips = "".join(f'<code class="lk">{escape(str(x))}</code>' for x in locks)
        else:
            chips = '<span class="nolk">none</span>'
        parts.append(f'<span class="hp h-locks"><span class="hk">locks held</span>'
                     f'<span class="hv">{chips}</span></span>')
    hud = _stack_meter(state, prev, linker, root, problems)
    hud += _irq_meter(state, prev, linker, root, problems)
    hud += f'<div class="hud" aria-label="Machine state">{"".join(parts)}</div>' if parts else ""
    stack = state.get("stack") or []
    if stack:
        frames = []
        for idx, name in enumerate(stack):
            if idx and str(name) in TRAP_ENTRIES and str(stack[idx - 1]) not in TRAP_ENTRIES:
                frames.append('<span class="trapb" title="A trap pushed a new frame here: '
                              'everything to the right runs on the same stack, on top of '
                              'the interrupted code">trap</span>')
            cands = linker.symbol(str(name), group)
            if cands:
                s = cands[0]
                frames.append(f'<a class="sy ref" data-s="{s.id}" href="{root}'
                              f'{page_url(s.defloc[0])}#L{s.defloc[1]}">{escape(str(name))}</a>')
            else:
                frames.append(f"<span>{escape(str(name))}</span>")
        hud += ('<div class="stack" aria-label="Call stack"><span class="hk">call stack</span>'
                + '<span class="sep">›</span>'.join(frames) + "</div>")
    return hud


def render_tour(t: Tour, tours: list[Tour], files: dict[str, SrcFile], facts, table,
                linker: Linker) -> str:
    root = "../"
    by_num = {x.num: x for x in tours}
    md = lambda text, group=None: linker.render(text, root, "", group, t.problems)

    nsteps = len(t.steps)
    segs = "".join(
        f'<button class="seg" data-go="{i}" title="{escape(label)}" aria-label="{escape(label)}">'
        f'</button>'
        for i, label in enumerate(["Introduction"] + [f"{k}. {s.title}" for k, s in
                                                      enumerate(t.steps, 1)] + ["Wrap-up"]))

    # ---- intro
    prereq = ""
    known = [q for q in t.prerequisites if q in by_num]
    if known:
        prereq = ('<p class="prereq"><b>Best after:</b> ' + ", ".join(
            f'<a href="{root}{by_num[q].url}">{q}. {escape(by_num[q].title)}</a>'
            for q in known) + "</p>")
    outline = "".join(
        f'<li><a href="#step-{k}" data-go="{k}"><span class="on">{k}</span>'
        f'{escape(s.title)}</a> <span class="ofile">{escape(s.file)}</span></li>'
        for k, s in enumerate(t.steps, 1))
    cast = f'<div class="cast"><h3>Who is running where</h3>{md(t.cast)}</div>' if t.cast else ""
    intro = (f'<section class="tstep intro" data-i="0" id="ts-0">'
             f'<div class="intro-inner"><p class="tkicker">Tour {t.num} · {escape(t.group)} · '
             f'about {minutes(t)} minutes · {nsteps} steps</p>'
             f'<h1>{escape(t.title)}</h1><div class="tsum">{md(t.summary)}</div>{prereq}{cast}'
             f'<div class="multihart"><b>Three harts are running.</b> This tour follows one '
             f'path through the code, but the machine has three CPUs executing at the same '
             f'time. Watch the <span class="hp-demo">locks held</span> display at the top of '
             f'each step, and read the <b>Meanwhile, on other harts</b> boxes: they show what '
             f'the other CPUs could be doing at that very moment.</div>'
             f'<button class="btn big" data-go="1">Start the tour →</button>'
             f'<details class="outline" open><summary>The route</summary><ol>{outline}</ol>'
             f'</details></div></section>')

    # ---- steps
    secs = []
    for k, s in enumerate(t.steps, 1):
        f = files[s.file]
        group = f.group
        code = render_lines(f, facts[s.file], table, root, only=(s.a, s.b), focus=(s.fa, s.fb))
        others = (f'<aside class="others"><h3><span class="dots"><i></i><i></i><i></i></span>'
                  f'Meanwhile, on other harts</h3>{md(s.others, group)}</aside>'
                  if s.others else "")
        rng = f"{s.fa}" if s.fa == s.fb else f"{s.fa}–{s.fb}"
        fig = ""
        if s.figure:
            from .concepts import figure_html
            fig = figure_html(s.figure, linker.render_inline(s.caption, root, t.problems)
                              if s.caption else "", t.problems)
        secs.append(
            f'<section class="tstep" data-i="{k}" id="ts-{k}" hidden>'
            f'{_hud(s.state, linker, root, group, t.problems, t.steps[k - 2].state if k > 1 else None)}'
            f'<div class="tgrid"><div class="tcode">'
            f'<div class="tfile"><a href="{root}{page_url(s.file)}#L{s.fa}">'
            f'{escape(s.file)}</a><span>lines {rng}</span></div>'
            f'<div class="code excerpt lang-{f.lang}">{code}</div></div>'
            f'<div class="tnote"><p class="tstepno">Step {k} of {nsteps}</p>'
            f'<h2>{escape(s.title)}</h2>{fig}{md(s.note, group)}{others}</div></div></section>')

    # ---- wrap-up
    rows = "".join(
        f'<tr><td><code>{escape(str(l.get("lock", "")))}</code></td>'
        f'<td>{linker.render_inline(str(l.get("where", "")), root, t.problems)}</td>'
        f'<td>{linker.render_inline(str(l.get("protects", "")), root, t.problems)}</td></tr>'
        for l in t.locks)
    locks = (f'<h2>Locks on this path</h2><table class="locktab"><thead><tr><th>Lock</th>'
             f'<th>Taken in</th><th>Protects</th></tr></thead><tbody>{rows}</tbody></table>'
             if rows else "")
    quiz = "".join(
        f'<details class="q"><summary><span class="qn">{i}</span>{md(q.get("q", ""))}'
        f'</summary><div class="qa">{md(q.get("a", ""))}</div></details>'
        for i, q in enumerate(t.quiz, 1))
    quiz = f'<h2>Check your understanding</h2><div class="quiz">{quiz}</div>' if quiz else ""
    nxt = by_num.get(t.num + 1)
    nxt_html = (f'<a class="btn big" href="{root}{nxt.url}">Next tour: {nxt.num}. '
                f'{escape(nxt.title)} →</a>' if nxt else "")
    outro = (f'<section class="tstep outro" data-i="{nsteps + 1}" id="ts-{nsteps + 1}" hidden>'
             f'<div class="intro-inner"><p class="tkicker">Tour {t.num} · wrap-up</p>'
             f'<h1>{escape(t.title)}: what you saw</h1>{locks}{quiz}'
             f'<div class="outro-nav"><a class="btn" href="{root}tours/index.html">All tours</a>'
             f'{nxt_html}</div></div></section>')

    body = (f'<div class="tour" data-tour="{t.num}" data-steps="{nsteps}">'
            f'<div class="tour-top"><a class="tback" href="{root}tours/index.html">Tours</a>'
            f'<span class="ttitle"><b>{t.num}</b> {escape(t.title)}</span>'
            f'<div class="segs" role="tablist" aria-label="Steps">{segs}</div>'
            f'<div class="tnav"><button class="icon-btn" data-step="-1" aria-label="Previous step">←</button>'
            f'<span class="count"></span>'
            f'<button class="icon-btn" data-step="1" aria-label="Next step">→</button></div></div>'
            f'<div class="tstage">{intro}{"".join(secs)}{outro}</div>'
            f'<p class="keys">Keys: <kbd>←</kbd> <kbd>→</kbd> step · <kbd>Home</kbd> start</p></div>')
    return (HEAD.format(title=f"Tour {t.num}: {escape(t.title)} · xv6, line by line", root=root)
            + f'<body class="tour-page" data-root="{root}" data-file="">\n'
            + TOP.format(root=root, crumb=f"tour {t.num}") + body
            + SCRIPTS.format(root=root)
            + f'<script src="{root}assets/tour.js" defer></script>\n</body>\n</html>\n')


def render_index(tours: list[Tour], linker: Linker) -> str:
    root = "../"
    by_num = {t.num: t for t in tours}
    groups: dict[str, list[Tour]] = defaultdict(list)
    for t in tours:
        groups[t.group].append(t)
    order = [g for g in GROUP_ORDER if g in groups] + sorted(g for g in groups
                                                           if g not in GROUP_ORDER)
    probs: list[str] = []

    def card(t: Tour) -> str:
        first = re.sub(r"<[^>]+>", "", linker.render(t.summary.split("\n\n")[0], root, "",
                                                      None, probs)).strip()
        if len(first) > 220:
            first = first[:217].rsplit(" ", 1)[0] + "…"
        return (f'<a class="tcard" href="{root}{t.url}" data-tour="{t.num}">'
                f'<span class="tnum">{t.num}</span><span class="tbody"><b>{escape(t.title)}</b>'
                f'<span class="tdesc">{escape(first)}</span><span class="tmeta">{len(t.steps)} '
                f'steps · ~{minutes(t)} min</span></span><span class="tdone" title="Completed">'
                f'✓</span></a>')

    path = "".join(f'<a class="pstop" href="{root}{by_num[n].url}" data-tour="{n}">'
                   f'<span>{n}</span>{escape(by_num[n].title)}</a>'
                   for n in LEARNING_PATH if n in by_num)
    sections = "".join(f'<h2>{escape(g)}</h2><div class="tcards">'
                       + "".join(card(t) for t in groups[g]) + "</div>" for g in order)
    return (HEAD.format(title="Guided tours · xv6, line by line", root=root)
            + f'<body class="tours-index" data-root="{root}" data-file="">\n'
            + TOP.format(root=root, crumb="tours")
            + '<main class="tours-main">'
            + '<h1>Guided tours</h1><p class="lede">Each tour follows one path through the '
            'running system, from the first instruction to the hardware and back, across C, '
            'assembly and the linker script. At every step you see the real code, the state '
            'of the machine (which hart, which mode, which stack, which page table, which locks are held, and whether interrupts can arrive) and what the '
            'other CPUs might be doing at that moment.</p>'
            + (f'<h2>Start here: a learning path</h2><div class="lpath">{path}</div>'
               if path else "")
            + sections + "</main>" + SCRIPTS.format(root=root)
            + f'<script src="{root}assets/tour.js" defer></script>\n</body>\n</html>\n')


def tour_lines_json(index: dict, path: str, by_num: dict[int, Tour]) -> str:
    """Per-file map line -> [[tour, step, step title, tour url]] for the notes panel."""
    m = index.get(path)
    if not m:
        return ""
    data = {str(n): [[t, k, title, by_num[t].url] for (t, k, title) in v] for n, v in m.items()}
    return ('<script type="application/json" id="tourlines">'
            + json.dumps(data, separators=(",", ":")).replace("</", "<\\/") + "</script>")
