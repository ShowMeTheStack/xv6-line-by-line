# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Jyotiprakash Mishra. Based on "xv6, line by line" by Jyotiprakash Mishra
# (https://xv6.jyotiprakash.org); see NOTICE for the attribution term (GPLv3 section 7(b)).
"""Guided tours: loading, validation and the data the renderer needs.

annotations/tours/NN-slug.yaml describes one tour:

    title: Life of a system call
    group: Traps and system calls
    summary: |                  # the opening screen (markdown)
    prerequisites: [2, 4]       # other tour numbers
    cast: |                     # optional: who is running where at the start
    steps:
      - title: printf calls write
        file: user/printf.c
        lines: 10-24            # the excerpt shown
        focus: 14-15            # optional: the lines highlighted inside it
        state:                  # the machine-state display for this step
          hart: 1               # a number, a list, or "any"
          mode: U               # M, S or U
          proc: sh (pid 2)
          intr: on              # on or off
          satp: user            # bare, kernel or user
          locks: []             # locks held right now, in acquisition order
          stack: [main, printf, putc, write]
          sp: user              # the stack sp points into right now (see STACKS):
                                #   user | kernel | scheduler | boot | none
                                # or a mapping {on: kernel, detail: "...", switched: "..."}
                                #   detail: shown after the label (e.g. an address)
                                #   switched: what just moved sp to this stack
          irq: {noff: 1, intena: 1}  # this hart's push_off depth and saved interrupt flag
                                # (see LOCKS): noff = mycpu()->noff, intena =
                                # mycpu()->intena (0 or 1; required when noff > 0).
                                # Shorthand `irq: 0`. Optional note: "why noff is what it is".
                                # Required on S-mode steps; U and M steps default to 0.
        note: |                 # the narrative (markdown, [[links]])
        others: |               # optional "Meanwhile, on other harts" box
        figure: three-stacks    # optional: annotations/figs/<name>.svg, shown above the note
        caption: ...            # optional figure caption (markdown, [[links]])
    locks:                      # closing summary table
      - lock: p->lock
        where: [[sched]]
        protects: ...
    quiz:
      - q: |
        a: |
"""

import re
from dataclasses import dataclass, field

import yaml

from .config import ANNOTATIONS, SrcFile

TOURS = ANNOTATIONS / "tours"

# The planned tours: number -> (slug, title, group). Tour files must be named
# annotations/tours/NN-<slug>.yaml; notes link to tours with [[tour:N]].
PLAN = {
    1: ("make-to-disk-image-and-kernel", "From make qemu to a disk image and a kernel", "Boot and build"),
    2: ("power-on-to-main", "Power-on to main, on every hart at once", "Boot and build"),
    3: ("main-one-hart-builds-the-kernel", "main: one hart builds the kernel, the others wait", "Boot and build"),
    4: ("first-process-to-shell-prompt", "From the first process to the shell prompt", "Boot and build"),
    5: ("life-of-a-system-call", "Life of a system call", "Traps and system calls"),
    6: ("system-call-arguments", "System-call arguments and user pointers", "Traps and system calls"),
    7: ("trampoline-and-trapframe", "The trampoline and the trapframe", "Traps and system calls"),
    8: ("traps-inside-the-kernel", "Traps taken inside the kernel", "Traps and system calls"),
    9: ("device-interrupts-and-the-plic", "Device interrupts and the PLIC", "Traps and system calls"),
    10: ("exceptions-and-faults", "Exceptions and faults", "Traps and system calls"),
    11: ("timer-tick-to-context-switch", "From a timer tick to a context switch", "Time and scheduling"),
    12: ("one-scheduler-per-hart", "One scheduler per hart", "Time and scheduling"),
    13: ("swtch-and-the-lock-handoff", "swtch and the lock handed across a context switch", "Time and scheduling"),
    14: ("pause-and-the-tick-counter", "pause(n) and the tick counter", "Time and scheduling"),
    15: ("spinlocks-from-the-hardware-up", "Spinlocks from the hardware up", "Concurrency primitives"),
    16: ("sleep-and-wakeup", "sleep and wakeup, and the lost-wakeup problem", "Concurrency primitives"),
    17: ("sleep-locks", "Sleep-locks", "Concurrency primitives"),
    18: ("lock-ordering", "Lock ordering: how xv6 avoids deadlock", "Concurrency primitives"),
    19: ("memory-ordering-across-harts", "Memory ordering across harts", "Concurrency primitives"),
    20: ("fork", "fork", "Processes"),
    21: ("exit-wait-and-zombies", "exit, wait and zombies", "Processes"),
    22: ("exec", "exec", "Processes"),
    23: ("kill", "kill", "Processes"),
    24: ("kernel-page-table-and-paging-on", "The kernel page table and turning paging on", "Memory"),
    25: ("a-user-address-space", "A user address space", "Memory"),
    26: ("sbrk-and-page-faults", "sbrk, eager and lazy, and page faults", "Memory"),
    27: ("physical-page-allocator", "The physical page allocator", "Memory"),
    28: ("copyin-and-copyout", "Crossing the user/kernel boundary in memory", "Memory"),
    29: ("a-disk-read-end-to-end", "A disk read, end to end", "File system"),
    30: ("the-buffer-cache", "The buffer cache", "File system"),
    31: ("the-log-and-group-commit", "The log: begin_op, commit and group commit", "File system"),
    32: ("crash-recovery", "Crash recovery", "File system"),
    33: ("the-life-of-an-inode", "The life of an inode", "File system"),
    34: ("path-lookup", "Path lookup", "File system"),
    35: ("creating-and-naming-files", "Creating and naming files", "File system"),
    36: ("reading-and-writing-a-file", "Reading and writing a file", "File system"),
    37: ("a-keystrokes-journey", "A keystroke's journey", "Devices and putting it all together"),
    38: ("console-output-from-three-harts", "Output to the console from three harts", "Devices and putting it all together"),
    39: ("pipes", "Pipes", "Devices and putting it all together"),
    40: ("capstone-ls-pipe-wc", "Capstone: the shell running ls | wc", "Devices and putting it all together"),
    41: ("every-transition", "Every transition: mode, stack and page table", "The dance of privilege"),
    42: ("one-harts-stacks", "One hart's stacks, from power-on to the first user instruction", "The dance of privilege"),
    43: ("a-system-call-csr-by-csr", "A system call, CSR by CSR", "The dance of privilege"),
    44: ("one-interrupt-three-landing-sites", "One interrupt, three landing sites", "The dance of privilege"),
    45: ("one-time-slice-on-three-harts", "One complete time slice on three harts", "The dance of privilege"),
    46: ("boot-a-return-that-never-happened", "Boot: returning from a trap that never happened", "The dance of privilege"),
    47: ("where-a-suspended-process-lives", "Where a suspended process lives", "The dance of privilege"),
    48: ("breaking-the-invariants", "Breaking the invariants", "The dance of privilege"),
    49: ("every-lock-in-one-pipeline", "Every lock in one ls | wc", "Locks and interrupt state"),
    50: ("noff-and-intena", "noff and intena through a sleep, a yield and an interrupt",
         "Locks and interrupt state"),
    51: ("the-lock-order-graph-measured", "The lock-order graph, measured", "Locks and interrupt state"),
    52: ("breaking-the-lock-rules", "Breaking the lock rules", "Locks and interrupt state"),
}


def plan_url(num: int) -> str:
    slug = PLAN[num][0]
    return f"tours/{num:02d}-{slug}.html"
MODES = {"M": "machine mode", "S": "supervisor mode", "U": "user mode"}
SATP = {"bare": "paging off", "kernel": "kernel page table", "user": "user page table"}
# The stacks a hart can be running on. "boot" and "scheduler" are the same memory
# (the hart's slice of stack0): main() never returns, it becomes the scheduler.
STACKS = {
    "user": "user stack",
    "kernel": "kernel stack",
    "scheduler": "scheduler stack",
    "boot": "boot stack",
    "none": "no usable stack",
}


def stack_state(st: dict) -> dict | None:
    """Normalize state.sp to {on, detail, switched}, or None if absent."""
    v = st.get("sp")
    if v is None:
        return None
    if isinstance(v, str):
        return {"on": v, "detail": "", "switched": ""}
    if isinstance(v, dict):
        # YAML 1.1 reads an unquoted `on:` key as the boolean True
        return {"on": str(v.get("on", v.get(True, ""))), "detail": str(v.get("detail") or ""),
                "switched": str(v.get("switched") or "")}
    return {"on": str(v), "detail": "", "switched": ""}


# Frames that can hold a push_off level without a spinlock being in state.locks:
# acquire before the swap succeeds, release after the store, myproc, uartputc_sync.
PUSHERS = {"acquire", "release", "push_off", "pop_off", "myproc", "uartputc_sync"}


def irq_state(st: dict) -> dict | None:
    """Normalize state.irq to {noff, intena, note, derived}, or None if not executing."""
    v = st.get("irq")
    if v is None:
        if st.get("mode") in ("U", "M"):
            return {"noff": 0, "intena": None, "note": "", "derived": True}
        return None
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return {"noff": v, "intena": None, "note": "", "derived": False}
    if isinstance(v, dict):
        ie = v.get("intena")
        if isinstance(ie, bool):
            ie = int(ie)
        try:
            noff = int(v.get("noff"))
        except (TypeError, ValueError):
            noff = -1
        return {"noff": noff, "intena": ie, "note": str(v.get("note") or ""), "derived": False}
    return {"noff": -1, "intena": None, "note": "", "derived": False}


def is_sleeplock(name: str) -> bool:
    n = str(name).lower()
    return ("sleep-lock" in n or "sleep lock" in n or "sleeplock" in n) and "(spinlock)" not in n


def irq_problems(st: dict) -> list[str]:
    """Consistency rules between irq, intr, locks and the call stack."""
    out = []
    irq = irq_state(st)
    mode = st.get("mode")
    if irq is None:
        if mode == "S":
            out.append("S-mode step has no irq (noff/intena)")
        return out
    noff, ie = irq["noff"], irq["intena"]
    if not 0 <= noff <= 8:
        out.append("irq.noff must be an integer 0-8")
        return out
    if ie not in (None, 0, 1):
        out.append("irq.intena must be 0 or 1")
    if noff > 0 and ie is None:
        out.append("irq: noff > 0 needs intena (0 or 1)")
    if mode == "U" and noff:
        out.append("irq: user code runs with noff 0")
    intr = st.get("intr")
    if noff > 0 and intr in ("on", True):
        out.append("irq: noff > 0 but interrupts on (push_off always leaves SIE clear)")
    spins = sum(1 for x in st.get("locks") or [] if not is_sleeplock(x))
    stack = [str(x) for x in st.get("stack") or []]
    extra = sum(1 for x in stack if x in PUSHERS)
    if mode == "S" and not irq["note"]:
        if noff < spins:
            out.append(f"irq: noff {noff} < {spins} spinlock(s) in locks")
        elif noff > spins + extra:
            out.append(f"irq: noff {noff} > {spins} spinlock(s) + {extra} push_off frame(s); "
                       "add irq.note saying why")
    if mode == "S" and ("sched" in stack or "swtch" in stack) and noff != 1 and not irq["note"]:
        out.append("irq: sched/swtch always run with noff == 1")
    return out


@dataclass
class Step:
    title: str
    file: str
    a: int
    b: int
    fa: int
    fb: int
    state: dict
    note: str
    others: str
    figure: str = ""
    caption: str = ""


@dataclass
class Tour:
    num: int
    slug: str
    title: str
    group: str
    summary: str
    prerequisites: list[int]
    cast: str
    steps: list[Step]
    locks: list[dict]
    quiz: list[dict]
    problems: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"tours/{self.num:02d}-{self.slug}.html"


def _range(v) -> tuple[int, int]:
    if isinstance(v, int):
        return v, v
    a, _, b = str(v).partition("-")
    return int(a), int(b or a)


def load(files: list[SrcFile]) -> list[Tour]:
    by_path = {f.path: f for f in files}
    tours = []
    for p in sorted(TOURS.glob("*.yaml")) if TOURS.exists() else []:
        m = re.fullmatch(r"(\d+)-([\w-]+)\.yaml", p.name)
        if not m:
            continue
        probs: list[str] = []
        try:
            raw = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError as e:
            tours.append(Tour(int(m.group(1)), m.group(2), p.name, "", "", [], "", [], [],
                              [], [f"YAML error: {e}"]))
            continue
        steps = []
        for i, s in enumerate(raw.get("steps") or [], 1):
            where = f"step {i}"
            path = s.get("file", "")
            f = by_path.get(path)
            if f is None:
                probs.append(f"{where}: unknown file {path!r}")
                continue
            try:
                a, b = _range(s.get("lines"))
                fa, fb = _range(s["focus"]) if s.get("focus") else (a, b)
            except (TypeError, ValueError):
                probs.append(f"{where}: bad lines/focus {s.get('lines')!r}/{s.get('focus')!r}")
                continue
            n = len(f.text_lines())
            if not (1 <= a <= b <= n) or not (a <= fa <= fb <= b):
                probs.append(f"{where}: lines {a}-{b} / focus {fa}-{fb} out of range "
                             f"({path} has {n} lines)")
                continue
            if b - a > 80:
                probs.append(f"{where}: excerpt of {b - a + 1} lines is too long (max 81)")
            st = s.get("state") or {}
            if st.get("mode") and st["mode"] not in MODES:
                probs.append(f"{where}: mode must be M, S or U")
            if st.get("satp") and st["satp"] not in SATP:
                probs.append(f"{where}: satp must be bare, kernel or user")
            sps = stack_state(st)
            if sps is not None and sps["on"] not in STACKS:
                probs.append(f"{where}: sp must be one of {', '.join(STACKS)}")
            if st.get("intr") not in (None, "on", "off", True, False):
                probs.append(f"{where}: intr must be on or off")
            probs += [f"{where}: {x}" for x in irq_problems(st)]
            if not s.get("title") or not s.get("note"):
                probs.append(f"{where}: needs a title and a note")
            steps.append(Step(s.get("title", ""), path, a, b, fa, fb, st,
                              (s.get("note") or "").strip(), (s.get("others") or "").strip(),
                              str(s.get("figure") or ""), str(s.get("caption") or "")))
        t = Tour(int(m.group(1)), m.group(2), raw.get("title", m.group(2)),
                 raw.get("group", ""), (raw.get("summary") or "").strip(),
                 [int(x) for x in raw.get("prerequisites") or []],
                 (raw.get("cast") or "").strip(), steps, raw.get("locks") or [],
                 raw.get("quiz") or [], probs)
        if not t.summary:
            probs.append("missing summary")
        if not steps:
            probs.append("no steps")
        tours.append(t)
    nums = {t.num for t in tours}
    for t in tours:
        if t.num in PLAN and PLAN[t.num][0] != t.slug:
            t.problems.append(f"file name slug {t.slug!r} should be {PLAN[t.num][0]!r}")
        for q in t.prerequisites:
            if q not in PLAN:
                t.problems.append(f"prerequisite tour {q} is not in the plan")
            elif q not in nums:
                t.problems.append(f"prerequisite tour {q} does not exist (yet)")
    return sorted(tours, key=lambda t: t.num)


def line_index(tours: list[Tour]) -> dict[str, dict[int, list[tuple[int, int, str]]]]:
    """path -> line -> [(tour number, step number, step title)] for focus lines."""
    out: dict[str, dict[int, list]] = {}
    for t in tours:
        for i, s in enumerate(t.steps, 1):
            for n in range(s.fa, s.fb + 1):
                out.setdefault(s.file, {}).setdefault(n, []).append((t.num, i, s.title))
    return out
