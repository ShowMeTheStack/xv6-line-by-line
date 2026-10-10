# xv6, line by line

**Every line of a real operating system, explained. Every claim checked against the running kernel.**

**Read it:** <https://xv6.jyotiprakash.org>

*xv6, line by line* is a complete, interactive companion to
[xv6-riscv](https://github.com/mit-pdos/xv6-riscv), MIT's teaching operating system for
RISC-V. It takes all 83 source files of the kernel, the user programs, the file-system
builder and the build system, pinned at upstream commit `06aad25`, and turns them into a
website where nothing is left unexplained. Every line is annotated. Every identifier is
cross-referenced. Every guided tour carries the machine's state at each step. Every
statement about what the kernel does was checked against xv6 itself, running on QEMU.

It was designed, written and directed by **Jyotiprakash Mishra**, as the companion to his
book *RISC-V Architecture and XV6: Instruction Set Architecture, Systems Programming, and
Kernel Development* (De Gruyter Brill, 2026).

---

## What is in it

### All of xv6, annotated line by line

| | |
|---|---|
| Source files | **83**, every one of them, nothing skipped |
| Lines of source | **13,249**, every line covered by an annotation |
| Named symbols cross-referenced | **2,457**: functions, structs, fields, macros, assembly labels, linker symbols, Makefile variables |
| Glossary terms | **229**, underlined wherever they appear |

Hover over any name to see what it is and where it is defined; click to jump to the
definition; open the symbol panel to see every use, across C, RISC-V assembly, linker
scripts and the Makefile. Click any line to read its notes, or press **Start reading** and
walk through a file one note at a time.

### 52 guided tours, 1,009 steps

Tours follow one path through the kernel from start to finish, across files, the way the
CPU actually executes it: from `make` to a bootable disk image, from power-on to `main`,
from the first process to the shell prompt, a system call from `ecall` to `sret`, a page
fault, a context switch, the timer interrupt, `fork`, `exec`, `pipe`, the buffer cache,
crash recovery in the log, memory ordering across harts, and many more.

Every step shows the code **and the state of the machine at that moment**:

- which hart is running and which process;
- privilege mode, the active stack and the active page table, drawn as a **stack strip**;
- whether interrupts are on, how deep the `push_off` nesting is, and what `intena`
  will restore, drawn as an **interrupt-state strip** (982 of them across the tours);
- which locks are held, with **lock badges** in the gutter of the code.

The machine states were recorded from xv6 running under gdb, not imagined.

### Three concept pages

Long-form explanations of the three ideas students find hardest, with original figures:

- **Stacks**: the user stack, the per-process kernel stack, the per-hart boot stacks, and
  how a trap moves between them.
- **Mode, stack and page table**: the three things that change together on every trap,
  and the trampoline that makes the switch possible.
- **Locks**: spinlocks, sleep-locks, `push_off`/`pop_off`, lock ordering and every lock in
  xv6, with the rules each one enforces.

### Test yourself: 500 questions

**500 auto-graded questions in 20 categories**, from the boot sequence to the file system,
in nine question types: multiple choice, multiple answer, true or false, compute the
number, put the steps in order, click the line of code, fill in the machine state, decode
the bits of a register or PTE, and match the pairs. Every answer
comes with an explanation that links back into the annotated source. Take a whole
category, or a quick ten.

### 25 extension labs

Twenty-five build-it-yourself extensions of xv6, from a one-star warm-up to five-star
projects, each with a complete reference implementation as its own git branch:

| Area | Labs |
|---|---|
| The system-call and trap path | `trace` · a kernel backtrace on panic · `ps` · CPU time accounting and `time` |
| Traps and control flow | `sigalarm`/`sigreturn` · Ctrl-C and process groups · a sampling profiler |
| Scheduling | stride scheduling with `nice` · user threads: `clone`, `join` and futexes |
| Memory | a shared read-only page (vDSO) · copy-on-write fork · demand-paged exec · a growable stack · superpages · `mmap`/`munmap` · swapping to disk · direct user access with `sstatus.SUM` |
| Concurrency | per-CPU free lists · a hashed buffer cache · ticket spinlocks · lockdep-lite, a runtime lock-order checker |
| File system | doubly-indirect blocks · symbolic links · atomic `rename` |
| Devices | an e1000 network driver and UDP sockets |

Every lab follows the same seven phases:

1. **The spec**: what to build and the observable behaviour that proves it works.
2. **Think first**: design questions to answer before writing code, with progressive
   hints and 305 self-checks.
3. **Build it**: milestones, each testable on its own.
4. **Debugging clinic**: 142 real bugs, each built into the reference on purpose, with the
   exact symptom it produced on QEMU (panics, hangs, wrong output, gdb backtraces) and why.
5. **The reference solution**: a guided reveal of the branch, commit by commit, 435 steps,
   with the machine state at each one.
6. **Verify and measure**: real test output, and real measurements.
7. **Go further**: stretch goals.

Together the labs add about 13,600 lines of kernel and user code in 190 commits. Each
commit is one teaching step. Every reference solution passes its own test program and
xv6's full `usertests` on three harts, and was attacked with adversarial programs that
look for crafted-input panics, leaks and races.

The reference branches live in
[ShowMeTheStack/xv6-riscv-labs](https://github.com/ShowMeTheStack/xv6-riscv-labs), one
branch per lab (`ext/01-trace` … `ext/25-e1000`), each starting from the same frozen
commit `06aad25`.

---

## Using the labs

```sh
git clone https://github.com/ShowMeTheStack/xv6-riscv-labs
cd xv6-riscv-labs
git checkout -b my-cow 06aad25        # start your own solution from the frozen commit
make qemu                             # build and boot xv6
git diff 06aad25 origin/ext/11-cow    # only when you want to see the reference
```

You need a RISC-V cross toolchain and QEMU with `qemu-system-riscv64`. xv6's Makefile
finds the toolchain prefix by itself (`riscv64-unknown-elf-`, `riscv64-linux-gnu-` or
`riscv64-elf-`); set `TOOLPREFIX` if yours is elsewhere. Linux, macOS and WSL all work.

---

## Building the site

The site is a static website generated from the pristine xv6 sources and the annotation
files in this repository.

```sh
git clone --recurse-submodules https://github.com/ShowMeTheStack/xv6-line-by-line
cd xv6-line-by-line
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# the lab pages are generated from the reference branches
git clone --no-checkout https://github.com/ShowMeTheStack/xv6-riscv-labs extensions/xv6
git -C extensions/xv6 fetch origin '+refs/heads/ext/*:refs/heads/ext/*'

python tools/build.py                 # writes the site into site/
python -m http.server -d site 8000    # then open http://localhost:8000
```

A push to `main` builds and deploys the site to GitHub Pages
(`.github/workflows/pages.yml`).

### How it works

| Path | What |
|---|---|
| `xv6/` | Upstream xv6-riscv as a git submodule, pinned at `06aad25` and never edited |
| `annotations/` | The content: one YAML file per source file (line annotations), the tours, the concept pages, the glossary, the question bank and the labs |
| `tools/build.py` | Builds the whole site into `site/` |
| `tools/annot.py` | Validates the content: every line covered, every link resolves, every question well formed, every lab step pointing at real lines of a real commit |
| `tools/xv6x/` | The generator: libclang for C, hand-written scanners for RISC-V assembly, linker scripts, the Makefile and `usys.pl`; the renderers for files, tours, concepts, questions and labs |
| `tools/shim/` | A minimal `stdarg.h` so libclang can parse xv6 without a RISC-V compiler |
| `web/` | The browser side: hover cards, go-to-definition, references panel, search, the tour player, the quiz engine, light and dark themes |

Annotations refer to code by symbol and line (`[[kfork]]`, `[[kernel/proc.c:294]]`), and
the validator re-checks every reference against the pinned sources, so the text cannot
drift away from the code.

---

## Author

**Jyotiprakash Mishra**, Assistant Professor of Computer Science at KIIT, co-founder and
CEO of ENineHQ Technologies, and PhD candidate at BITS Pilani (thesis on side-channel
security in open-source RISC-V processors). Formerly a Team Lead at Epic Systems and a
Senior Member of Technical Staff at Oracle; MS in Computer Science from the University of
Wisconsin–Madison, where he was the teaching assistant for *Introduction to Operating
Systems*.

- Blog: <https://blog.jyotiprakash.org>
- More teaching tools: [µSystem 8086](https://8086.jyotiprakash.org), a cycle-accurate
  8086/8088 system simulator. In closed testing: PipeLens (pipelines, caches and coherence
  in one simulator), NetSim (networks) and Compy (a C89 compiler opened up).
- Contact: <mail@jyotiprakash.org>

## xv6

xv6 is developed by Frans Kaashoek, Robert Morris and Russ Cox at MIT
([mit-pdos/xv6-riscv](https://github.com/mit-pdos/xv6-riscv)) and is distributed under the
MIT license; see `xv6/LICENSE`. This project includes it unmodified as a submodule.
