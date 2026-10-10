"""Plain data shared by the indexers, the symbol table and the renderer."""

from dataclasses import dataclass, field


@dataclass
class Tok:
    """A highlighted range on one line (0-based, end-exclusive columns)."""
    line: int
    c0: int
    c1: int
    cls: str
    gloss: str = ""     # glossary key, e.g. "insn:csrw", "csr:satp", "reg:a0"


@dataclass
class NDef:
    """A definition found by a non-C indexer (asm label, linker symbol, ...)."""
    ns: str             # asm, ld, section, makevar, maketarget
    group: str
    name: str
    path: str
    line: int
    col: int            # 1-based, like libclang
    kind: str
    role: str = "def"   # def, or "assign" for later Makefile assignments


@dataclass
class NRef:
    """A use of a name, to be resolved by trying namespaces in order."""
    path: str
    line: int
    col: int
    name: str
    group: str
    lookup: tuple[str, ...]     # e.g. ("asm", "cext", "macro")
    role: str = "ref"           # ref, or "decl" (.globl / .global)
    width: int = 0              # characters to link, when not len(name)


@dataclass
class FLink:
    """A range that links to another file (an #include, an object file, ...)."""
    path: str
    line: int
    c0: int
    c1: int
    target: str
    title: str = ""


@dataclass
class FileFacts:
    toks: list[Tok] = field(default_factory=list)
    defs: list[NDef] = field(default_factory=list)
    refs: list[NRef] = field(default_factory=list)
    flinks: list[FLink] = field(default_factory=list)
