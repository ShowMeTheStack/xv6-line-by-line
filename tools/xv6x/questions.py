"""Test Yourself: self-graded questions.

annotations/questions/NN-slug.yaml is one category:

    title: Spinlocks and interrupt state
    summary: One sentence for the index card.
    questions:
      - id: spin-01            # unique across the site, [a-z0-9-]; never reuse or renumber
        level: 1               # 1 warm-up, 2 solid, 3 deep
        type: choice           # see TYPES
        q: |                   # the question (markdown, [[links]])
        code: kernel/spinlock.c:92-103      # optional excerpt (required for type line);
                                            # "@97-98" after the range marks focus lines
        explain: |             # the right way to think about it (markdown); shown after
                               # every answer, right or wrong
        ...type-specific fields, below

Every wrong answer the reader can give must have feedback written as a misconception:
"You may have thought X because Y" -- the page then shows `explain`.

choice   options: [{text, correct: true, why}, {text, why}, ...]   exactly one correct;
         the correct option's `why` says why it is right, each wrong one's `why` is the
         misconception behind choosing it.
multi    options: same shape, one or more correct. `why` on every option explains its
         status (shown when the reader gets that option wrong).
number   answer: 256 (or "0x100"); accept: [other equal spellings are automatic; list other
         acceptable values only if truly equivalent]; wrong: {128: "misconception", ...};
         why_wrong: feedback for any other wrong number (required).
order    items: [first, second, ...] in the correct order (3-8; each a string or
         {text, why}); why on an item is shown if that item is the first misplaced one;
         why_wrong: generic feedback (required).
line     code: required; answer: 105 or [105, 106]; lines: {101: "misconception", ...};
         why_wrong: feedback for any other line (required).
state    state: {mode: S, stack: kernel, sie: off, noff: 1, intena: 1, satp: kernel}
         (any subset of these fields, at least 2); why: {field: "misconception if this
         field is wrong"}; why_wrong: generic (required).
bits     value: "0x200000122" (shown); fields: [{label, options: [...], answer, why}]
         (2-6 fields; why = misconception if wrong).
match    pairs: [{left, right, why}] (3-6; rights must be distinct; why = misconception
         if this left is matched wrongly).
tf       answer: true | false; why_tf: misconception if the reader picks the wrong
         truth value (required); reasons: [{text, correct: true, why}, {text, why}, ...]
         exactly one correct (the reason it is true/false).
"""

import base64
import json
import random
import re
from dataclasses import dataclass, field
from html import escape

import yaml

from .config import ANNOTATIONS

QDIR = ANNOTATIONS / "questions"
TYPES = ("choice", "multi", "number", "order", "line", "state", "bits", "match", "tf")
LEVELS = {1: "warm-up", 2: "solid", 3: "deep"}
TYPE_LABEL = {
    "choice": "Choose one", "multi": "Choose all that apply", "number": "Type a number",
    "order": "Put in order", "line": "Click the line", "state": "Fill in the machine state",
    "bits": "Decode the bits", "match": "Match the pairs", "tf": "True or false, and why",
}
# Machine-state fields: name -> (label, [(value, display)])
STATE_FIELDS = {
    "mode": ("Privilege mode", [("M", "M (machine)"), ("S", "S (supervisor)"), ("U", "U (user)")]),
    "stack": ("Active stack", [("user", "user stack"), ("kernel", "the process's kernel stack"),
                               ("scheduler", "scheduler stack (stack0)"),
                               ("boot", "boot stack (stack0)"), ("none", "no usable stack")]),
    "satp": ("Page table (satp)", [("bare", "paging off"), ("kernel", "kernel page table"),
                                    ("user", "user page table")]),
    "sie": ("Interrupts (sstatus.SIE)", [("on", "on"), ("off", "off")]),
    "noff": ("noff", [(str(i), str(i)) for i in range(5)]),
    "intena": ("intena", [("0", "0"), ("1", "1"), ("-", "— (noff is 0)")]),
}


@dataclass
class Question:
    id: str
    level: int
    type: str
    raw: dict


@dataclass
class Category:
    num: int
    slug: str
    title: str
    summary: str
    questions: list[Question]
    problems: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"test/{self.num:02d}-{self.slug}.html"


def parse_num(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip().lower().replace("_", "").replace(",", "").replace(" ", "")
    try:
        if s.startswith(("0x", "-0x")):
            return int(s, 16)
        if s.startswith(("0b", "-0b")):
            return int(s, 2)
        return int(s, 10)
    except ValueError:
        return None


def parse_code(spec: str):
    """'kernel/x.c:10-20@12-13' -> (path, a, b, fa, fb)."""
    m = re.fullmatch(r"([\w./-]+):(\d+)(?:-(\d+))?(?:@(\d+)(?:-(\d+))?)?", str(spec).strip())
    if not m:
        return None
    a = int(m.group(2)); b = int(m.group(3) or a)
    fa = int(m.group(4)) if m.group(4) else None
    fb = int(m.group(5) or m.group(4)) if m.group(4) else None
    return m.group(1), a, b, fa, fb


def _need(q: dict, keys, where, probs):
    for k in keys:
        if q.get(k) in (None, "", [], {}):
            probs.append(f"{where}: needs `{k}`")


def validate(q: dict, where: str, files: dict) -> list[str]:
    probs: list[str] = []
    t = q.get("type")
    if t not in TYPES:
        return [f"{where}: type must be one of {', '.join(TYPES)}"]
    if q.get("level") not in LEVELS:
        probs.append(f"{where}: level must be 1, 2 or 3")
    _need(q, ["q", "explain"], where, probs)
    code = None
    if q.get("code"):
        code = parse_code(q["code"])
        if not code:
            probs.append(f"{where}: bad code spec {q['code']!r}")
        else:
            path, a, b, fa, fb = code
            f = files.get(path)
            if f is None:
                probs.append(f"{where}: unknown file {path}")
                code = None
            else:
                n = len(f.text_lines())
                if not (1 <= a <= b <= n) or b - a > 60 or (fa and not a <= fa <= fb <= b):
                    probs.append(f"{where}: code range {q['code']} invalid (max 61 lines)")
                    code = None
    if t in ("choice", "multi"):
        opts = q.get("options") or []
        nc = sum(1 for o in opts if o.get("correct"))
        if not 3 <= len(opts) <= 6:
            probs.append(f"{where}: {t} needs 3-6 options")
        if t == "choice" and nc != 1:
            probs.append(f"{where}: choice needs exactly one correct option (has {nc})")
        if t == "multi" and nc < 1:
            probs.append(f"{where}: multi needs at least one correct option")
        for i, o in enumerate(opts, 1):
            if not o.get("text") or not o.get("why"):
                probs.append(f"{where}: option {i} needs text and why")
        texts = [str(o.get("text", "")).strip().lower() for o in opts]
        if len(set(texts)) != len(texts):
            probs.append(f"{where}: duplicate option text")
    elif t == "number":
        if parse_num(q.get("answer")) is None:
            probs.append(f"{where}: answer must be an integer (decimal, 0x hex or 0b binary)")
        for k in (q.get("wrong") or {}):
            if parse_num(k) is None:
                probs.append(f"{where}: wrong-answer key {k!r} is not a number")
            elif parse_num(k) == parse_num(q.get("answer")):
                probs.append(f"{where}: wrong-answer key {k!r} equals the answer")
        _need(q, ["why_wrong"], where, probs)
    elif t == "order":
        items = q.get("items") or []
        if not 3 <= len(items) <= 8:
            probs.append(f"{where}: order needs 3-8 items")
        texts = [str(i["text"] if isinstance(i, dict) else i) for i in items]
        if len(set(texts)) != len(texts):
            probs.append(f"{where}: duplicate order items")
        _need(q, ["why_wrong"], where, probs)
    elif t == "line":
        if not code:
            probs.append(f"{where}: line questions need a valid code excerpt")
        else:
            ans = q.get("answer")
            ans = ans if isinstance(ans, list) else [ans]
            for x in ans + list((q.get("lines") or {}).keys()):
                if not isinstance(x, int) or not code[1] <= x <= code[2]:
                    probs.append(f"{where}: line {x!r} is not inside the excerpt")
        _need(q, ["why_wrong"], where, probs)
    elif t == "state":
        st = q.get("state") or {}
        if len(st) < 2:
            probs.append(f"{where}: state needs at least 2 fields")
        for k, v in st.items():
            if k not in STATE_FIELDS:
                probs.append(f"{where}: unknown state field {k!r}")
            elif str(v if not isinstance(v, bool) else ("on" if v else "off")) not in \
                    [x for x, _ in STATE_FIELDS[k][1]]:
                probs.append(f"{where}: state.{k} = {v!r} is not an allowed value")
        _need(q, ["why_wrong"], where, probs)
    elif t == "bits":
        fs = q.get("fields") or []
        if not 2 <= len(fs) <= 6:
            probs.append(f"{where}: bits needs 2-6 fields")
        for i, f in enumerate(fs, 1):
            if not f.get("label") or not f.get("options") or "answer" not in f or not f.get("why"):
                probs.append(f"{where}: field {i} needs label, options, answer, why")
            elif str(f["answer"]) not in [str(o) for o in f["options"]]:
                probs.append(f"{where}: field {i} answer not among its options")
        _need(q, ["value"], where, probs)
    elif t == "match":
        ps = q.get("pairs") or []
        if not 3 <= len(ps) <= 6:
            probs.append(f"{where}: match needs 3-6 pairs")
        rights = [str(p.get("right", "")) for p in ps]
        if len(set(rights)) != len(rights):
            probs.append(f"{where}: match right-hand sides must be distinct")
        for i, p in enumerate(ps, 1):
            if not p.get("left") or not p.get("right") or not p.get("why"):
                probs.append(f"{where}: pair {i} needs left, right, why")
    elif t == "tf":
        if q.get("answer") not in (True, False):
            probs.append(f"{where}: tf answer must be true or false")
        _need(q, ["why_tf"], where, probs)
        rs = q.get("reasons") or []
        if not 2 <= len(rs) <= 5 or sum(1 for r in rs if r.get("correct")) != 1:
            probs.append(f"{where}: tf needs 2-5 reasons with exactly one correct")
        for i, r in enumerate(rs, 1):
            if not r.get("text") or not r.get("why"):
                probs.append(f"{where}: reason {i} needs text and why")
    return probs


def load(files) -> list[Category]:
    by_path = {f.path: f for f in files}
    cats = []
    seen: dict[str, str] = {}
    for p in sorted(QDIR.glob("*.yaml")) if QDIR.exists() else []:
        m = re.fullmatch(r"(\d+)-([\w-]+)\.yaml", p.name)
        if not m:
            continue
        probs: list[str] = []
        try:
            raw = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError as e:
            cats.append(Category(int(m.group(1)), m.group(2), p.name, "", [], [f"YAML: {e}"]))
            continue
        qs = []
        for i, q in enumerate(raw.get("questions") or [], 1):
            qid = str(q.get("id") or "")
            where = f"q{i} {qid}"
            if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", qid):
                probs.append(f"{where}: bad or missing id")
            elif qid in seen:
                probs.append(f"{where}: id also used in {seen[qid]}")
            seen[qid] = p.name
            probs += validate(q, where, by_path)
            qs.append(Question(qid, q.get("level", 0), q.get("type", ""), q))
        if not raw.get("title"):
            probs.append("missing title")
        cats.append(Category(int(m.group(1)), m.group(2), raw.get("title", ""),
                             str(raw.get("summary") or "").strip(), qs, probs))
    return sorted(cats, key=lambda c: c.num)


# ---------------------------------------------------------------- rendering

def _enc(obj) -> str:
    return base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()


def _rng(qid: str) -> random.Random:
    return random.Random("xv6-q-" + qid)


def _shuffled(qid: str, n: int, avoid_identity: bool = False) -> list[int]:
    idx = list(range(n))
    r = _rng(qid)
    for _ in range(20):
        r.shuffle(idx)
        if not avoid_identity or idx != list(range(n)) or n < 2:
            break
    return idx


def render_question(q: Question, k: int, ctx) -> str:
    """ctx: object with md(text)->html, inline(text)->html, excerpt(path,a,b,fa,fb)->html."""
    r = q.raw
    t = q.type
    md, inline = ctx.md, ctx.inline
    code_html = ""
    if r.get("code"):
        c = parse_code(r["code"])
        if c:
            path, a, b, fa, fb = c
            if t == "line":
                fa, fb = 0, 0       # nothing pre-highlighted: the reader picks
            code_html = (f'<div class="qcode"><div class="qfile">{escape(path)}</div>'
                         f'<div class="code excerpt">{ctx.excerpt(path, a, b, a if fa is None else fa, b if fb is None else fb)}'
                         f'</div></div>')
    ex = md(r.get("explain", ""))
    pay: dict = {"t": t, "ex": ex}
    body = ""
    name = f"q-{q.id}"
    if t in ("choice", "multi"):
        opts = r["options"]
        order = _shuffled(q.id, len(opts))
        kind = "radio" if t == "choice" else "checkbox"
        pay["o"] = [{"c": bool(opts[i].get("correct")), "w": md(opts[i]["why"]),
                     "x": inline(str(opts[i]["text"]))} for i in order]
        body = '<div class="qopts">' + "".join(
            f'<label class="qopt"><input type="{kind}" name="{name}" value="{j}">'
            f'<span>{inline(str(opts[i]["text"]))}</span></label>'
            for j, i in enumerate(order)) + "</div>"
    elif t == "number":
        pay["a"] = [parse_num(r["answer"])] + [parse_num(x) for x in r.get("accept") or []]
        pay["wr"] = {str(parse_num(k2)): md(v) for k2, v in (r.get("wrong") or {}).items()}
        pay["g"] = md(r["why_wrong"])
        pay["as"] = str(r["answer"])
        body = (f'<div class="qnum"><input type="text" inputmode="text" autocomplete="off" '
                f'spellcheck="false" aria-label="Your answer" placeholder="e.g. 42 or 0x2a">'
                f'<span class="qhint">decimal, 0x hex or 0b binary</span></div>')
    elif t == "order":
        items = [i if isinstance(i, dict) else {"text": i} for i in r["items"]]
        order = _shuffled(q.id, len(items), avoid_identity=True)
        pay["w"] = [md(it["why"]) if it.get("why") else "" for it in items]
        pay["x"] = [inline(str(it["text"])) for it in items]
        pay["g"] = md(r["why_wrong"])
        body = '<ol class="qorder">' + "".join(
            f'<li data-i="{i}"><span class="qotext">{inline(str(items[i]["text"]))}</span>'
            f'<span class="qomove"><button type="button" class="qup" aria-label="Move up">↑</button>'
            f'<button type="button" class="qdn" aria-label="Move down">↓</button></span></li>'
            for i in order) + "</ol>"
    elif t == "line":
        ans = r["answer"] if isinstance(r["answer"], list) else [r["answer"]]
        pay["a"] = ans
        pay["wl"] = {str(k2): md(v) for k2, v in (r.get("lines") or {}).items()}
        pay["g"] = md(r["why_wrong"])
        body = '<p class="qpick">Your pick: <b class="qpicked">none yet</b> (click a line in the code)</p>'
    elif t in ("state", "bits"):
        fields = []
        if t == "state":
            for key, v in r["state"].items():
                label, opts = STATE_FIELDS[key]
                val = "on" if v is True else "off" if v is False else str(v)
                fields.append({"label": label, "opts": opts, "a": val,
                               "w": (r.get("why") or {}).get(key)})
        else:
            for f in r["fields"]:
                fields.append({"label": f["label"], "opts": [(str(o), str(o)) for o in f["options"]],
                               "a": str(f["answer"]), "w": f.get("why")})
        pay["f"] = [{"a": f["a"], "w": md(f["w"]) if f["w"] else "",
                     "d": dict(f["opts"])[f["a"]], "l": f["label"]} for f in fields]
        if t == "state":
            # With noff 0, intena still holds a stale 0 or 1 that nothing reads: any choice
            # is accepted, and the feedback says why.
            for f, pf in zip(fields, pay["f"]):
                if f["label"] == "intena" and f["a"] == "-":
                    pf["a"] = "*"
                    pf["n"] = md("With noff 0, intena is not in use: it still holds a stale 0 "
                                 "or 1 from the last outermost push_off, and the next outermost "
                                 "push_off will overwrite it ([[concept:locks#intena]]).")
        pay["g"] = md(r.get("why_wrong", "")) if r.get("why_wrong") else ""
        val = (f'<p class="qval">Value: <code>{escape(str(r["value"]))}</code></p>'
               if t == "bits" else "")
        body = val + '<div class="qfields">' + "".join(
            f'<label class="qfield"><span>{inline(f["label"])}</span><select>'
            f'<option value="">choose…</option>'
            + "".join(f'<option value="{escape(v)}">{escape(d)}</option>' for v, d in f["opts"])
            + "</select></label>" for f in fields) + "</div>"
    elif t == "match":
        ps = r["pairs"]
        rorder = _shuffled(q.id, len(ps), avoid_identity=True)
        pay["a"] = [str(i) for i in range(len(ps))]
        pay["w"] = [md(p["why"]) for p in ps]
        pay["x"] = [inline(str(p["right"])) for p in ps]
        pay["l"] = [inline(str(p["left"])) for p in ps]
        opts = "".join(f'<option value="{i}">{escape(re.sub("<[^>]+>", "", inline(str(ps[i]["right"]))))}</option>'
                       for i in rorder)
        body = '<div class="qfields qmatch">' + "".join(
            f'<label class="qfield"><span>{inline(str(p["left"]))}</span><select>'
            f'<option value="">choose…</option>{opts}</select></label>' for p in ps) + "</div>"
    elif t == "tf":
        rs = r["reasons"]
        order = _shuffled(q.id, len(rs))
        pay["a"] = bool(r["answer"])
        pay["wtf"] = md(r["why_tf"])
        pay["r"] = [{"c": bool(rs[i].get("correct")), "w": md(rs[i]["why"]),
                     "x": inline(str(rs[i]["text"]))} for i in order]
        body = (f'<div class="qopts qtf"><label class="qopt"><input type="radio" name="{name}-tf" '
                f'value="1"><span>True</span></label><label class="qopt"><input type="radio" '
                f'name="{name}-tf" value="0"><span>False</span></label></div>'
                f'<p class="qsub">Why?</p><div class="qopts qreasons">' + "".join(
                    f'<label class="qopt"><input type="radio" name="{name}-r" value="{j}">'
                    f'<span>{inline(str(rs[i]["text"]))}</span></label>'
                    for j, i in enumerate(order)) + "</div>")
    lvl = LEVELS.get(q.level, "")
    return (f'<article class="qz" id="{escape(q.id)}" data-id="{escape(q.id)}" data-type="{t}" '
            f'data-k="{_enc(pay)}">'
            f'<header class="qh"><span class="qn">{k}</span>'
            f'<span class="qlvl l{q.level}">{lvl}</span><span class="qtype">{TYPE_LABEL[t]}</span>'
            f'<span class="qstatus" aria-live="polite"></span></header>'
            f'<div class="qq">{md(r["q"])}</div>{code_html}<div class="qans">{body}</div>'
            f'<div class="qbtns"><button type="button" class="btn qcheck">Check</button>'
            f'<button type="button" class="btn qretry" hidden>Try again</button></div>'
            f'<div class="qfb" hidden></div></article>')
