# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Jyotiprakash Mishra. Based on "xv6, line by line" by Jyotiprakash Mishra
# (https://xv6.jyotiprakash.org); see NOTICE for the attribution term (GPLv3 section 7(b)).
"""Test Yourself pages: index, one page per category, and the quick-10 page."""

from html import escape

from .annotations import Linker
from .questions import Category, render_question
from .render import HEAD, SCRIPTS, TOP, render_lines


class _Ctx:
    def __init__(self, linker: Linker, files, facts, table, root: str, problems: list[str]):
        self.linker, self.files, self.facts, self.table = linker, files, facts, table
        self.root, self.problems = root, problems

    def md(self, text) -> str:
        return self.linker.render(str(text or ""), self.root, "", None, self.problems)

    def inline(self, text) -> str:
        return self.linker.render_inline(str(text or ""), self.root, self.problems)

    def excerpt(self, path, a, b, fa, fb) -> str:
        f = self.files[path]
        return render_lines(f, self.facts[path], self.table, self.root, only=(a, b),
                            focus=(fa, fb))


def _page(title: str, crumb: str, body: str, root: str = "../") -> str:
    return (HEAD.format(title=f"{escape(title)} · xv6, line by line", root=root)
            + f'<body class="test-page" data-root="{root}" data-file="">\n'
            + TOP.format(root=root, crumb=crumb)
            + f'<main class="test-main">{body}</main>' + SCRIPTS.format(root=root)
            + f'<script src="{root}assets/quiz.js" defer></script>\n</body>\n</html>\n')


INTRO = ('<p class="lede">Twenty-five questions in each of twenty areas, all checked by your '
         'browser. When an answer is wrong you are told the most likely line of thinking that '
         'led to it, then the right way to think about it, with links to the code, the tours '
         'and the concept pages. Your progress is kept in this browser only.</p>')


def render_category(c: Category, cats: list[Category], ctx: _Ctx) -> str:
    qs = "".join(render_question(q, k, ctx) for k, q in enumerate(c.questions, 1))
    i = [x.num for x in cats].index(c.num)
    prev = cats[i - 1] if i > 0 else None
    nxt = cats[i + 1] if i + 1 < len(cats) else None
    nav = ('<nav class="qnav">'
           + (f'<a href="{prev.num:02d}-{prev.slug}.html">← {escape(prev.title)}</a>' if prev else "<span></span>")
           + '<a href="index.html">All categories</a>'
           + (f'<a href="{nxt.num:02d}-{nxt.slug}.html">{escape(nxt.title)} →</a>' if nxt else "<span></span>")
           + "</nav>")
    head = (f'<p class="tkicker"><a href="index.html">Test yourself</a> · category {c.num} of '
            f'{len(cats)}</p><h1>{escape(c.title)}</h1>'
            f'<p class="lede">{ctx.inline(c.summary)}</p>'
            f'<div class="qbar" data-cat="{c.num}"><span class="qscore"></span>'
            f'<span class="qfilter"><button type="button" class="btn" data-f="all">All</button>'
            f'<button type="button" class="btn" data-f="todo">Not yet answered</button>'
            f'<button type="button" class="btn" data-f="wrong">Got wrong</button>'
            f'<button type="button" class="btn qreset">Reset this category</button></span></div>')
    return _page(c.title, "test yourself", head + f'<div class="qlist">{qs}</div>' + nav)


def render_index(cats: list[Category], ctx: _Ctx) -> str:
    cards = "".join(
        f'<a class="tcard qcard" href="{c.num:02d}-{c.slug}.html" data-ids="'
        f'{escape(" ".join(q.id for q in c.questions))}"><span class="tnum">{c.num}</span>'
        f'<span class="tbody"><b>{escape(c.title)}</b><span class="tdesc">'
        f'{escape(c.summary)}</span><span class="tmeta">{len(c.questions)} questions · '
        f'<span class="qprog">not started</span></span></span></a>' for c in cats)
    total = sum(len(c.questions) for c in cats)
    body = (f'<h1>Test yourself</h1>{INTRO}'
            f'<div class="qbar"><span class="qscore qtotal" data-total="{total}"></span>'
            f'<span class="qfilter"><a class="btn big" href="quick.html">Quick 10 →</a>'
            f'<button type="button" class="btn qresetall">Reset all progress</button></span></div>'
            f'<div class="tcards">{cards}</div>')
    return _page("Test yourself", "test yourself", body)


def render_quick(cats: list[Category], ctx: _Ctx) -> str:
    """Every question, hidden; quiz.js shows ten (unanswered and wrong ones first)."""
    parts = []
    for c in cats:
        for k, q in enumerate(c.questions, 1):
            parts.append(f'<div class="qwrap" data-cat="{escape(c.title)}" '
                         f'data-href="{c.num:02d}-{c.slug}.html#{escape(q.id)}" hidden>'
                         + render_question(q, k, ctx) + "</div>")
    body = ('<p class="tkicker"><a href="index.html">Test yourself</a></p><h1>Quick 10</h1>'
            '<p class="lede">Ten questions from all twenty categories, favouring ones you have '
            'not answered yet or got wrong.</p>'
            '<div class="qbar"><span class="qscore"></span><span class="qfilter">'
            '<button type="button" class="btn qnew">New set of 10</button></span></div>'
            f'<div class="qlist quick">{"".join(parts)}</div>')
    return _page("Quick 10", "test yourself", body)


def write(site, files, facts, table, linker: Linker, cats: list[Category]) -> list[str]:
    problems: list[str] = []
    by_path = {f.path: f for f in files}
    ctx = _Ctx(linker, by_path, facts, table, "../", problems)
    out = site / "test"
    out.mkdir(exist_ok=True)
    for c in cats:
        (site / c.url).write_text(render_category(c, cats, ctx))
    (out / "index.html").write_text(render_index(cats, ctx))
    (out / "quick.html").write_text(render_quick(cats, ctx))
    for c in cats:
        problems += [f"questions {c.num:02d}-{c.slug}: {p}" for p in c.problems]
    return problems
