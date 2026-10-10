"""Index C translation units with libclang.

Each translation unit (a .c file plus every header it includes) is parsed with
the same flags the Makefile uses. We record two kinds of facts, keyed by the
exact (file, line, column) of the identifier in the source:

  Decl: a name is declared or defined here (function, variable, struct, macro...)
  Ref:  a name is used here, and refers to the entity with a given USR

A USR ("unified symbol resolution") is clang's stable name for an entity, e.g.
"c:@F@kalloc" for the function kalloc. Two files that mention the same external
function produce the same USR; that is how a call in proc.c finds its
definition in kalloc.c.
"""

from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import clang.cindex as ci

from .config import GEN, XV6, SrcFile, compile_args

CK = ci.CursorKind

REF_KINDS = {
    CK.DECL_REF_EXPR, CK.MEMBER_REF_EXPR, CK.TYPE_REF, CK.MACRO_INSTANTIATION,
    CK.LABEL_REF, CK.MEMBER_REF,
}

DECL_KIND_NAMES = {
    CK.FUNCTION_DECL: "function",
    CK.VAR_DECL: "variable",
    CK.PARM_DECL: "parameter",
    CK.FIELD_DECL: "field",
    CK.STRUCT_DECL: "struct",
    CK.UNION_DECL: "union",
    CK.ENUM_DECL: "enum",
    CK.ENUM_CONSTANT_DECL: "enumerator",
    CK.TYPEDEF_DECL: "typedef",
    CK.MACRO_DEFINITION: "macro",
    CK.LABEL_STMT: "label",
}


ALWAYS_DEF = {CK.MACRO_DEFINITION, CK.PARM_DECL, CK.FIELD_DECL, CK.LABEL_STMT,
              CK.ENUM_CONSTANT_DECL}


@dataclass(frozen=True)
class Decl:
    path: str
    line: int
    col: int
    name: str
    usr: str
    kind: str
    is_def: bool
    external: bool      # visible to other files at link time
    type: str
    group: str


@dataclass(frozen=True)
class Ref:
    path: str
    line: int
    col: int
    name: str
    usr: str
    group: str


def _relpath(fname: str) -> str | None:
    p = Path(fname)
    for base in (XV6, GEN):
        try:
            return p.resolve().relative_to(base).as_posix()
        except ValueError:
            pass
    return None


def _usr(c: ci.Cursor, path: str) -> str:
    u = c.get_usr()
    return u or f"loc:{path}:{c.location.line}:{c.location.column}"


def _kind(c: ci.Cursor) -> str:
    k = DECL_KIND_NAMES.get(c.kind, "")
    if c.kind == CK.VAR_DECL and c.semantic_parent and \
            c.semantic_parent.kind != CK.TRANSLATION_UNIT:
        k = "local"
    return k


def _type(c: ci.Cursor) -> str:
    if c.kind in (CK.MACRO_DEFINITION, CK.STRUCT_DECL, CK.UNION_DECL, CK.ENUM_DECL,
                  CK.LABEL_STMT):
        return ""
    t = c.underlying_typedef_type.spelling if c.kind == CK.TYPEDEF_DECL else c.type.spelling
    # clang names anonymous types by absolute path ("unnamed struct at /…/kernel/bio.c:25:1");
    # keep only the repository-relative part
    return t.replace(f"{XV6}/", "")


@dataclass(frozen=True)
class MacroRef:
    """A name used inside a #define body. libclang does not resolve these (the
    body is only text until the macro is expanded), so they are resolved by name."""
    path: str
    line: int
    col: int
    name: str
    group: str


@dataclass(frozen=True)
class FuncExtent:
    path: str
    name: str
    start: int      # first line of the function definition
    end: int        # last line


def _macro_body_refs(c: ci.Cursor, path: str, group: str) -> list[MacroRef]:
    toks = list(c.get_tokens())[1:]
    params: set[str] = set()
    # Function-like macro: "(" immediately follows the name, with no space.
    if toks and toks[0].spelling == "(" and \
            toks[0].location.column == c.location.column + len(c.spelling):
        for i, t in enumerate(toks):
            if t.spelling == ")":
                toks = toks[i + 1:]
                break
            if t.kind == ci.TokenKind.IDENTIFIER:
                params.add(t.spelling)
    return [MacroRef(path, t.location.line, t.location.column, t.spelling, group)
            for t in toks
            if t.kind == ci.TokenKind.IDENTIFIER and t.spelling not in params]


def index_tu(f: SrcFile):
    """Parse one .c file; return its declarations, references, macro-body
    references and errors."""
    index = ci.Index.create()
    tu = index.parse(str(f.disk), args=compile_args(f),
                     options=ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
    errors = [f"{d.location.file}:{d.location.line}: {d.spelling}"
              for d in tu.diagnostics if d.severity >= ci.Diagnostic.Error]

    lines_cache: dict[str, list[str]] = {}
    path_cache: dict[str, str | None] = {}

    def text_at(path: str, line: int, col: int, n: int) -> str:
        if path not in lines_cache:
            disk = (GEN / path) if (GEN / path).exists() else (XV6 / path)
            lines_cache[path] = disk.read_text().split("\n")
        lines = lines_cache[path]
        if line - 1 >= len(lines):
            return ""
        return lines[line - 1][col - 1:col - 1 + n]

    decls, refs, mrefs, extents = [], [], [], []
    for c in tu.cursor.walk_preorder():
        loc = c.location
        if loc.file is None:
            continue
        fname = loc.file.name
        if fname not in path_cache:
            path_cache[fname] = _relpath(fname)
        path = path_cache[fname]
        if path is None:
            continue

        if c.kind in DECL_KIND_NAMES:
            name = c.spelling
            # The cursor location must point at the name itself; anything else
            # (anonymous structs, names produced by macro expansion) is skipped.
            if not name or text_at(path, loc.line, loc.column, len(name)) != name:
                continue
            external = c.kind == CK.MACRO_DEFINITION or \
                c.linkage == ci.LinkageKind.EXTERNAL
            is_def = c.kind in ALWAYS_DEF or c.is_definition() or (
                # locals: "int i;" has no initializer but still defines i
                c.kind == CK.VAR_DECL and c.semantic_parent.kind != CK.TRANSLATION_UNIT
                and c.storage_class != ci.StorageClass.EXTERN) or (
                # "char stack0[N];" at file scope is a (tentative) definition
                c.kind == CK.VAR_DECL and c.storage_class != ci.StorageClass.EXTERN
                and c.semantic_parent.kind == CK.TRANSLATION_UNIT)
            decls.append(Decl(path, loc.line, loc.column, name, _usr(c, path), _kind(c),
                              is_def, external, _type(c), f.group))
            if c.kind == CK.MACRO_DEFINITION:
                mrefs += _macro_body_refs(c, path, f.group)
            if c.kind == CK.FUNCTION_DECL and c.is_definition():
                extents.append(FuncExtent(path, name, c.extent.start.line,
                                          c.extent.end.line))
        elif c.kind in REF_KINDS:
            target = c.referenced
            if target is None:
                continue
            name = c.spelling if c.kind in (CK.MACRO_INSTANTIATION, CK.MEMBER_REF_EXPR,
                                            CK.DECL_REF_EXPR) else target.spelling
            if not name or text_at(path, loc.line, loc.column, len(name)) != name:
                continue
            tloc = target.location
            tpath = _relpath(tloc.file.name) if tloc.file else None
            usr = target.get_usr() or (f"loc:{tpath}:{tloc.line}:{tloc.column}"
                                       if tpath else "")
            if usr:
                refs.append(Ref(path, loc.line, loc.column, name, usr, f.group))
    return decls, refs, mrefs, extents, errors


def index_all(files: list[SrcFile]):
    tus = [f for f in files if f.lang == "c"]
    with Pool() as pool:
        results = pool.map(index_tu, tus)
    decls, refs, mrefs, extents, errors = set(), set(), {}, set(), []
    for d, r, m, x, e in results:
        decls.update(d)
        refs.update(r)
        extents.update(x)
        for x in m:     # a header seen from several programs: keep the first
            mrefs.setdefault((x.path, x.line, x.col), x)
        errors += e
    key = lambda x: (x.path, x.line, x.col, x.usr, x.group)
    return (sorted(decls, key=key), sorted(refs, key=key),
            [mrefs[k] for k in sorted(mrefs)],
            sorted(extents, key=lambda x: (x.path, x.start)), errors)
