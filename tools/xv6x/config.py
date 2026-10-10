# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Jyotiprakash Mishra. Based on "xv6, line by line" by Jyotiprakash Mishra
# (https://xv6.jyotiprakash.org); see NOTICE for the attribution term (GPLv3 section 7(b)).
"""Paths, the list of files to publish, and how each file is compiled."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
XV6 = ROOT / "xv6"
BUILD = ROOT / "build"
GEN = BUILD / "gen"          # generated sources (e.g. user/usys.S)
SITE = ROOT / "site"
WEB = ROOT / "web"
ANNOTATIONS = ROOT / "annotations"

UPSTREAM = "https://github.com/mit-pdos/xv6-riscv"
COMMIT = "06aad25"

# Files compiled together into one program (one link "namespace").
#   kernel: kernel/*  (one big binary)
#   user:   user/*    (many binaries, all linked with ULIB)
#   mkfs:   mkfs/*    (a host program that runs on the build machine)
#   build:  Makefile
ULIB = {"user/ulib.c", "user/printf.c", "user/umalloc.c", "user/usys.S"}

# Files that are produced by the build but are worth reading.
GENERATED = {
    "user/usys.S": ("perl", ["perl", "user/usys.pl"]),
}

# Dotfiles that are pure editor/tooling settings; published, but listed last.
MINOR = {".clang-format", ".dir-locals.el", ".editorconfig", ".gitignore",
         ".github/workflows/test.yml", "LICENSE"}


@dataclass
class SrcFile:
    path: str            # repo-relative path, e.g. "kernel/vm.c"
    disk: Path           # where to read it from
    lang: str            # c, h, asm, ld, make, perl, python, yaml, gdb, elisp, text
    group: str | None    # kernel, user, mkfs, build, or None
    generated: bool = False
    lines: list[str] | None = None

    def text_lines(self) -> list[str]:
        if self.lines is None:
            self.lines = self.disk.read_text(encoding="utf-8").split("\n")
            if self.lines and self.lines[-1] == "":
                self.lines.pop()
        return self.lines


def lang_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    return {
        "c": "c", "h": "h", "S": "asm", "ld": "ld", "pl": "perl", "py": "python",
        "yml": "yaml", "el": "elisp", "tmpl-riscv": "gdb",
    }.get(ext, "make" if name == "Makefile" else "text")


def group_of(path: str) -> str | None:
    top = path.split("/", 1)[0]
    if top in ("kernel", "user", "mkfs"):
        return top
    if path == "Makefile":
        return "build"
    return None


def generate_sources() -> None:
    for path, (_, cmd) in GENERATED.items():
        out = GEN / path
        out.parent.mkdir(parents=True, exist_ok=True)
        text = subprocess.run(cmd, cwd=XV6, check=True, capture_output=True,
                              text=True).stdout
        if not out.exists() or out.read_text() != text:
            tmp = out.with_suffix(f".tmp{os.getpid()}")
            tmp.write_text(text)
            os.replace(tmp, out)    # atomic: concurrent runs never see a partial file


def source_files() -> list[SrcFile]:
    tracked = subprocess.run(["git", "ls-files"], cwd=XV6, check=True,
                             capture_output=True, text=True).stdout.split()
    files = [SrcFile(p, XV6 / p, lang_of(p), group_of(p)) for p in tracked]
    files += [SrcFile(p, GEN / p, lang_of(p), group_of(p), generated=True)
              for p in GENERATED]
    return sorted(files, key=lambda f: f.path)


def host_include_dirs() -> list[str]:
    """System include dirs of the host C compiler (needed to parse mkfs.c)."""
    r = subprocess.run(["cc", "-E", "-x", "c", "-", "-v"], input="", capture_output=True,
                       text=True)
    m = re.search(r"#include <...> search starts here:\n(.*?)End of search list",
                  r.stderr, re.S)
    if not m:
        return []
    return [d.strip().split(" (")[0] for d in m.group(1).splitlines() if d.strip()]


RISCV_ARGS = [
    "--target=riscv64-unknown-elf", "-march=rv64gc", "-mcmodel=medany", "-std=gnu99",
    "-ffreestanding", "-fno-common", "-nostdlib", "-fno-builtin",
    "-Wno-unknown-attributes",
]


def compile_args(f: SrcFile) -> list[str]:
    """Flags mirroring the Makefile's CFLAGS (see xv6/Makefile)."""
    if f.group == "mkfs":
        args = ["-std=gnu99", "-Wno-unknown-attributes"]
        for d in host_include_dirs():
            args += ["-isystem", d]
        try:
            sdk = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True,
                                 text=True).stdout.strip()
            if sdk:
                args += ["-isysroot", sdk]
        except FileNotFoundError:
            pass
    else:
        args = list(RISCV_ARGS) + ["-isystem", str(ROOT / "tools" / "shim")]
    return args + [f"-I{XV6}"]
