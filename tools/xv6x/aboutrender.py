"""The "About the creator" page, from annotations/about.yaml."""

from html import escape

import yaml

from .config import ANNOTATIONS
from .render import HEAD, SCRIPTS, TOP

ICONS = {
    "mail": '<path d="M3 6h18v12H3z M3 7l9 6 9-6"/>',
    "blog": '<path d="M5 4h10l4 4v12H5z M15 4v4h4 M8 12h8 M8 16h6"/>',
    "company": '<path d="M4 20V8l8-4 8 4v12z M9 20v-5h6v5 M8 10h2 M14 10h2"/>',
    "linkedin": '<path d="M4 4h16v16H4z M8 10v6 M8 7.5v.5 M12 16v-6 M12 13c0-2 4-2 4 0v3"/>',
}


def _icon(name: str) -> str:
    return (f'<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
            f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
            f'{ICONS.get(name, "")}</svg>')


def render(linker, problems: list[str]) -> str:
    d = yaml.safe_load((ANNOTATIONS / "about.yaml").read_text())
    root = ""
    md = lambda t: linker.render(str(t or ""), root, "", None, problems)
    inline = lambda t: linker.render_inline(str(t or ""), root, problems)

    links = "".join(f'<a class="ab-link" href="{escape(l["href"])}">{_icon(l.get("icon", ""))}'
                    f'<span>{escape(l["label"])}</span></a>' for l in d["links"])
    roles = "".join(f"<li>{escape(r)}</li>" for r in d["roles"])
    stats = "".join(
        f'<div class="ab-stat"><b data-n="{s["n"]}" data-suffix="{escape(s.get("suffix", ""))}">'
        f'{s["n"]}{escape(s.get("suffix", ""))}</b><span>{escape(s["label"])}</span>'
        f'<small>{escape(s.get("sub", ""))}</small></div>' for s in d["stats"])
    hero = (f'<section class="ab-hero"><div class="ab-glow" aria-hidden="true"></div>'
            f'<div class="ab-hero-in"><div class="ab-photo"><img src="{escape(d["photo"])}" '
            f'alt="Portrait of {escape(d["name"])}" width="349" height="481"></div>'
            f'<div class="ab-id"><p class="ab-kicker">The creator of xv6, line by line</p>'
            f'<h1>{escape(d["name"])}</h1><ul class="ab-roles">{roles}</ul>'
            f'<p class="ab-tag">{escape(d["tagline"].strip())}</p>'
            f'<div class="ab-links">{links}</div></div></div>'
            f'<div class="ab-stats">{stats}</div></section>')

    def section(sid, title, body, kicker=""):
        k = f'<p class="ab-sk">{escape(kicker)}</p>' if kicker else ""
        return f'<section class="ab-sec" id="{sid}">{k}<h2>{escape(title)}</h2>{body}</section>'

    why = f'<div class="ab-why">{md(d["why"])}</div>'
    profile = f'<div class="ab-prose">{md(d["profile"])}</div>'

    books = "".join(
        f'<article class="ab-book{" ab-feature" if b.get("note") else ""}">'
        f'<div class="ab-cover" aria-hidden="true"><span>{escape(b["title"].split(":")[0])}</span>'
        f'<small>De Gruyter Brill</small></div><div><p class="ab-status">{escape(b.get("status", ""))}'
        f'</p><h3>{escape(b["title"])}</h3><p class="ab-meta">{escape(b["authors"])}<br>'
        f'{escape(b["venue"])} · ISBN {escape(b["isbn"])}</p>'
        + (f'<p class="ab-note">{escape(b["note"])}</p>' if b.get("note") else "")
        + "</div></article>" for b in d["books"])

    edu = "".join(
        f'<article class="ab-card"><p class="ab-years">{escape(e["years"])}</p><h3>{escape(e["degree"])}</h3>'
        f'<p class="ab-org">{escape(e["school"])}</p><ul>'
        + "".join(f"<li>{inline(p)}</li>" for p in e["points"]) + "</ul></article>" for e in d["education"])

    exp = "".join(
        f'<li><span class="ab-dot" aria-hidden="true"></span><div><p class="ab-years">{escape(x["years"])}</p>'
        f'<h3>{escape(x["role"])}</h3><p class="ab-org">{escape(x["org"])}</p><p>{inline(x["text"])}</p></div></li>'
        for x in d["experience"])

    def tool(s):
        live = bool(s.get("href"))
        status = (f'<p class="ab-tstat{" live" if live else ""}">{escape(s["status"])}</p>'
                  if s.get("status") else "")
        paper = f'<p class="ab-tpaper"><b>Paper:</b> {inline(s["paper"])}</p>' if s.get("paper") else ""
        shot = (f'<figure class="ab-shot"><img src="{escape(s["shot"])}" width="1200" height="750" '
                f'loading="lazy" alt="{escape(s["name"])}: {escape(s.get("caption", ""))}">'
                f'<figcaption>{escape(s.get("caption", ""))}</figcaption></figure>') if s.get("shot") else ""
        body = f'{shot}<div class="ab-tbody">{status}<h3>{escape(s["name"])}</h3><p>{escape(s["text"])}</p>{paper}'
        if live:
            return (f'<a class="ab-tool" href="{escape(s["href"])}">{body}'
                    f'<span class="ab-go">{escape(s["href"].replace("https://", ""))} →</span></div></a>')
        return f'<div class="ab-tool ab-soon">{body}</div></div>'
    sw = "".join(tool(s) for s in d["software"])

    pats = "".join(f'<li><span class="ab-num">{escape(p["number"])}</span>{escape(p["title"])}</li>'
                   for p in d["patents"])

    def pub(p):
        href = p.get("href") or (f'https://doi.org/{p["doi"]}' if p.get("doi") else "")
        t = escape(p["title"])
        t = f'<a href="{escape(href)}">{t}</a>' if href else t
        return (f'<li><span class="ab-pt">{escape(p.get("tag", ""))}</span><div>{t}'
                f'<small>{escape(p["venue"])}</small></div></li>')
    pubs = "".join(pub(p) for p in d["publications"])

    honors = "".join(f"<li>{escape(h)}</li>" for h in d["honors"])
    skills = "".join(f'<span class="ab-chip">{escape(s)}</span>' for s in d["skills"])

    body = (hero
            + '<main class="ab-main">'
            + section("why", "Why this site exists", why, "A note on the project")
            + section("profile", "Profile", profile)
            + section("books", "Books", f'<div class="ab-books">{books}</div>', "De Gruyter Brill, 2026")
            + section("software", "Teaching tools", f'<div class="ab-tools">{sw}</div>',
                      "Free, in the browser")
            + section("education", "Education", f'<div class="ab-cards">{edu}</div>')
            + section("experience", "Experience", f'<ol class="ab-tl">{exp}</ol>')
            + section("patents", "Patents", f'<p class="ab-sub">Inventors: {escape(d["patent_inventors"])}</p>'
                      f'<ol class="ab-pats">{pats}</ol>', "Six published patent applications")
            + section("publications", "Publications", f'<ol class="ab-pubs">{pubs}</ol>',
                      "Sixteen papers")
            + section("honors", "Honors", f'<ul class="ab-honors">{honors}</ul>')
            + section("skills", "Expertise", f'<div class="ab-chips">{skills}</div>')
            + "</main>")
    return (HEAD.format(title=f"About the creator · xv6, line by line", root=root)
            + f'<body class="about-page" data-root="{root}" data-file="">\n'
            + TOP.format(root=root, crumb="about the creator") + body + SCRIPTS.format(root=root)
            + f'<script src="{root}assets/about.js" defer></script>\n</body>\n</html>\n')
