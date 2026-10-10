"""Run every indexer over every published file."""

from . import cindex, config, lexers
from .model import FileFacts, NRef
from .symbols import SymbolTable


def run(verbose: bool = True):
    config.generate_sources()
    files = config.source_files()
    paths = {f.path for f in files}
    exists = paths.__contains__

    decls, refs, mrefs, extents, errors = cindex.index_all(files)
    for e in errors:
        print("libclang error:", e)

    facts: dict[str, FileFacts] = {}
    flinks: dict[str, list] = {}
    for f in files:
        lines = f.text_lines()
        text = "\n".join(lines) + "\n"
        if f.lang == "asm":
            ff = lexers.scan_asm(f.path, f.group, lines)
        elif f.lang == "ld":
            ff = lexers.scan_ld(f.path, f.group, lines, exists)
        elif f.lang == "make":
            ff = lexers.scan_make(f.path, lines, exists)
        else:
            ff = FileFacts(toks=lexers.pygments_toks(f.lang, text))
            if f.lang in ("c", "h"):
                ff.toks += lexers.inline_asm_toks(lines)
            if f.path == "user/usys.pl":
                ff.refs += lexers.scan_usys_pl(f.path, lines).refs
        if f.lang in ("c", "h", "asm"):
            ff.flinks += lexers.include_links(f.path, lines, exists)
        facts[f.path] = ff
        flinks[f.path] = [l for l in ff.flinks if f.lang in ("c", "h", "asm")]

    for m in mrefs:
        facts[m.path].refs.append(NRef(m.path, m.line, m.col, m.name, m.group,
                                       ("macro", "cname")))

    table = SymbolTable()
    idents = {f.path: lexers.c_identifiers("\n".join(f.text_lines()) + "\n")
              for f in files if f.lang in ("c", "h")}
    table.build(decls, refs, facts, flinks, idents, extents)
    if verbose:
        nlinks = sum(len(v) for v in table.links.values())
        print(f"{len(files)} files, {len(table.syms)} symbols, {nlinks} linked occurrences")
    return files, facts, table
