"""Extension labs: build-it-yourself extensions of xv6, one git branch each.

annotations/labs/NN-slug.yaml describes one lab; its reference solution is the branch
`ext/NN-slug` in the clone extensions/xv6, branched from the frozen commit. Every commit
on the branch is one step of the reveal (commit messages are the step titles' source of
truth for "what this commit does").

    published: true              # shown on the site only when set
    title: Copy-on-write fork
    area: Memory                 # one of AREAS
    stars: 4                     # 1-5
    branch: ext/11-cow
    prerequisites: {tours: [20, 25], concepts: [stacks]}
    summary: |                   # one paragraph for the index card and the overview
    learn: [ ... ]               # bullets: what this teaches about the internals
    spec: |                      # what to build, observable behaviour, the test to pass
    think:                       # design questions to answer before seeing code
      - title: Where is a write to a shared page caught?
        q: |
        hints: [hint 1, hint 2, hint 3]      # progressively more specific (1-3)
        answer: |                            # the reference design's answer
        checks: [ ...question objects, same schema as annotations/questions ... ]
    build: |                     # how to start (git commands), milestones, testing advice
    clinic:                      # real bugs: change made, real symptom, why
      - bug: Forgot to lock the reference count
        change: |                # what was broken (markdown, may include a diff block)
        symptom: |               # what actually happened, from a recorded run
        why: |
    reveal:                      # the guided tour through the reference branch
      - title: ...
        commit: 1                # 1-based index into the branch's commits after the base
        file: kernel/vm.c        # file as of that commit
        lines: 300-340           # excerpt (of the file at that commit)
        focus: 310-320           # optional
        diff: true               # optional: show this commit's diff for the file too
        state: {...}             # same machine-state fields as tour steps
        note: |
        others: |
    verify: |                    # real test output and what it shows
    measure: |                   # optional: measurements (real numbers)
    further: |                   # stretch goals
"""

import re
import subprocess
from dataclasses import dataclass, field

import yaml

from .config import ANNOTATIONS, ROOT

LABS = ANNOTATIONS / "labs"
EXT = ROOT / "extensions" / "xv6"
BASE = "06aad25"
# the public repository holding the ext/ reference branches
LABS_REPO = "https://github.com/ShowMeTheStack/xv6-riscv-labs"
AREAS = ["The system-call and trap path", "Traps and control flow", "Scheduling", "Memory",
         "Concurrency", "File system", "Devices"]

# The planned labs: number -> (slug, title, area, stars)
PLAN = {
    1: ("trace", "trace: logging system calls", "The system-call and trap path", 1),
    2: ("backtrace", "A kernel backtrace on panic", "The system-call and trap path", 1),
    3: ("procinfo", "ps: a safe snapshot of the process table", "The system-call and trap path", 2),
    4: ("cputime", "CPU time accounting and a time command", "The system-call and trap path", 2),
    5: ("sigalarm", "sigalarm and sigreturn: calling a user handler from a timer", "Traps and control flow", 3),
    6: ("ctrl-c", "Ctrl-C: interrupting the foreground job", "Traps and control flow", 3),
    7: ("profiler", "A sampling profiler", "Traps and control flow", 2),
    8: ("stride", "Stride scheduling with nice", "Scheduling", 3),
    9: ("threads", "User threads: clone, join and futex", "Scheduling", 5),
    10: ("vdso", "A shared read-only page: system calls without a trap", "Memory", 2),
    11: ("cow", "Copy-on-write fork", "Memory", 4),
    12: ("demand-exec", "Demand-paged exec", "Memory", 4),
    13: ("growstack", "A growable user stack", "Memory", 3),
    14: ("superpages", "Superpages", "Memory", 4),
    15: ("mmap", "mmap and munmap of files", "Memory", 5),
    16: ("swap", "Swapping to disk", "Memory", 5),
    17: ("sum", "Direct user access with sstatus.SUM", "Memory", 3),
    18: ("percpu-kalloc", "Per-CPU free lists in kalloc", "Concurrency", 3),
    19: ("bcache-hash", "A hashed buffer cache", "Concurrency", 4),
    20: ("ticketlock", "Ticket spinlocks", "Concurrency", 2),
    21: ("lockdep", "Lockdep-lite: a runtime lock-order checker", "Concurrency", 4),
    22: ("bigfile", "Doubly-indirect blocks: large files", "File system", 2),
    23: ("symlink", "Symbolic links", "File system", 3),
    24: ("rename", "Atomic rename", "File system", 4),
    25: ("e1000", "An e1000 network driver and UDP sockets", "Devices", 5),
}


def branch_name(num: int) -> str:
    return f"ext/{num:02d}-{PLAN[num][0]}"


def git(*args) -> str:
    return subprocess.run(["git", "-C", str(EXT), *args], capture_output=True, text=True,
                          check=True).stdout


def commits(branch: str) -> list[tuple[str, str]]:
    """[(sha, subject)] for the branch's commits after BASE, oldest first."""
    out = git("log", "--reverse", "--format=%H%x09%s", f"{BASE}..{branch}")
    return [tuple(l.split("\t", 1)) for l in out.splitlines() if l.strip()]


def file_at(sha: str, path: str) -> str | None:
    try:
        return git("show", f"{sha}:{path}")
    except subprocess.CalledProcessError:
        return None


def diff_of(sha: str, path: str) -> str:
    return git("show", "--format=", "-U4", sha, "--", path)


@dataclass
class Lab:
    num: int
    slug: str
    raw: dict
    commits: list = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"labs/{self.num:02d}-{self.slug}.html"

    @property
    def reveal_url(self) -> str:
        return f"labs/{self.num:02d}-{self.slug}-reveal.html"

    def get(self, k, d=None):
        return self.raw.get(k, d)


def _range(v) -> tuple[int, int]:
    if isinstance(v, int):
        return v, v
    a, _, b = str(v).partition("-")
    return int(a), int(b or a)


def load(files) -> list[Lab]:
    from .questions import validate as qvalidate
    from .tours import irq_problems, stack_state, STACKS
    by_path = {f.path: f for f in files}
    labs = []
    for p in sorted(LABS.glob("*.yaml")) if LABS.exists() else []:
        m = re.fullmatch(r"(\d+)-([\w-]+)\.yaml", p.name)
        if not m:
            continue
        num, slug = int(m.group(1)), m.group(2)
        probs: list[str] = []
        try:
            raw = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError as e:
            labs.append(Lab(num, slug, {}, [], [f"YAML: {e}"]))
            continue
        lab = Lab(num, slug, raw, [], probs)
        if num not in PLAN or PLAN[num][0] != slug:
            probs.append(f"file name should be {num:02d}-{PLAN.get(num, ('?',))[0]}.yaml")
        for k in ("title", "summary", "spec", "think", "build", "clinic", "reveal", "verify"):
            if not raw.get(k):
                probs.append(f"missing `{k}`")
        if raw.get("area") not in AREAS:
            probs.append(f"area must be one of {AREAS}")
        br = raw.get("branch") or (branch_name(num) if num in PLAN else "")
        try:
            lab.commits = commits(br)
        except subprocess.CalledProcessError:
            probs.append(f"branch {br} not found in extensions/xv6")
        if lab.commits is not None and not lab.commits and not probs:
            probs.append(f"branch {br} has no commits after {BASE}")
        for i, t in enumerate(raw.get("think") or [], 1):
            hs = t.get("hints") or []
            if not t.get("q") or not t.get("answer") or not 1 <= len(hs) <= 3:
                probs.append(f"think {i}: needs q, answer and 1-3 hints")
            for j, q in enumerate(t.get("checks") or [], 1):
                probs += qvalidate(q, f"think {i} check {j}", by_path)
        for i, c in enumerate(raw.get("clinic") or [], 1):
            for k in ("bug", "change", "symptom", "why"):
                if not c.get(k):
                    probs.append(f"clinic {i}: needs `{k}`")
        for i, s in enumerate(raw.get("reveal") or [], 1):
            where = f"reveal step {i}"
            ci = s.get("commit")
            if not isinstance(ci, int) or not lab.commits or not 1 <= ci <= len(lab.commits):
                probs.append(f"{where}: commit must be 1..{len(lab.commits)}")
                continue
            sha = lab.commits[ci - 1][0]
            text = file_at(sha, s.get("file", ""))
            if text is None:
                probs.append(f"{where}: {s.get('file')} does not exist at commit {ci}")
                continue
            n = len(text.splitlines())
            try:
                a, b = _range(s.get("lines"))
                fa, fb = _range(s["focus"]) if s.get("focus") else (a, b)
            except (TypeError, ValueError):
                probs.append(f"{where}: bad lines/focus")
                continue
            if not (1 <= a <= b <= n) or not (a <= fa <= fb <= b) or b - a > 80:
                probs.append(f"{where}: lines {a}-{b}/focus {fa}-{fb} invalid ({n} lines, max 81)")
            if not s.get("title") or not s.get("note"):
                probs.append(f"{where}: needs title and note")
            st = s.get("state") or {}
            sps = stack_state(st)
            if st.get("mode") and sps is None:
                probs.append(f"{where}: has a mode but no sp")
            if sps and sps["on"] not in STACKS:
                probs.append(f"{where}: bad sp")
            probs += [f"{where}: {x}" for x in irq_problems(st)]
            if s.get("diff") and not diff_of(sha, s["file"]).strip():
                probs.append(f"{where}: diff: true but commit {ci} does not change {s['file']}")
        labs.append(lab)
    return sorted(labs, key=lambda l: l.num)
