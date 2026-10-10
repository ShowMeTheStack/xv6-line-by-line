"""Merge every indexer's facts into one table of symbols.

A symbol is identified by where it is defined. Everything else - prototypes,
uses, .globl lines - is an "occurrence" of that symbol with a role:

  def     the definition
  decl    a declaration that is not the definition (prototype, extern, .globl)
  assign  a later assignment (Makefile "+=")
  ref     any other use

Names are resolved the way the linker would: within one program ("group").
The kernel's printf and the user library's printf are different symbols. A C
prototype with no C definition (swtch, trampoline, etext...) is linked to the
assembly label or linker-script symbol of the same name in the same program.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from .cindex import Decl, Ref
from .config import ULIB
from .model import FileFacts, NDef, NRef

Loc = tuple[str, int, int]          # path, line, 1-based column


@dataclass
class Sym:
    name: str
    kind: str
    type: str
    group: str
    lang: str                       # c, asm, ld, make
    defloc: Loc
    id: int = -1
    occ: dict[Loc, tuple[int, str]] = field(default_factory=dict)  # loc -> (width, role)

    def add(self, loc: Loc, width: int, role: str) -> None:
        old = self.occ.get(loc)
        rank = {"def": 0, "decl": 1, "assign": 2, "ref": 3}
        if old is None or rank[role] < rank[old[1]]:
            self.occ[loc] = (width, role)


class SymbolTable:
    def __init__(self) -> None:
        self.by_loc: dict[Loc, Sym] = {}
        self.c_map: dict[tuple[str, str], list[Sym]] = defaultdict(list)  # (group, usr)
        self.native: dict[tuple[str, str, str], Sym] = {}                 # (ns, group, name)
        self.cext: dict[tuple[str, str], list[Sym]] = defaultdict(list)   # (group, name)
        self.macros: dict[str, list[Sym]] = defaultdict(list)
        self.cnames: dict[tuple[str, str], list[Sym]] = defaultdict(list)  # file-scope names
        self.syms: list[Sym] = []
        # path -> list of (line, c0, c1, [sym], role)
        self.links: dict[str, list[tuple[int, int, int, list[Sym], str]]] = defaultdict(list)
        self.includes: dict[str, set[str]] = defaultdict(set)

    # -------------------------------------------------------------- build
    def _sym(self, loc: Loc, **kw) -> Sym:
        s = self.by_loc.get(loc)
        if s is None:
            s = self.by_loc[loc] = Sym(defloc=loc, **kw)
        return s

    def build(self, decls: list[Decl], refs: list[Ref], facts: dict[str, FileFacts],
              flinks_by_path: dict[str, list], idents=None, extents=()) -> None:
        for path, fl in flinks_by_path.items():
            for link in fl:
                self.includes[path].add(link.target)

        # 1. C definitions.
        for d in decls:
            if not d.is_def:
                continue
            loc = (d.path, d.line, d.col)
            s = self._sym(loc, name=d.name, kind=d.kind, type=d.type, group=d.group,
                          lang="c")
            if s not in self.c_map[(d.group, d.usr)]:
                self.c_map[(d.group, d.usr)].append(s)
            if d.kind == "macro" and s not in self.macros[d.name]:
                self.macros[d.name].append(s)
            if d.kind in ("typedef", "function", "variable", "enumerator") and \
                    s not in self.cnames[(d.group, d.name)]:
                self.cnames[(d.group, d.name)].append(s)
            if d.external and d.kind in ("function", "variable") and \
                    s not in self.cext[(d.group, d.name)]:
                self.cext[(d.group, d.name)].append(s)

        # 2. Assembly / linker script / Makefile definitions.
        for ff in facts.values():
            for nd in ff.defs:
                key = (nd.ns, nd.group, nd.name)
                loc = (nd.path, nd.line, nd.col)
                if key not in self.native:
                    lang = {"asm": "asm", "section": "asm", "ld": "ld", "ldsec": "ld"} \
                        .get(nd.ns, "make")
                    self.native[key] = self._sym(loc, name=nd.name, kind=nd.kind,
                                                 type="", group=nd.group, lang=lang)
                self.native[key].add(loc, len(nd.name), nd.role)

        # 3. C names that are only declared: link to asm/ld, else keep the decl.
        for d in decls:
            key = (d.group, d.usr)
            if key in self.c_map:
                continue
            target = None
            if d.external:
                target = (self.native.get(("asm", d.group, d.name)) or
                          self.native.get(("ld", d.group, d.name)))
            if target is None:
                # e.g. kernel/file.h read by a user program: use the definition
                # the same entity has in another program.
                other = [ss for (g, u), lst in self.c_map.items() if u == d.usr
                         for ss in lst if g != d.group]
                target = other[0] if other else None
            if target is None:
                target = self._sym((d.path, d.line, d.col), name=d.name, kind=d.kind,
                                   type=d.type, group=d.group, lang="c")
                target.kind += " (declared only)"
            elif not target.type:
                target.type = d.type
            self.c_map[key].append(target)
            if d.external and d.kind in ("function", "variable"):
                self.cext[(d.group, d.name)].append(target)

        # 4. Occurrences.
        for d in decls:
            for s in self._resolve_c(d.group, d.usr, d.path):
                loc = (d.path, d.line, d.col)
                s.add(loc, len(d.name), "def" if loc == s.defloc else "decl")
        for r in refs:
            for s in self._resolve_c(r.group, r.usr, r.path):
                s.add((r.path, r.line, r.col), len(r.name), "ref")
        for ff in facts.values():
            for nr in ff.refs:
                for s in self._resolve_native(nr):
                    s.add((nr.path, nr.line, nr.col), nr.width or len(nr.name), nr.role)

        # 5. Identifiers libclang could not place (mostly macro arguments, which
        #    it reports at the macro's position): resolve by C scope rules.
        if idents:
            self._resolve_by_scope(idents, extents, decls)

        # 6. Number the symbols and build per-file link lists.
        used = [s for s in self.by_loc.values() if s.occ]
        used.sort(key=lambda s: (s.defloc, s.name))
        for i, s in enumerate(used):
            s.id = i
        self.syms = used
        by_occ: dict[tuple[str, int, int, int], list[tuple[Sym, str]]] = defaultdict(list)
        for s in used:
            for (path, line, col), (width, role) in s.occ.items():
                by_occ[(path, line, col, width)].append((s, role))
        for (path, line, col, width), entries in sorted(by_occ.items()):
            role = min((r for _, r in entries),
                       key=["def", "decl", "assign", "ref"].index)
            self.links[path].append((line, col - 1, col - 1 + width,
                                     [s for s, _ in entries], role))

    def _resolve_by_scope(self, idents, extents, decls) -> None:
        covered = {loc for s in self.by_loc.values() for loc in s.occ}
        group_of = {d.path: d.group for d in decls}
        funcs = defaultdict(list)
        for x in extents:
            funcs[x.path].append(x)
        scoped = defaultdict(list)          # (path, name) -> locals/params
        fields = defaultdict(list)          # (group, name) -> fields
        for s in self.by_loc.values():
            if s.kind in ("local", "parameter"):
                scoped[(s.defloc[0], s.name)].append(s)
            elif s.kind == "field" and s not in fields[(s.group, s.name)]:
                fields[(s.group, s.name)].append(s)
        for path, toks in idents.items():
            group = group_of.get(path)
            for line, col, name, prev in toks:
                loc = (path, line, col)
                if loc in covered:
                    continue
                found: list[Sym] = []
                if prev.endswith(".") or prev == "->":
                    cands = fields.get((group, name), [])
                    found = cands if len(cands) == 1 else []
                else:
                    fn = next((x for x in funcs.get(path, ()) if x.start <= line <= x.end),
                              None)
                    if fn:
                        cands = [s for s in scoped.get((path, name), [])
                                 if fn.start <= s.defloc[1] <= line]
                        if cands:
                            found = [max(cands, key=lambda s: s.defloc[1:])]
                    if not found:
                        found = self._resolve_native(
                            NRef(path, line, col, name, group or "", ("macro", "cname")))
                for s in found:
                    s.add(loc, len(name), "ref")

    # -------------------------------------------------------------- resolution
    def _resolve_c(self, group: str, usr: str, path: str) -> list[Sym]:
        cands = self.c_map.get((group, usr), [])
        if len(cands) > 1:
            same = [s for s in cands if s.defloc[0] == path]
            if same:
                return same
            if group == "user" and path not in ULIB:
                lib = [s for s in cands if s.defloc[0] in ULIB]
                if lib:
                    return lib
        return cands

    def _resolve_native(self, nr: NRef) -> list[Sym]:
        for ns in nr.lookup:
            if ns == "cext":
                found = self.cext.get((nr.group, nr.name), [])
            elif ns == "cname":
                found = self.cnames.get((nr.group, nr.name), []) or \
                    self.cext.get((nr.group, nr.name), [])
            elif ns == "macro":
                found = self.macros.get(nr.name, [])
                if len(found) > 1:
                    near = self._included(nr.path) | {nr.path}
                    found = [s for s in found if s.defloc[0] in near] or found
            else:
                s = self.native.get((ns, nr.group, nr.name))
                found = [s] if s else []
            if found:
                return found
        return []

    def _included(self, path: str) -> set[str]:
        seen, todo = set(), [path]
        while todo:
            p = todo.pop()
            for q in self.includes.get(p, ()):
                if q not in seen:
                    seen.add(q)
                    todo.append(q)
        return seen
