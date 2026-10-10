"""Syntax highlighting plus definitions/references for the non-C languages.

C and headers are highlighted with Pygments; their cross references come from
libclang (cindex.py). Assembly, linker scripts and the Makefile are small and
regular, so they get hand-written scanners that understand exactly the
constructs xv6 uses and emit both highlighting and symbol facts.
"""

import re
from pathlib import Path

from pygments import lex
from pygments.lexers import (CLexer, EmacsLispLexer, PerlLexer, PythonLexer,
                             YamlLexer)
from pygments.token import Token

from .model import FileFacts, FLink, NDef, NRef, Tok

# ---------------------------------------------------------------- RISC-V names

REGS = ({"zero", "ra", "sp", "gp", "tp", "fp"} | {f"t{i}" for i in range(7)} |
        {f"s{i}" for i in range(12)} | {f"a{i}" for i in range(8)} |
        {f"x{i}" for i in range(32)})

CSRS = {
    "mstatus", "misa", "medeleg", "mideleg", "mie", "mtvec", "mcounteren", "mscratch",
    "mepc", "mcause", "mtval", "mip", "mhartid", "menvcfg", "mcountinhibit",
    "pmpcfg0", "pmpaddr0", "sstatus", "sie", "stvec", "scounteren", "sscratch", "sepc",
    "scause", "stval", "sip", "satp", "stimecmp", "senvcfg", "time", "cycle", "instret",
}

# ---------------------------------------------------------------- Pygments


def _pyg_class(tt) -> str:
    if tt in Token.Comment.Preproc or tt in Token.Comment.PreprocFile:
        return "pp"
    if tt in Token.Comment:
        return "cm"
    if tt in Token.Keyword.Type:
        return "kt"
    if tt in Token.Keyword:
        return "kw"
    if tt in Token.Literal.String:
        return "st"
    if tt in Token.Literal.Number:
        return "nu"
    if tt in Token.Name.Builtin:
        return "nb"
    if tt in Token.Operator or tt in Token.Punctuation:
        return "op"
    return ""


PYG = {"c": CLexer, "h": CLexer, "perl": PerlLexer, "python": PythonLexer,
       "yaml": YamlLexer, "elisp": EmacsLispLexer}


def pygments_toks(lang: str, text: str) -> list[Tok]:
    lexer_cls = PYG.get(lang)
    if lexer_cls is None:
        return []
    toks, line, col = [], 1, 0
    for tt, value in lex(text, lexer_cls(stripnl=False, ensurenl=False)):
        cls = _pyg_class(tt)
        parts = value.split("\n")
        for i, part in enumerate(parts):
            if i:
                line, col = line + 1, 0
            if part and cls:
                toks.append(Tok(line, col, col + len(part), cls))
            col += len(part)
    return toks


def c_identifiers(text: str) -> list[tuple[int, int, str, str]]:
    """(line, 1-based col, name, previous non-space chars) for C identifiers."""
    out, line, col, prev = [], 1, 0, ""
    for tt, value in lex(text, CLexer(stripnl=False, ensurenl=False)):
        parts = value.split("\n")
        for i, part in enumerate(parts):
            if i:
                line, col = line + 1, 0
            if part and tt in Token.Name and tt not in Token.Name.Builtin and \
                    re.fullmatch(r"[A-Za-z_]\w*", part):
                out.append((line, col + 1, part, prev))
            col += len(part)
        if value.strip():
            prev = (prev + value.strip())[-2:]
    return out


# ---------------------------------------------------------------- #include

INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"')


def include_links(path: str, lines: list[str], exists) -> list[FLink]:
    out = []
    here = Path(path).parent
    for n, s in enumerate(lines, 1):
        m = INCLUDE_RE.match(s)
        if not m:
            continue
        inc = m.group(1)
        for cand in ((here / inc).as_posix(), inc):
            if exists(cand):
                out.append(FLink(path, n, m.start(1) - 1, m.end(1) + 1, cand,
                                 f"open {cand}"))
                break
    return out


# ---------------------------------------------------------------- assembly

PP_RE = re.compile(r"\s*#\s*(include|define|undef|if|ifdef|ifndef|elif|else|endif)\b")
LABEL_RE = re.compile(r"\s*([A-Za-z_.$][\w.$]*):")
WORD_RE = re.compile(r"[A-Za-z_.$][\w.$]*|0[xX][0-9a-fA-F]+|-?\d+")


def scan_asm(path: str, group: str, lines: list[str]) -> FileFacts:
    ff = FileFacts()
    for n, s in enumerate(lines, 1):
        if PP_RE.match(s):
            ff.toks.append(Tok(n, 0, len(s), "pp"))
            continue
        hash_at = s.find("#")
        code = s if hash_at < 0 else s[:hash_at]
        if hash_at >= 0:
            ff.toks.append(Tok(n, hash_at, len(s), "cm"))
        pos = 0
        m = LABEL_RE.match(code)
        if m:
            name = m.group(1)
            ff.toks.append(Tok(n, m.start(1), m.end(1), "lbl"))
            ff.defs.append(NDef("asm", group, name, path, n, m.start(1) + 1, "label"))
            pos = m.end()
        words = list(WORD_RE.finditer(code, pos))
        if not words:
            continue
        op = words[0]
        opname = op.group()
        if opname.startswith("."):
            ff.toks.append(Tok(n, op.start(), op.end(), "dir", f"dir:{opname}"))
        else:
            ff.toks.append(Tok(n, op.start(), op.end(), "insn", f"insn:{opname}"))
        for w in words[1:]:
            name, c0, c1 = w.group(), w.start(), w.end()
            if name[0].isdigit() or name[0] == "-":
                ff.toks.append(Tok(n, c0, c1, "nu"))
            elif opname in (".globl", ".global"):
                ff.refs.append(NRef(path, n, c0 + 1, name, group, ("asm", "cext"), "decl"))
            elif opname == ".section":
                ff.toks.append(Tok(n, c0, c1, "sec"))
                if not name.startswith("."):
                    ff.defs.append(NDef("section", group, name, path, n, c0 + 1, "section"))
            elif name in REGS:
                ff.toks.append(Tok(n, c0, c1, "reg", f"reg:{name}"))
            elif name in CSRS:
                ff.toks.append(Tok(n, c0, c1, "csr", f"csr:{name}"))
            else:
                ff.refs.append(NRef(path, n, c0 + 1, name, group,
                                    ("asm", "cext", "ld", "macro")))
    return ff


# ---------------------------------------------------------------- linker script

LD_KEYWORDS = {"OUTPUT_ARCH", "ENTRY", "SECTIONS", "PROVIDE", "ALIGN", "ASSERT"}
LD_TOKEN_RE = re.compile(
    r'(?P<cm>/\*)|(?P<st>"[^"]*")|(?P<nu>0[xX][0-9a-fA-F]+|\d+)'
    r'|(?P<w>[A-Za-z_./*][\w./*-]*)|(?P<p>[()])')


def scan_ld(path: str, group: str, lines: list[str], src_exists) -> FileFacts:
    ff = FileFacts()
    in_comment = False
    paren_owner: list[str] = []     # word before each open "("
    last_word = ""
    for n, s in enumerate(lines, 1):
        pos = 0
        while pos < len(s):
            if in_comment:
                end = s.find("*/", pos)
                stop = len(s) if end < 0 else end + 2
                ff.toks.append(Tok(n, pos, stop, "cm"))
                in_comment = end < 0
                pos = stop
                continue
            m = LD_TOKEN_RE.search(s, pos)
            if not m:
                break
            pos = m.end()
            kind, text, c0, c1 = m.lastgroup, m.group(), m.start(), m.end()
            if kind == "cm":
                in_comment, pos = True, c0
            elif kind == "st":
                ff.toks.append(Tok(n, c0, c1, "st"))
            elif kind == "nu":
                ff.toks.append(Tok(n, c0, c1, "nu"))
            elif kind == "p":
                if text == "(":
                    paren_owner.append(last_word)
                elif paren_owner:
                    paren_owner.pop()
                last_word = ""
            else:
                rest = s[c1:].lstrip()
                owner = paren_owner[-1] if paren_owner else ""
                if text in LD_KEYWORDS or text == ".":
                    ff.toks.append(Tok(n, c0, c1, "kw", f"ld:{text}"))
                elif text == "*":
                    ff.toks.append(Tok(n, c0, c1, "op"))
                elif text.endswith(".o") and "/" in text:
                    stem = text[:-2]
                    for ext in (".S", ".c"):
                        if src_exists(stem + ext):
                            ff.flinks.append(FLink(path, n, c0, c1, stem + ext,
                                                   f"{text} is compiled from {stem + ext}"))
                            break
                elif owner == "ENTRY":
                    ff.refs.append(NRef(path, n, c0 + 1, text, group, ("asm", "cext")))
                elif owner == "*" or owner.endswith(".o"):
                    ff.toks.append(Tok(n, c0, c1, "sec"))
                    if not text.startswith("."):
                        ff.refs.append(NRef(path, n, c0 + 1, text, group, ("section",)))
                elif text.startswith(".") and rest.startswith(":"):
                    ff.toks.append(Tok(n, c0, c1, "sec"))
                    ff.defs.append(NDef("ldsec", group, text, path, n, c0 + 1,
                                        "output section"))
                elif rest.startswith("=") and not rest.startswith("=="):
                    ff.defs.append(NDef("ld", group, text, path, n, c0 + 1,
                                        "linker symbol"))
                elif not text.startswith("."):
                    ff.refs.append(NRef(path, n, c0 + 1, text, group, ("ld", "asm", "cext")))
                last_word = text
    return ff


# ---------------------------------------------------------------- Makefile

MAKE_FUNCS = {"shell", "wildcard", "patsubst", "subst", "filter", "filter-out",
              "foreach", "if", "call", "dir", "notdir", "basename", "addprefix",
              "addsuffix", "sort", "strip", "word", "words", "info", "error", "warning"}
MAKE_DIRECTIVES = re.compile(
    r"\s*(ifndef|ifdef|ifeq|ifneq|else|endif|-include|include|export|define|endef)\b")
ASSIGN_RE = re.compile(r"\s*([A-Za-z_][\w]*)\s*(\+=|:=|\?=|=)")
RULE_RE = re.compile(r"([^\t#=:][^=#:]*?)\s*:(?!=)")
VAR_RE = re.compile(r"\$\(([\w-]+)|\$\{([\w-]+)|\$([@<^*?%])|\$([A-Za-z])|\$\$")
WORD_RE_MAKE = re.compile(r"[^\s\\;'\"|<>]+")


def _expand(word: str) -> str:
    for v, val in (("K", "kernel"), ("U", "user")):
        word = word.replace(f"$({v})", val).replace(f"${v}", val)
    return word


def scan_make(path: str, lines: list[str], src_exists) -> FileFacts:
    ff = FileFacts()
    group = "build"
    targets: set[str] = set()
    seen_vars: set[str] = set()
    for s in lines:     # pass 1: collect target names for forward references
        if not s.startswith("\t") and not ASSIGN_RE.match(s) and \
                not MAKE_DIRECTIVES.match(s):
            m = RULE_RE.match(s)
            if m:
                targets.update(_expand(t) for t in m.group(1).split())

    def word_link(n: int, c0: int, c1: int, word: str) -> bool:
        """Link a path-like word to a source file or to a make target."""
        x = _expand(word)
        stem = x[:-2] if x.endswith(".o") else None
        prog = re.fullmatch(r"user/_(\w+)", x)
        if src_exists(x):
            ff.flinks.append(FLink(path, n, c0, c1, x, f"open {x}"))
        elif x in targets:
            ff.refs.append(NRef(path, n, c0 + 1, x, group, ("maketarget",)))
            return True
        elif stem and src_exists(stem + ".c"):
            ff.flinks.append(FLink(path, n, c0, c1, stem + ".c",
                                   f"{x} is compiled from {stem}.c"))
        elif stem and src_exists(stem + ".S"):
            ff.flinks.append(FLink(path, n, c0, c1, stem + ".S",
                                   f"{x} is assembled from {stem}.S"))
        elif prog and src_exists(f"user/{prog.group(1)}.c"):
            ff.flinks.append(FLink(path, n, c0, c1, f"user/{prog.group(1)}.c",
                                   f"the program {x} is built from user/{prog.group(1)}.c"))
        else:
            return False
        return True

    def values(n: int, s: str, start: int, linkable: bool = True) -> None:
        """Highlight variable uses, flags and file names in s[start:]."""
        linked: list[tuple[int, int]] = []
        if linkable:
            for w in WORD_RE_MAKE.finditer(s, start):
                word = w.group()
                if ("/" in word or "." in word or _expand(word) in targets) and \
                        not word.startswith("-") and "$(" not in word.replace("$(K)", "") \
                        .replace("$(U)", ""):
                    if word_link(n, w.start(), w.end(), word):
                        linked.append((w.start(), w.end()))
        for w in WORD_RE_MAKE.finditer(s, start):
            word = w.group().rstrip(")`")
            if word.startswith("-") and len(word) > 1 and \
                    not any(a <= w.start() < b for a, b in linked):
                flag = word.split("=")[0] if word.startswith("-m") else word
                ff.toks.append(Tok(n, w.start(), w.start() + len(word), "flag", f"flag:{flag}"))
        for m in VAR_RE.finditer(s, start):
            if any(a <= m.start() < b for a, b in linked):
                continue
            name = m.group(1) or m.group(2) or m.group(4)
            if m.group(3):
                ff.toks.append(Tok(n, m.start(), m.end(), "av", f"make:${m.group(3)}"))
            elif name in MAKE_FUNCS:
                ff.toks.append(Tok(n, m.start(), m.end(), "fn", f"make:{name}"))
            elif name:
                g0 = m.start(1) if m.group(1) else m.start(2) if m.group(2) else m.start(4)
                ff.toks.append(Tok(n, m.start(), g0, "var"))
                if name in seen_vars or name in ("K", "U"):
                    ff.refs.append(NRef(path, n, g0 + 1, name, group, ("makevar",)))
                else:
                    ff.toks.append(Tok(n, g0, g0 + len(name), "var", f"make:{name}"))

    continuation = None     # kind of the logical line being continued
    for n, s in enumerate(lines, 1):
        hash_at = -1
        for m in re.finditer(r"#", s):
            if m.start() == 0 or s[m.start() - 1] != "\\":
                hash_at = m.start()
                break
        code = s if hash_at < 0 else s[:hash_at]
        if hash_at >= 0:
            ff.toks.append(Tok(n, hash_at, len(s), "cm"))
        kind = continuation
        if kind is None:
            if s.startswith("\t"):
                kind = "recipe"
            elif (m := MAKE_DIRECTIVES.match(code)):
                kind = "directive"
                ff.toks.append(Tok(n, m.start(1), m.end(1), "kw", f"make:{m.group(1)}"))
                if m.group(1) in ("ifndef", "ifdef"):
                    name = code[m.end():].strip()
                    col = code.index(name, m.end())
                    if name in seen_vars:
                        ff.refs.append(NRef(path, n, col + 1, name, group, ("makevar",)))
                    else:
                        ff.toks.append(Tok(n, col, col + len(name), "var"))
                else:
                    values(n, code, m.end())
            elif (m := ASSIGN_RE.match(code)):
                kind = "assign"
                name = m.group(1)
                ff.defs.append(NDef("makevar", group, name, path, n, m.start(1) + 1,
                                    "make variable",
                                    "assign" if name in seen_vars else "def"))
                seen_vars.add(name)
                ff.toks.append(Tok(n, m.start(2), m.end(2), "op"))
                values(n, code, m.end())
            elif code.strip() and (m := RULE_RE.match(code)):
                kind = "rule"
                for t in re.finditer(r"\S+", m.group(1)):
                    word = t.group()
                    if word.startswith(".") and word[1:].isupper():
                        ff.toks.append(Tok(n, t.start(), t.end(), "kw", f"make:{word}"))
                        continue
                    ff.toks.append(Tok(n, t.start(), t.end(), "tgt"))
                    ff.defs.append(NDef("maketarget", group, _expand(word), path, n,
                                        t.start() + 1, "make target"))
                values(n, code, m.end())
            else:
                kind = "other"
                values(n, code, 0)
        else:
            values(n, code, 0)
        if kind == "recipe" and continuation is None:
            values(n, code, 0)
        continuation = kind if code.rstrip().endswith("\\") else None
    return ff


# ---------------------------------------------------------------- usys.pl

ENTRY_RE = re.compile(r'^entry\("(\w+)"\);')


def scan_usys_pl(path: str, lines: list[str]) -> FileFacts:
    ff = FileFacts()
    for n, s in enumerate(lines, 1):
        m = ENTRY_RE.match(s)
        if m:
            name = m.group(1)
            label = "sys_sbrk" if name == "sbrk" else name
            # entry("sbrk") generates the label sys_sbrk; link to that label.
            ff.refs.append(NRef(path, n, m.start(1) + 1, label, "user", ("asm",),
                                width=len(name)))
    return ff


# ---------------------------------------------------------------- inline asm in C

ASM_STR_RE = re.compile(r'asm\s+volatile\s*\(\s*"([^"]*)"')


def inline_asm_toks(lines: list[str]) -> list[Tok]:
    """Mark instruction, CSR and register names inside asm("...") strings."""
    toks = []
    for n, s in enumerate(lines, 1):
        for m in ASM_STR_RE.finditer(s):
            body, base = m.group(1), m.start(1)
            for i, w in enumerate(re.finditer(r"[A-Za-z_.][\w.]*", body)):
                name, c0, c1 = w.group(), base + w.start(), base + w.end()
                if i == 0:
                    toks.append(Tok(n, c0, c1, "insn", f"insn:{name}"))
                elif name in CSRS:
                    toks.append(Tok(n, c0, c1, "csr", f"csr:{name}"))
                elif name in REGS:
                    toks.append(Tok(n, c0, c1, "reg", f"reg:{name}"))
    return toks
