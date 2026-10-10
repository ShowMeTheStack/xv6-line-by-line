---
title: "Locks and interrupt state"
summary: Why three harts need locks, how a spinlock works down to the instruction, how xv6 keeps interrupts off while one is held, how a lock crosses a context switch, and every lock in the kernel, with its measured order and nesting.
---
xv6 runs on three [[g:hart|harts]] at once, all reading and writing the same kernel memory. A
lock is how the kernel says "only one hart at a time in here". This page explains the two kinds
of lock in this tree, the [[g:spinlock]] and the [[g:sleeplock|sleep-lock]], and the per-hart
interrupt state that comes with every spinlock. Three words run through it and through every
tour step's strip: **SIE**, the interrupt-enable bit of [[g:csr:sstatus|sstatus]] (`intr:
on/off`); **noff**, how many [[push_off]] calls this hart has not undone; and **intena**,
whether SIE was on just before the outermost `push_off`.

## Why locks: three harts, one free list {#why}

Take [[kalloc]] without its lock. Its core is three memory operations:

```c
r = kmem.freelist;            // load the first free page
if (r)
  kmem.freelist = r->next;    // load its next pointer, store it as the new head
```

Each line is fine on one hart. On three harts the loads and stores interleave. Here is one
possible interleaving, with the free list starting as `P1 → P2 → P3` and hart 2 freeing a page
`P9` with [[kfree]] at the same moment:

| time | hart 0: `kalloc` | hart 1: `kalloc` | hart 2: `kfree(P9)` | `kmem.freelist` |
|---|---|---|---|---|
| 1 | `r = freelist` → P1 | | | P1 |
| 2 | | `r = freelist` → P1 | | P1 |
| 3 | | | `P9->next = freelist` (P1) | P1 |
| 4 | `freelist = P1->next` (P2) | | | P2 |
| 5 | | | `freelist = P9` | P9 |
| 6 | | `freelist = P1->next` (P2) | | P2 |

Hart 0 and hart 1 both return `P1`: two page tables now share one page, and each process can
scribble over the other's memory. Hart 2's `P9` was linked in at step 5 and unlinked by
hart 1's stale store at step 6: that page is lost for good. Nothing crashes at the time. This
is a [[g:race-condition]]: the result depends on timing, the code usually works, and when it
fails the damage shows up much later.

The cure is to make the three operations a [[g:critical-section]] that only one hart can be
in at a time. That is what [[acquire]]`(&kmem.lock)` and [[release]]`(&kmem.lock)` around
them do ([[kernel/kalloc.c:73]], [[kernel/kalloc.c:77]]). A lock protects *data*, not code:
[[kfree]] takes the same lock ([[kernel/kalloc.c:59]]), and so must every other piece of code
that touches `kmem.freelist`.

The obvious lock, `while (lk->locked) ; lk->locked = 1;`, fails the same way: two harts can
both read 0 before either stores 1. Testing and setting must be one indivisible step, which only
the hardware can provide.

## The spinlock, step by step {#spinlock}

A spinlock is three fields ([[kernel/spinlock.h]]): `locked` (0 free, 1 held), `name` (for
debugging) and `cpu`, the hart that holds it. At offsets 0, 8 and 16, 24 bytes in all.
[[acquire]] ([[kernel/spinlock.c:22-42]]) does four things, in this order:

1. [[push_off]] (line 24): turn interrupts off on this hart and count one more level.
   [Below](#noff) explains why this comes first.
2. [[holding]] (lines 25–26): if this hart already holds `lk`, [[panic]] with `acquire`.
3. Spin on an atomic swap until it returns 0 (lines 37–38).
4. `lk->cpu = mycpu()` (line 41): record the owner.

[[release]] ([[kernel/spinlock.c:46-76]]) is the mirror image: check with [[holding]] (panic
`release` if this hart is not the owner), clear `lk->cpu`, store 0 into `locked` with release
ordering, and finally [[pop_off]].

### The atomic swap {#amoswap}

Line 37 is `__atomic_exchange_n(&lk->locked, 1, __ATOMIC_ACQUIRE)`. GCC turns it into a
single instruction from the RISC-V "A" (atomic) extension. In `kernel/kernel.asm` (trimmed: the
`holding` panic branch at `0x80000c00` is left out):

```text
80000bfe:  li     a4,1
80000c02:  mv     a5,a4
80000c04:  amoswap.w.aq  a5,a5,(s1)   # a5 = old lk->locked; lk->locked = 1, as one step
80000c08:  sext.w a5,a5
80000c0a:  bnez   a5,80000c02         # old value was 1: someone holds it, try again
```

[[g:insn:amoswap|amoswap.w]] reads the 32-bit word at the address in `s1` (here `lk`, whose
first field is `locked`), writes `a5` (1) there, and puts the old value in `a5`. No other hart
can read or write that word between the read and the write. So:

* old value 0: the lock was free, and this hart's 1 took it;
* old value 1: another hart holds it; writing 1 over 1 changed nothing. Loop.

If three harts swap at the same instant, the memory system puts the three swaps in some order.
Exactly one of them sees 0.

{{fig:locks-amoswap-race|Three harts racing for one lock word. Each `amoswap.w.aq` writes 1 and returns the old value; only the swap that finds 0 wins. The holder frees the lock with `fence rw,w` and a plain `sw zero`; the next swap to arrive, from whichever hart, wins it. The order of the harts is illustrative.}}

Notice what the loop does while it waits: *every* iteration is an atomic write, even when the
lock is plainly held. This is a plain swap loop, not the "test-and-test-and-set" loop that
production kernels use (spin on ordinary loads until the word reads 0, and only then try the
swap). On real multi-core hardware a write needs exclusive ownership of the cache line, so
spinning harts keep pulling the line away from each other and from the holder, whose release
store then has to fetch it back. xv6 keeps the simplest correct loop. The spinning hart has
interrupts off and does nothing else until the lock is free, which is why spinlocks are held
only briefly.

### Releasing: a fence and a store {#fence}

Line 73 frees the lock with `__atomic_store_n(&lk->locked, 0, __ATOMIC_RELEASE)`, which
compiles to two instructions:

```text
80000c82:  sd     zero,16(s1)     # lk->cpu = 0 (line 51)
80000c86:  fence  rw,w
80000c8a:  sw     zero,0(s1)      # lk->locked = 0
```

Why not `lk->locked = 0;`? Two reasons, both about other harts.

* **Ordering.** RISC-V's memory model, RVWMO, lets other harts see a hart's loads and stores
  to *different* addresses out of program order, and the compiler may reorder them too. The
  next owner could then see `locked == 0` before the critical section's last writes. The
  [[g:insn:fence|fence rw,w]] orders every earlier read (`r`) and write (`w`) of this hart
  before every later write, the freeing `sw` included; `__ATOMIC_RELEASE` also stops the
  compiler moving accesses below the store.
* **Atomicity.** The C standard does not promise that an assignment is a single store. The
  atomic built-in does (on RISC-V, one `sw`), so no hart can see a half-written value.

The acquire side needs the opposite guarantee: no access of the critical section may happen
*before* the lock is held. That is the `.aq` bit on the swap: no later load or store of this
hart is observed by others before the `amoswap`. Together, `.aq` on the way in and the fence on
the way out keep every access to the protected data inside the lock. See
[[g:memory-barrier]] and [the RISC-V section](#riscv).

Line 51 clears `lk->cpu` *before* the store. In the other order, another hart could take the
lock and record itself in `cpu` in between, and this hart's late `lk->cpu = 0` would erase the
new owner.

### holding() and lk->cpu {#holding}

[[holding]] ([[kernel/spinlock.c:80-86]]) answers "does *this hart* hold `lk`?":
`lk->locked && lk->cpu == mycpu()`. Three things to notice.

* **It names a hart, not a process or a thread.** `lk->cpu` is a `struct cpu *`. That choice is
  what lets `p->lock` be acquired by the scheduler and released by the process
  ([handoff](#handoff)): both run on the same hart, so `holding` is true for both.
* **Interrupts must be off** (the comment on line 79). With them on, a timer interrupt could
  switch this thread out between reading `lk->cpu` and calling [[mycpu]], and it could resume
  on another hart: the answer would be about the wrong hart. Every caller has them off:
  [[acquire]] after its `push_off`, [[release]] and [[sched]] because they hold a lock.
* **It catches self-deadlock.** If a hart that holds `lk` called `acquire(&lk)` again, the swap
  would return 1 forever: the holder is the spinner. Line 25 turns that silent hang into
  `panic: acquire`. A real way to hit it: call [[wakeup]] while holding your own `p->lock`.
  `wakeup` takes every process's `p->lock` in turn, yours included. That is why [[kexit]]
  calls `wakeup(p->parent)` on line 353 *before* `acquire(&p->lock)` on line 355.

## Interrupts: the SIE bit {#sie}

A hart in supervisor mode takes an interrupt only if three things are true: the interrupt is
pending, its own bit is set in [[g:csr:sie|sie]] (xv6 sets the external and timer bits once,
at boot), and the global switch `sstatus.SIE` is 1. (In user mode, supervisor interrupts are
taken whatever SIE says.) When a trap is taken, the hardware copies SIE into `SPIE` and clears
SIE; `sret` copies `SPIE` back. Everything else is xv6's own code, and there are only a handful
of instructions:

| Instruction | Where | Effect |
|---|---|---|
| `csrrci a5,sstatus,2` (`0x80000bb8`) | [[push_off]], [[kernel/spinlock.c:97]] | read sstatus and clear SIE, in one instruction |
| `csrsi sstatus,2` (`0x80000c4c`) | [[pop_off]], [[kernel/spinlock.c:115]] | set SIE (only when noff reaches 0 and intena is 1) |
| `csrsi sstatus,2` (`0x80002668`) | [[usertrap]], [[kernel/trap.c:66]] | interrupts on for a system call |
| `csrci sstatus,2` (`0x80002496`) | [[prepare_return]], [[kernel/trap.c:108]] | off before `stvec` points at [[uservec]] |
| `csrw sstatus` | [[prepare_return]], [[kernel/trap.c:128]] | writes SIE 0 again, and sets the `SPIE` that `userret`'s `sret` will copy into SIE |
| `csrsi` then `csrci` (`0x80001e0c`, `0x80001e10`) | [[scheduler]], [[kernel/proc.c:441-442]] | a one-instruction window in which a pending interrupt is taken |
| `csrw sstatus` | [[kerneltrap]], [[kernel/trap.c:163]] | puts back the `sstatus` saved at entry (its SIE is 0) |
| `sret` | [[kernelvec]], [[userret]] | SIE = SPIE |

[[intr_on]] and [[intr_off]] compile to one instruction each, the immediate forms
[[g:insn:csrsi|csrsi / csrci]], and [[intr_get]] reads the bit. Bit 1 is the value 2,
hence the `,2`.

**wfi with interrupts off.** An idle scheduler executes `wfi` (`0x80001e08`,
[[kernel/proc.c:467]]) with SIE = 0. The RISC-V privileged specification says
[[g:insn:wfi|wfi]] must resume when an interrupt enabled in `sie` becomes pending, *whatever
SIE says*; the interrupt is then taken in the window at the top of the loop (`sepc` =
`0x80001e10`, see [[concept:stacks#scheduler]]). Scanning with SIE off (line 442) closes a race:
otherwise an interrupt could be handled after the scan found nothing but before `wfi`, leaving
the hart asleep although a process had just become runnable.

## push_off and pop_off: counting {#noff}

Why must interrupts be off while a spinlock is held? Because an interrupt handler on the
same hart might want the same lock. Suppose a system call on hart 0 holds `tickslock` in
[[sys_pause]] and the timer fires. [[clockintr]] wants `tickslock` ([[kernel/trap.c:170]]).
It spins, and it spins forever: the holder is the very code the interrupt paused, and it
cannot continue until the handler returns. With SIE off, the timer interrupt stays pending and
is taken right after the release. (A handler on *another* hart that wants the lock just spins
until it is released, which is fine.)

Why not plain `intr_off()`/`intr_on()`? Because locks nest (releasing [[kwait]]'s inner
`p->lock` must not enable interrupts while `wait_lock` is held), and because if interrupts were
already off before the first lock (a handler, the scheduler, boot), they must stay off. So [[push_off]] and [[pop_off]] ([[kernel/spinlock.c:92-116]]) keep two fields
in this hart's `struct cpu` ([[kernel/proc.h:22-27]]): `noff` at offset 120 and `intena` at
offset 124 (the struct is 128 bytes: the `proc` pointer, the 112-byte `context`, two `int`s).

```c
push_off:  flags = csrrci sstatus, SIE      // old value, and SIE now 0
           if (noff == 0) intena = old SIE
           noff += 1
pop_off:   if (SIE) panic("pop_off - interruptible")
           if (noff < 1) panic("pop_off")
           noff -= 1
           if (noff == 0 && intena) SIE = 1
```

SIE is cleared *before* `noff` is touched, so no interrupt can arrive mid-bookkeeping, and
[[mycpu]] is reliable because the thread can no longer move to another hart.

Two other functions call the pair directly. [[myproc]] ([[kernel/proc.c:85-88]]) wraps its read
of `c->proc` so the thread cannot migrate mid-read, which is why `noff` briefly goes one level
deeper than the locks held whenever lock code calls `myproc()`. And [[uartputc_sync]]
([[kernel/uart.c:105-106]], [[kernel/uart.c:118-119]]) brackets its wait-and-write on the UART. The code gives no reason; probably it is so that an
interrupt on this hart cannot split the test of the transmit register from the write, and it
skips the pair while `panicking` is set probably so that a panic raised from inside the lock
code can still print.

### intena {#intena}

`intena` answers one question: *should the last `pop_off` turn interrupts back on?* Only the
outermost `push_off` (the one that takes `noff` from 0 to 1) records it, because inner calls
always find SIE already 0 and would lose the original value. When `noff` is 0, `intena` keeps
its old value, but nothing reads it; tour strips show it as "—".

The rule for predicting it: **intena is the SIE value at the moment noff last went from 0 to
1 on this hart.**

* In a system call, after [[usertrap]]'s `intr_on()`: the first acquire records 1.
* In an interrupt handler ([[devintr]] and everything it calls), in [[kerneltrap]], in the
  scheduler loop after line 442, and at boot: SIE is already 0, so 0.
* In [[forkret]]: the `p->lock` it releases was acquired by the scheduler, so 0, and the
  release on line 520 leaves interrupts off.

### A worked trace: kwait reaps a child {#trace}

Here is the deepest nesting the measurements found (see [nesting](#nesting)): a parent in
`wait` finds a `ZOMBIE` child and frees it. Start in [[usertrap]] after line 66.

| # | Code | What happens | SIE | noff | intena |
|---|---|---|---|---|---|
| 0 | [[kernel/trap.c:66]] `intr_on()` | system call begins | 1 | 0 | — |
| 1 | [[kernel/proc.c:374]] `myproc()` → `push_off` | `csrrci` reads SIE = 1 and clears it; noff was 0 so intena = 1 | 0 | 1 | 1 |
| 2 | `myproc()` → `pop_off` | noff 1 → 0, intena is 1: `csrsi` | 1 | 0 | — |
| 3 | [[kernel/proc.c:376]] `acquire(&wait_lock)` → `push_off` | SIE 1 → 0, intena = 1 | 0 | 1 | 1 |
| 4 | same `acquire`: holding, `amoswap`, `lk->cpu` | `wait_lock` held | 0 | 1 | 1 |
| 5 | [[kernel/proc.c:384]] `acquire(&pp->lock)` | old SIE is 0, but noff ≠ 0, so intena is left alone | 0 | 2 | 1 |
| 6 | [[kernel/proc.c:398]] [[freeproc]] → [[kfree]] → [[kernel/kalloc.c:59]] `acquire(&kmem.lock)` | the third level | 0 | **3** | 1 |
| 7 | [[kernel/kalloc.c:62]] `release(&kmem.lock)` → `pop_off` | noff 3 → 2; not 0, nothing else | 0 | 2 | 1 |
| 8 | [[proc_freepagetable]] frees every page: more `kfree` calls | noff 2 → 3 → 2 for each page | 0 | 2 | 1 |
| 9 | [[kernel/proc.c:399]] `release(&pp->lock)` | noff 2 → 1 | 0 | 1 | 1 |
| 10 | [[kernel/proc.c:400]] `release(&wait_lock)` → `pop_off` | noff 1 → 0 and intena = 1: `csrsi sstatus,2` at `0x80000c4c` | 1 | 0 | — |

Interrupts were off exactly while a spinlock was held. Had they been off before step 3,
intena would have been 0 and step 10 would have left them off.

{{fig:locks-noff-timeline|SIE, noff and intena on one hart while a parent waits for a child: `kwait` registers and sleeps, the hart switches to its scheduler (which forces intena to 0), and later the parent resumes and reaps the child at noff 3. intena belongs to each thread: `sched` keeps the parent's 1 in a register across the switch and puts it back.}}

## The invariant: noff > 0 means SIE = 0 {#invariant}

On every hart, at every instruction: **whenever noff is greater than 0, SIE is 0.** It holds
because of who can set SIE:

* `push_off` clears SIE *before* incrementing `noff`, and `pop_off` sets it only *after*
  `noff` has dropped to 0;
* [[usertrap]]'s `intr_on()` runs on a hart that just came from user mode, where `noff` is 0;
* the scheduler's `intr_on()` runs at the top of its loop, holding nothing;
* [[kerneltrap]]'s `w_sstatus(sstatus)` ([[kernel/trap.c:163]]) writes back the value read at
  entry, whose SIE is 0 (line 147 panics otherwise), so it never turns SIE on by itself;
* `sret` in [[kernelvec]] then restores the interrupted code's SIE from `SPIE`; it is 1 only if
  the interrupted code was at noff 0, and [[kerneltrap]] has released everything it took
  (including the `p->lock` of a [[yield]]) before it returns, so noff is 0 again;
* `sret` in [[userret]] goes to user mode with noff 0.

And `pop_off` checks the invariant every time: SIE on at a `pop_off` means someone turned
interrupts on inside a critical section, and the kernel panics `pop_off - interruptible`.

The consequence is the reason for the whole scheme: **a device or timer interrupt is only ever
taken on a hart whose noff is 0.** An interrupt handler can therefore never interrupt a
critical section on its own hart, and it can safely acquire any spinlock that is not held on
its own hart. Exceptions are a different matter: a page fault or illegal instruction in kernel
code is a bug, and [[kerneltrap]] panics whatever `noff` is.

## Which interrupt handlers take which locks {#handlers}

Every lock below is taken from an interrupt handler on some hart, so every other acquirer
must hold it with interrupts off. [[acquire]] makes that automatic.

| Handler | Locks | Pair it protects against, on the same hart |
|---|---|---|
| [[clockintr]] (hart 0 only) | `tickslock`, then each `p->lock` in `wakeup(&ticks)` | [[sys_pause]], [[sys_uptime]] |
| [[uartintr]] | each `p->lock` in `wakeup(&tx_chan)` | anyone holding a `p->lock` |
| [[consoleintr]] (called by `uartintr`) | `cons.lock`, then `p->lock` in `wakeup(&cons.r)`; with Ctrl-P, `pr.lock` through [[procdump]]'s [[printk]] | [[consoleread]]; [[printk]] |
| [[virtio_disk_intr]] | `disk.vdisk_lock`, then `p->lock` in `wakeup(b)` | [[virtio_disk_rw]] |
| [[devintr]] | `pr.lock` if it prints `unexpected interrupt` | [[printk]] |
| [[kerneltrap]], [[usertrap]] on a timer interrupt | the process's own `p->lock`, in [[yield]] | (not inside [[devintr]]; intena is 0) |

In the [measured run](#measured) the locks taken inside [[devintr]] were exactly these five
(per-lock counts in the [inventory](#inventory)), and never a sleep-lock: a handler cannot
sleep, so it can never wait for one.

## intena belongs to the thread {#sched-intena}

`struct cpu` holds one `intena` per hart, but a hart runs many threads, each of which took its
outermost lock in its own situation: a process sleeping from a system call with SIE on
(intena 1), a process yielding from [[kerneltrap]] with SIE off (0), the scheduler always with
SIE off (0). Each thread's outermost `push_off` overwrites `mycpu()->intena`, so the value has
to travel with the thread, as the comment above [[sched]] says ([[kernel/proc.c:472-478]]).

The code does it in two halves:

* **[[sched]] saves and restores it** ([[kernel/proc.c:494]], [[kernel/proc.c:496]]). The
  local variable `intena` lives in the callee-saved register `s3` in this build: `lw s3,172(a5)`
  at `0x80001e7e` before the `swtch`, `sw s3,172(s2)` at `0x80001ea4` after it (`a5` and `s2`
  hold `cpus + 128 × hart − 48`, so 172 is `intena`'s offset 124 plus 48). [[swtch]] saves
  `s3` in `p->context`, so the value travels with the process to whichever hart resumes it.
* **[[scheduler]] sets it to 0** right after its `swtch` returns ([[kernel/proc.c:456]],
  `sw zero,172(a5)` at `0x80001df8`). The scheduler's own value is always 0, so this is its
  version of the restore.

What goes wrong without each half (reasoned from the code):

* **Without the restore on line 496**, a process that slept from a system call would resume
  with the intena that the scheduler's `acquire` on line 446 recorded: 0. Its `release` at the
  end of [[sleep]] would leave interrupts off, for the rest of that system call (until `sret`
  on the way to user mode), so it could no longer be preempted.
* **Without line 456**, the scheduler would run with interrupts on after any process that
  slept from a system call: outside its one-instruction window, with the `wfi` race described
  [above](#sie). Its next `acquire` on line 446 would then record intena 1, and a brand-new
  process's [[forkret]] would turn interrupts on when it released that lock.
* **Without both**, the classic failure appears: process A sleeps from a system call
  (intena 1); the scheduler inherits 1, releases A's lock with interrupts turned on, takes the
  next `p->lock` recording intena 1, and switches to B, which had yielded from [[kerneltrap]].
  B inherits 1, and its `release` at the end of [[yield]] turns interrupts on *inside
  kerneltrap*, before lines 162–163 restore `sepc` and `sstatus`. A second interrupt there
  overwrites `sepc`, and the first trap returns to the wrong place.

[[tour:50]] follows `noff` and `intena` through a sleep, a yield and an interrupt.

## p->lock is handed across swtch {#handoff}

Every other lock is released by the same thread that acquired it. `p->lock` is the exception, and the
reason the kernel works.

* The scheduler acquires `p->lock` ([[kernel/proc.c:446]]), marks the process `RUNNING`, and
  calls [[swtch]] **with the lock held**. The process wakes up in the middle of [[sched]] and
  releases it: at the end of [[yield]] ([[kernel/proc.c:507]]), at the end of [[sleep]]
  ([[kernel/proc.c:571]]), or, for a process that has never run, in [[forkret]]
  ([[kernel/proc.c:520]]).
* When the process gives up the hart it acquires its own `p->lock` ([[yield]] line 504,
  [[sleep]] line 566, [[kexit]] line 355), changes `p->state`, and calls [[sched]], which
  calls `swtch` **with the lock held**. The scheduler, back from its own `swtch` call, releases
  it ([[kernel/proc.c:463]]).

{{fig:locks-handoff|One hart, two threads, one lock. The scheduler acquires `p->lock`, `swtch` carries it to the process, and the process releases it; to give the hart back, the process acquires it, `swtch` carries it back, and the scheduler releases it. `lk->cpu` names the hart throughout, so `holding()` is satisfied on both sides, and noff is exactly 1 at every `swtch`.}}

Why hold a lock across the switch at all? Between `p->state = RUNNABLE` (or `SLEEPING`) and the
moment `swtch` has finished saving the registers, the process is still running on its kernel
stack. If another hart's scheduler could see the new state, it could pick the process and start
running it on the *same* kernel stack: two harts, one stack. Holding `p->lock` from before the
state change until the scheduler's release makes "change state, stop using the stack" one
step as far as other harts can tell. The same lock makes [[wakeup]] wait while a process is
halfway into [[sleep]], and makes [[kwait]] wait while a child is still inside [[kexit]]'s
`sched` (the comment on [[kernel/proc.c:383]]).

It works because [[holding]] names the hart ([above](#holding)). [[tour:13]] steps through it.

## Sleep-locks {#sleep-locks}

Some locks must be held for a long time. [[bread]] holds a buffer while the disk reads it,
which takes milliseconds, and the process sleeps in [[virtio_disk_rw]] meanwhile. A spinlock
cannot be held there: other harts would spin with interrupts off for the whole disk access,
and [[sched]] refuses to switch away from a thread holding any spinlock but its own `p->lock`
(it would panic `sched locks`). A [[g:sleeplock|sleep-lock]] is a lock whose waiters sleep
instead of spinning.

{{fig:locks-sleeplock-anatomy|A `struct sleeplock` is a flag and a PID, guarded by a spinlock of its own. Process A holds the lock across a disk read; process B finds it held, registers on the lock's address and sleeps; A's `releasesleep` wakes B, which takes it. The inner spinlock is held only for a few instructions at a time.}}

`struct sleeplock` ([[kernel/sleeplock.h]]) is `locked` (offset 0), `lk`, a whole spinlock
(offset 8), `name` (32) and `pid` (40). Its functions ([[kernel/sleeplock.c]]):

* [[acquiresleep]]: take `lk->lk`; while `locked` is 1, [[sleep_prepare]]`(lk)`, release
  `lk->lk`, [[sleep]], take `lk->lk` again; then `locked = 1`, `pid = myproc()->pid`, release
  `lk->lk`. The `myproc()` call does its own `push_off`, so noff goes one deeper for a moment.
* [[releasesleep]]: under `lk->lk`, `locked = 0`, `pid = 0`, [[wakeup]]`(lk)`.
* [[holdingsleep]]: under `lk->lk`, is it locked *by this process's PID*? Ownership is by
  process, not by hart, because a sleep-lock holder can sleep and resume on another hart.

Holding a sleep-lock adds nothing to `noff`. In a system call, a process holding one runs with
interrupts on and may sleep; [[sched]] only counts spinlocks. In the measured run a process went
to sleep 32,427 times holding a buffer lock and 1,165 times holding an inode lock. The price:
only a process can use a sleep-lock. Interrupt handlers and the scheduler never do, and
[[forkret]]'s comment explains why the file system is initialized from the first process
rather than from `main`.

There are 81 sleep-locks at boot: 30 buffers, 50 in-memory inodes, and the UART's `tx_lock`.
Each has its own inner spinlock, which gives 75 + 81 = 156 spinlocks at boot, plus one for
every pipe created later. [[tour:17]] follows one through a contended `ilock`.

## sleep_prepare, sleep and wakeup in this tree {#sleep-wakeup}

A process that must wait for a condition (input on the console, a disk request, a child's
exit) should give up the hart. The danger is the **lost wakeup**: the process checks the
condition, finds it false, and before it is actually asleep the event happens and the waker
calls [[wakeup]], which finds nobody asleep. Then the process sleeps forever.

**This tree differs from the MIT xv6 book**, whose `sleep(chan, lk)` releases the caller's lock
itself. Here the protocol is split in two, and no lock is passed to `sleep`:

```c
acquire(&lk);                    // lk protects the condition
while (!condition) {
  sleep_prepare(chan);           // under p->lock: p->chan = chan
  release(&lk);
  sleep();                       // under p->lock: if p->chan != 0, SLEEPING + sched
  acquire(&lk);
}
... use the condition ...
release(&lk);
```

and on the other side, with `lk` held, change the condition and call `wakeup(chan)`.

* [[sleep_prepare]] ([[kernel/proc.c:546-556]]) records the channel in `p->chan` under
  `p->lock`, *while the caller still holds `lk`*.
* [[sleep]] ([[kernel/proc.c:561-572]]) takes `p->lock` and goes to sleep only if `p->chan` is
  still non-zero. Otherwise it returns at once.
* [[wakeup]] ([[kernel/proc.c:575-595]]) takes every process's `p->lock` in turn. If `p->chan`
  matches, it clears it, and if the process is `SLEEPING`, it makes it `RUNNABLE`. (The
  comment on line 587–588 says "back to RUNNING"; the code, correctly, sets `RUNNABLE`.)

{{fig:locks-sleep-wakeup|The window between `release(&lk)` and `sleep()`. The waker on another hart changes the condition under `lk` and calls `wakeup`, which lands in the window: it clears `p->chan`, and `sleep()` then sees 0 and returns at once. The loop re-checks the condition and finds it true. No wakeup is lost, and no lock is passed to `sleep`.}}

Why no wakeup can be lost, by where the waker's `wakeup` lands relative to the sleeper:

1. **Before the sleeper's check**: the sleeper sees the condition true and never sleeps.
2. **Between the check and `sleep_prepare`**: impossible, since both sides need `lk`.
3. **Between `release(&lk)` and `sleep()`'s `acquire(&p->lock)`.** The window. `wakeup` clears
   `p->chan`; `sleep` sees 0 and returns; the loop re-checks.
4. **While the sleeper is inside `sleep()`.** It holds `p->lock`, so `wakeup` spins on it until
   the sleeper is `SLEEPING` and the scheduler has released the lock (handed across `swtch`,
   [above](#handoff)). Then `wakeup` sees `SLEEPING` and makes it `RUNNABLE`.
5. **After it is asleep**: the ordinary case.

All the reads and writes of `p->chan` and `p->state` happen under `p->lock` (apart from
[[procdump]]'s deliberately unlocked reads), which is what makes cases 3 and 4 airtight. Note that in this tree `p->chan != 0` means "registered for a
wakeup", not "sleeping": the comment on `chan` in [[kernel/proc.h:87]] ("If non-zero, sleeping
on chan") is out of date.

**A return from `sleep` never means the condition is true.** [[wakeup]] wakes every process on
the channel, and only one may win the resource. And [[kkill]] ([[kernel/proc.c:600-622]])
makes a `SLEEPING` process `RUNNABLE` without clearing `p->chan` and without anything having
changed. So every caller re-checks in a `while` loop, and the ones that may wait indefinitely
also check [[killed]] ([[consoleread]], [[piperead]], [[pipewrite]], [[sys_pause]], [[kwait]]).
The leftover `p->chan` is harmless: the next `sleep_prepare` overwrites it.

**uartwrite uses the protocol with no spinlock at all** ([[kernel/uart.c:80-96]]). Its
condition is a device register: "the transmitter can take a byte" (`LSR_TX_IDLE`). Every
iteration calls `sleep_prepare(&tx_chan)` first, *then* reads `LSR`. If the UART is busy, it
calls `sleep()`. [[uartintr]] calls `wakeup(&tx_chan)` whenever it sees the transmitter idle
([[kernel/uart.c:143-145]]). If that interrupt comes between the `LSR` read and `sleep()`, it
clears `p->chan` and `sleep` returns at once; the loop re-registers and reads `LSR` again.
Registering *before* testing is what replaces the lock. (In the measured run `uartwrite` took
`tx_lock` 1,426 times and never had to sleep.)

[[tour:16]] follows a sleep and a wakeup on two harts.

## The inventory {#inventory}

Every lock in the kernel at this commit. The source view puts a badge on each of the 180 lines
that acquire, release, test or initialize a lock or change interrupt state, and links it here.

| Lock | Kind | How many | Declared | Protects | Taken in an interrupt handler |
|---|---|---|---|---|---|
| [`kmem.lock`](#lock-kmem) | spin | 1 | [[kernel/kalloc.c:22]] | the free-page list | no |
| [`bcache.lock`](#lock-bcache) | spin | 1 | [[kernel/bio.c:26]] | the buffer LRU list; every buffer's `refcnt`, `dev`, `blockno` | no |
| [`b->lock`](#lock-buf) | sleep | 30 | [[kernel/buf.h:6]] | one buffer's `data` and `valid` | no |
| [`itable.lock`](#lock-itable) | spin | 1 | [[kernel/fs.c:179]] | every in-memory inode's `ref`, `dev`, `inum` | no |
| [`ip->lock`](#lock-inode) | sleep | 50 | [[kernel/file.h:21]] | all other inode fields and the inode's contents | no |
| [`ftable.lock`](#lock-ftable) | spin | 1 | [[kernel/file.c:18]] | every open file's `ref`; slot allocation | no |
| [`log.lock`](#lock-log) | spin | 1 | [[kernel/log.c:41]] | `outstanding`, `committing`, `ncommit`, the in-memory log header | no |
| [`pi->lock`](#lock-pipe) | spin | one per pipe | [[kernel/pipe.c:14]] | the pipe's buffer, counts and open flags | no |
| [`p->lock`](#lock-proc) | spin | 64 | [[kernel/proc.h:83]] | `state`, `chan`, `killed`, `xstate`, `pid`; held across `swtch` | **yes** |
| [`wait_lock`](#lock-wait_lock) | spin | 1 | [[kernel/proc.c:27]] | every `p->parent` | no |
| [`pid_lock`](#lock-pid_lock) | spin | 1 | [[kernel/proc.c:16]] | `nextpid` | no |
| [`tickslock`](#lock-tickslock) | spin | 1 | [[kernel/trap.c:9]] | `ticks` | **yes** |
| [`cons.lock`](#lock-cons) | spin | 1 | [[kernel/console.c:48]] | the console input buffer and its indices | **yes** |
| [`pr.lock`](#lock-pr) | spin | 1 | [[kernel/printk.c:23]] | one `printk`'s characters, kept together | **yes** |
| [`disk.vdisk_lock`](#lock-vdisk) | spin | 1 | [[kernel/virtio_disk.c:57]] | the virtio descriptors, rings, `free[]`, `info[]` | **yes** |
| [`tx_lock`](#lock-uart) | sleep | 1 | [[kernel/uart.c:42]] | the UART transmitter, one writer at a time | no |
| [`lk->lk`](#lock-sleeplock-lk) | spin | one per sleep-lock (81) | [[kernel/sleeplock.h:4]] | a sleep-lock's `locked` and `pid` | no |
| [`lk`](#lock-any) | spin | — | [[kernel/spinlock.h:2]] | the lock code's parameter | — |

At boot that is 75 named spinlocks (11 global ones plus 64 `p->lock`s) and 81 sleep-locks.
Counts below ("taken N times") are from the [measured run](#measured).

### kmem.lock {#lock-kmem}

Spinlock, one, [[kernel/kalloc.c:22]]; protects the free-page list. Taken by [[kfree]]
([[kernel/kalloc.c:59]]) and [[kalloc]] ([[kernel/kalloc.c:73]]) for a few instructions (the
junk fill happens outside). No sleep, no interrupt handler. A leaf, acquired after `wait_lock`
and `p->lock` ([[allocproc]], [[kfork]]'s [[uvmcopy]], [[kwait]]'s [[freeproc]]): that is how
it reaches noff 3. Taken 1,025,207 times, second only to `p->lock`.

### bcache.lock {#lock-bcache}

Spinlock, one, [[kernel/bio.c:26]]; protects the LRU list and each buffer's `refcnt`, `dev`,
`blockno`. Taken in [[bget]] ([[kernel/bio.c:62]]), [[brelse]] (124), [[bpin]] (142),
[[bunpin]] (150); `bget` drops it before taking the buffer's sleep-lock ([unusual](#unusual)).
A leaf, acquired after `log.lock` ([[log_write]] → [[bpin]]: 6,552 times) and under buffer and
inode sleep-locks. Taken 409,426 times.

### b->lock {#lock-buf}

Sleep-lock, 30 ([[NBUF]]), [[kernel/buf.h:6]]; protects a buffer's `data` and `valid`. Taken in
[[bget]] ([[kernel/bio.c:69]], [[kernel/bio.c:83]]), so [[bread]] returns it locked; released
by [[brelse]] ([[kernel/bio.c:122]]); checked by [[bwrite]] and [[brelse]]. Held across sleep
by design, while [[virtio_disk_rw]] waits for the disk: 198,161 acquisitions, and a process went
to sleep 32,427 times holding one. Never in an interrupt handler: [[virtio_disk_intr]] touches
only `b->disk`, which `disk.vdisk_lock` protects. Up to two per process (indirect block and
bitmap block; log block and home block).

### itable.lock {#lock-itable}

Spinlock, one, [[kernel/fs.c:179]]; protects every in-memory inode's `ref`, `dev`, `inum`.
Taken by [[iget]] (253), [[idup]] (286), [[iput]] (352, 370). Acquired after `p->lock` (a fork
child's [[idup]], [[userinit]]'s [[namei]]) and under inode sleep-locks; held while taking an
inode's sleep-lock only in [[iput]] ([order](#order)). Taken 22,473 times.

### ip->lock {#lock-inode}

Sleep-lock, 50 ([[NINODE]]), [[kernel/file.h:21]]; protects `valid`, `type`, `nlink`, `size`,
`addrs` and the file's contents. Taken by [[ilock]] ([[kernel/fs.c:303]]) and [[iput]] (362),
released by [[iunlock]] (328) and [[iput]] (368). Held across sleep while blocks are read:
11,893 acquisitions, 1,165 sleeps holding one. Two at once only parent directory first
([[create]], `sys_unlink`). Under it: buffer locks, `bcache`, `itable`, `ftable`, `log`, `kmem`,
`disk.vdisk_lock`.

### ftable.lock {#lock-ftable}

Spinlock, one, [[kernel/file.c:18]]; protects each `struct file`'s `ref` and slot allocation.
Taken by [[filealloc]] (34), [[filedup]] (50), [[fileclose]] (64), which drops it before
[[pipeclose]] or [[iput]]. A leaf, acquired under a child's `p->lock` ([[kfork]]'s
[[filedup]]: 20,205 times) and under an inode lock (`open`). Taken 42,454 times.

### log.lock {#lock-log}

Spinlock, one, [[kernel/log.c:41]]; protects `outstanding`, `committing`, `ncommit` and the
in-memory header. Taken by [[begin_op]] (131), [[end_op]] (159, 178), [[log_write]] (228),
[[sys_sync]] (249); waiters sleep on `&log`. [[end_op]] drops it before [[commit]], which sleeps
on disk writes (comment at 175–176); `committing` keeps other operations out meanwhile, which is
why [[commit]] can read the header without the lock. Before: `p->lock`, `bcache.lock`. Taken
51,832 times.

### pi->lock {#lock-pipe}

Spinlock, one per pipe ([[kernel/pipe.c:14]]), made by [[pipealloc]]; protects the 512-byte
buffer, `nread`, `nwrite`, `readopen`, `writeopen`. Taken by [[pipeclose]] (61), [[pipewrite]]
(82), [[piperead]] (118); writers sleep on `&pi->nwrite`, readers on `&pi->nread`. Before:
`p->lock` ([[wakeup]], [[killed]]), and `kmem.lock` if a user copy hits a lazily allocated page.
Taken 790 times: a writer holds it for a whole write, except while asleep on a full pipe.

### p->lock {#lock-proc}

Spinlock, 64 ([[NPROC]]), [[kernel/proc.h:83]]; protects `state`, `chan`, `killed`, `xstate`,
`pid`, and is **the** lock that crosses `swtch` ([handoff](#handoff)). Taken in [[scheduler]]
(446), [[yield]] (504), [[sleep_prepare]] (551), [[sleep]] (566), [[wakeup]] (581), [[kkill]]
(609), [[setkilled]], [[killed]], [[allocproc]] (115), [[kfork]] (300), [[kexit]] (355),
[[kwait]] (384). Taken 26,327,578 times, mostly by [[wakeup]], which takes every slot's lock in
turn (every [[brelse]] calls one through [[releasesleep]]: 12.7 million acquisitions); the
schedulers' scans account for most of the rest. Interrupt handlers take it through [[wakeup]]
(1,366,848 times; about 111,700 of them from [[uartintr]]'s `wakeup(&tx_chan)`, which holds no
other lock). Acquired after almost everything. Only four locks are taken while holding it:
`pid_lock`, `ftable.lock`, `itable.lock` for a slot being built ([[allocproc]], [[kfork]],
[[userinit]]), and `kmem.lock` for those and when [[kwait]]'s [[freeproc]] frees a zombie
child under the child's lock.

### wait_lock {#lock-wait_lock}

Spinlock, one, [[kernel/proc.c:27]]; protects every `p->parent` and makes exit and wait atomic
with respect to each other. "Must be acquired before any p->lock" (line 26). Taken by [[kfork]]
(296), [[kexit]] (347), [[kwait]] (376, 417): `kwait` registers with `sleep_prepare(p)` and
`kexit` calls `wakeup(p->parent)` while holding it, so no exit is missed. Before: `p->lock`,
`kmem.lock`. Taken 24,111 times.

### pid_lock {#lock-pid_lock}

Spinlock, one, [[kernel/proc.c:16]] (named `"nextpid"`); protects `nextpid`. Taken only by
[[allocpid]] ([[kernel/proc.c:97]]), under the new slot's `p->lock`. A leaf. Taken 6,723 times:
the number of PIDs handed out.

### tickslock {#lock-tickslock}

Spinlock, one, [[kernel/trap.c:9]] (named `"time"`); protects `ticks`. Taken by [[clockintr]]
([[kernel/trap.c:170]], hart 0, in the timer handler), [[sys_pause]] (76, 86) and
[[sys_uptime]] (108); a sleeping `pause` waits on `&ticks`. Before: `p->lock`. Taken 871 times,
578 in the handler.

### cons.lock {#lock-cons}

Spinlock, one, [[kernel/console.c:48]]; protects `cons.buf` and `r`, `w`, `e`. Taken by
[[consoleread]] (95, 107), which sleeps on `&cons.r`, and by [[consoleintr]] (149) in the UART
handler. Before: `p->lock`, and `pr.lock` on Ctrl-P ([[procdump]]); echo goes through
[[uartputc_sync]]'s `push_off` under it. Taken 138 times, 67 in the handler.

### pr.lock {#lock-pr}

Spinlock, one, [[kernel/printk.c:23]]; keeps one [[printk]]'s characters together across three
harts. Taken at [[kernel/printk.c:71]], released at 132, both skipped once `panicking` is set.
In interrupt context through Ctrl-P's [[procdump]] and [[devintr]]'s "unexpected interrupt". A
leaf apart from [[uartputc_sync]]'s `push_off`. Taken 290 times.

### disk.vdisk_lock {#lock-vdisk}

Spinlock, one, [[kernel/virtio_disk.c:57]]; protects the descriptors, the avail and used rings,
`disk.free[]`, `disk.info[]` and each `b->disk`. Taken by [[virtio_disk_rw]] (220), which sleeps
for free descriptors (232–235) and for completion (288–291), and by [[virtio_disk_intr]] (303).
Before: `p->lock`; acquired under buffer and inode sleep-locks. Taken 57,088 times, 19,028 in
the handler.

### tx_lock {#lock-uart}

Sleep-lock, one, [[kernel/uart.c:42]]; one process at a time feeds the UART, so two console
`write`s do not interleave. Taken and released only by [[uartwrite]] ([[kernel/uart.c:82]],
[[kernel/uart.c:95]]). It could be held across the `sleep()` on line 91, but in the measured
run it never was: 1,426 acquisitions, and every one of the 1,453 bytes found the transmitter
ready. No interrupt handler takes it. [[uartputc_sync]] ([[printk]], echo) bypasses it.

### lk->lk {#lock-sleeplock-lk}

Spinlock, one inside every sleep-lock (81 at boot), [[kernel/sleeplock.h:4]], named
`"sleep lock"`; protects that sleep-lock's `locked` and `pid`. Held only inside
[[acquiresleep]], [[releasesleep]] and [[holdingsleep]], never across a sleep. Before:
`p->lock` ([[sleep_prepare]], [[wakeup]]). After: `itable.lock`, in [[iput]]. The inner locks
of buffer, inode and UART sleep-locks were taken 612,218, 35,464 and 2,943 times.

### lk, the parameter {#lock-any}

Inside [[kernel/spinlock.c]], `lk` is whatever lock the caller passed; the badges there mark the
lock code's own operations. See [the spinlock](#spinlock).

## The lock-order graph {#order}

A **[[g:lock-order]]** edge "A before B" means some code path holds A while acquiring B. If
one path holds A and wants B while another holds B and wants A, two harts can each wait for the
other forever: a [[g:deadlock]]. So the edges must never form a cycle that can actually close. xv6 writes few of its
ordering rules down (the comment on `wait_lock` is one), so the graph below was measured: every
time a lock was acquired, the recorder noted which locks the same hart (or, for sleep-locks,
the same process) already held.

{{fig:locks-order-graph|The measured lock-order graph. An arrow from A to B means B was acquired while A was held. Sleep-locks sit at the top: a process may hold them while it takes anything below. `p->lock` sits near the bottom: nearly everything is held when it is taken, and while it is held only `kmem.lock`, `pid_lock`, `ftable.lock` and `itable.lock` are taken, for a process slot being built or (`kmem.lock` only) a zombie being freed. The dashed arrow closes one of the class-level cycles; all of them pass through `iput` and cannot deadlock (see the text).}}

Spinlock → spinlock edges observed:

* `wait_lock` → `p->lock`, `kmem.lock` ([[kwait]])
* `p->lock` → `pid_lock`, `kmem.lock`, `ftable.lock`, `itable.lock` ([[allocproc]], [[kfork]],
  [[userinit]], holding the new child's lock); `p->lock` → `kmem.lock` also in [[kwait]]'s
  [[freeproc]], under the zombie child's lock
* `tickslock` → `p->lock` (in the timer handler, and in [[sys_pause]])
* `disk.vdisk_lock` → `p->lock` (in the disk handler, and in [[virtio_disk_rw]])
* `cons.lock` → `p->lock`; `cons.lock` → `pr.lock` (Ctrl-P only)
* `log.lock` → `p->lock`, `bcache.lock`
* `pi->lock` → `p->lock`
* `itable.lock` → an inode's `lk->lk` ([[iput]])
* every sleep-lock's `lk->lk` → `p->lock`

Sleep-locks held while acquiring: inode → inode, inode → buffer, buffer → buffer; inode or
buffer → `bcache.lock`, `log.lock`, `disk.vdisk_lock`; inode → `itable.lock`, `ftable.lock`,
`kmem.lock`; `tx_lock` → `p->lock`. And one spinlock → sleep-lock edge: `itable.lock` →
`ip->lock`, in [[iput]].

**Cycles between classes.** A graph of lock *classes* does have cycles, and every one passes
through [[iput]]'s [[acquiresleep]] under `itable.lock` ([[kernel/fs.c:362]]), which adds the
edges `itable.lock` → `ip->lock` and its `lk->lk`:

* `itable.lock` → `ip->lock` → `itable.lock`: elsewhere, code holding a directory's inode lock
  calls [[iget]] or [[idup]] (2,607 times);
* `p->lock` → `itable.lock` → `lk->lk` → `p->lock`: [[kfork]]'s [[idup]] under the child's
  `np->lock` ([[kernel/proc.c:288]]), then [[releasesleep]]'s [[wakeup]]
  ([[kernel/sleeplock.c:42]]) or the [[sleep_prepare]] inside [[acquiresleep]].

None can close, because `iput` takes the inode's lock only when `ip->ref == 1` (line 357): the
only reference is the one `iput` is dropping, so no other process can hold that inode's lock or
be inside [[acquiresleep]] or [[releasesleep]] on it, and `iput`'s `acquiresleep` finds it free
and never sleeps. (If it slept, [[sched]] would panic `sched locks`: noff would be 2.) A
class-level graph cannot see that; the argument has to come from the code, and it would break
if anyone called [[acquiresleep]] under `itable.lock` without the same guarantee. The
self-edges inode → inode and buffer → buffer are kept safe by fixed roles instead: parent
directory before child, and indirect block before bitmap block, log block before home block.

**Edges the code allows that the run did not show.** Copying to or from user memory can
allocate a lazily allocated page ([[copyout]] and [[copyin]] call [[vmfault]], which calls
[[kalloc]]), so `pi->lock` → `kmem.lock` and `cons.lock` → `kmem.lock` are possible. Error-path
messages add more: [[balloc]]'s "out of blocks" and [[ialloc]]'s "no inodes" print (`pr.lock`)
under inode and buffer locks, and [[ireclaim]] holds a buffer while it prints and calls
[[iget]] (buffer → `pr.lock`, buffer → `itable.lock`). `kmem.lock` and `pr.lock` are leaves,
and `itable.lock` never waits for a buffer, so none of these creates a cycle.

[[tour:18]] explains the ordering rules and [[tour:51]] builds this graph from the
measurements.

## How deep it gets {#nesting}

The deepest `push_off` nesting observed on any hart was **noff = 3**, on exactly three paths:

1. [[kwait]]: `wait_lock` → the child's `p->lock` → `kmem.lock` ([[freeproc]] → [[kfree]]), the
   [trace above](#trace). 227,333 times.
2. [[iput]]: `itable.lock` → the inode's `lk->lk` → the `push_off` inside [[myproc]] on
   [[kernel/sleeplock.c:32]]. 344 times, each the last reference to an unlinked file
   ([order](#order) explains why this is safe).
3. Ctrl-P on the console, in an interrupt handler: `cons.lock` → `pr.lock` → the `push_off` in
   [[uartputc_sync]]. Only when someone types Ctrl-P.

The most sleep-locks held at once by one process was **3**: two inodes and a buffer (a
directory and a file during `create` or `unlink`, while reading a block; `link` never holds two, since `sys_link` unlocks the file before it locks the directory), or an inode
and two buffers (`bmap`'s indirect block and the bitmap block in `balloc`). Neither limit is
enforced anywhere; they are simply what the code does. `noff` is an `int`, and [[sched]] only
insists on exactly 1 at a switch.

## Unusual patterns {#unusual}

Most code follows the simple shape: acquire, touch the data, release, in the global order. A
few places do something cleverer, and each one is worth understanding.

* **[[iput]] takes a sleep-lock while holding a spinlock** ([[kernel/fs.c:362]]), legal only
  because `ip->ref == 1` means it never sleeps ([order](#order)). Line 363 then drops
  `itable.lock` before the slow truncation.
* **[[bget]] releases `bcache.lock` before [[acquiresleep]]** ([[kernel/bio.c:68-69]],
  [[kernel/bio.c:82-83]]). It must, since waiting for the buffer may mean sleeping. The gap is
  safe because `refcnt` was raised first (line 67 or 81): a buffer with a non-zero `refcnt` is
  never recycled for another block, so it is still the right buffer when the sleep-lock is
  finally granted.
* **[[kfork]] lets go of the child's lock to take `wait_lock`.** It holds the child's
  `np->lock` from [[allocproc]] through [[uvmcopy]], [[filedup]] and [[idup]]. To set
  `np->parent` it needs `wait_lock`, which must come *before* any `p->lock`, so it releases
  `np->lock` (line 294), takes `wait_lock` (296), and retakes `np->lock` (300).
* **[[kexit]] releases `wait_lock` while still holding its own lock** ([[kernel/proc.c:347-363]]).
  It reparents and wakes its parent under `wait_lock` (each [[wakeup]] takes every `p->lock`,
  so this comes before taking its own), takes its own `p->lock`, becomes `ZOMBIE`, and releases
  `wait_lock` (360): releasing out of order is legal; only the acquire order matters. [[sched]]
  demands noff = 1, and the kept `p->lock` stops the parent freeing the child until the
  scheduler releases it, after the child has left its kernel stack for good.
* **[[procdump]] takes no lock on the process table** ([[kernel/proc.c:675]]), to avoid wedging
  a stuck machine further (its [[printk]] still takes `pr.lock`). Its output may be
  inconsistent; that is the price.

## The rules {#rules}

What a kernel programmer working on this tree must do. The ones marked *enforced* panic when
broken.

1. **Hold the lock that protects a piece of shared data for every access** (see the comments at
   [[kernel/proc.h:85]], [[kernel/proc.h:92]], [[kernel/fs.c:170-176]]).
2. **Acquire in the global order.** Condition locks before `p->lock`; `wait_lock` before any
   `p->lock`; sleep-locks before spinlocks; inode before buffer; parent directory before child.
   Never acquire anything while holding a `p->lock` except those four, and only for a slot you
   are building or tearing down.
3. **Never switch away holding a spinlock other than your own `p->lock`** (*enforced*:
   `sched locks`). Release the condition lock between [[sleep_prepare]] and [[sleep]].
4. **Never call [[acquiresleep]] while holding a spinlock**, unless it provably cannot sleep
   ([[iput]]).
5. **Never call [[wakeup]] while holding your own `p->lock`** (*enforced*: `acquire`).
6. **Never turn interrupts on while holding a spinlock.** Use [[push_off]]/[[pop_off]], not
   [[intr_on]] (*enforced*: `pop_off - interruptible`, `sched interruptible`).
7. **Release on the hart that acquired** (*enforced*: `release`). The `p->lock` handoff is the
   one cross-thread release, and it stays on one hart.
8. **Keep spinlock sections short**, and never wait inside one for something that needs this
   hart (an interrupt, another process).
9. **Re-check the condition after every `sleep`**, and check [[killed]] where the wait may be
   long.
10. **Interrupt handlers never sleep and never take a sleep-lock.**

[[tour:52]] breaks several of these in a copy of the kernel and shows what happens.

## The panic catalogue {#panics}

The lock code's sanity checks, with what triggers each one.

| Message | Where | Means |
|---|---|---|
| `acquire` | [[kernel/spinlock.c:26]] | this hart already holds the lock: it would spin on itself forever |
| `release` | [[kernel/spinlock.c:49]] | releasing a lock this hart does not hold (never acquired, released twice, or acquired on another hart) |
| `pop_off - interruptible` | [[kernel/spinlock.c:110]] | SIE was on at a `pop_off`: someone enabled interrupts inside a critical section |
| `pop_off` | [[kernel/spinlock.c:112]] | more `pop_off`s (or releases) than `push_off`s |
| `sched p->lock` | [[kernel/proc.c:486]] | switching away without holding your own `p->lock` |
| `sched locks` | [[kernel/proc.c:488]] | `noff` is not exactly 1: switching away holding another spinlock (for example, forgetting `release(&lk)` before `sleep()`) |
| `sched RUNNING` | [[kernel/proc.c:490]] | the caller forgot to change `p->state` first |
| `sched interruptible` | [[kernel/proc.c:492]] | SIE on while holding `p->lock`: the invariant is broken |
| `kerneltrap: interrupts enabled` | [[kernel/trap.c:147]] | SIE on at the start of a kernel trap, which the hardware should have cleared |
| `sleep_prepare: zero chan` | [[kernel/proc.c:553]] | channel 0 would mean "not registered" |
| `bwrite`, `brelse`, `iunlock` | [[kernel/bio.c:110]], [[kernel/bio.c:120]], [[kernel/fs.c:326]] | the caller does not hold the buffer's or inode's sleep-lock ([[holdingsleep]]) |

A deadlock between two harts on two different locks has no such check: both harts spin with
interrupts off and stop for good, and the others soon follow as they need the same locks.

## Shared data with no lock {#unlocked}

A few shared variables are deliberately left without a lock, each for a stated reason.

* **`started`** ([[kernel/main.c:7]]): hart 0 sets it once boot is done; the other harts wait
  for it. It uses atomics instead of a lock: `__atomic_store_n(..., __ATOMIC_RELEASE)` compiles
  to `fence rw,w` + `sw` (`0x80000f0a`), and the waiting load to `lw` + `fence r,rw`
  (`0x80000e74`). That is enough for a one-way "ready" flag ([[g:atomic]]).
* **`panicking` and `panicked`** ([[kernel/printk.c:18-19]]): `volatile` flags written once
  each, read by [[printk]] and [[uartputc_sync]]. A lock here could be the very thing that is
  broken.
* **`static int first`** in [[forkret]] ([[kernel/proc.c:516]]): only the first process ever
  sees it as 1, and it clears it before any other process can exist.
* **`cpus[i]`**: each hart touches only its own entry, with interrupts off, so `noff`,
  `intena`, `proc` and `context` need no lock.
* **The process's private fields** (`kstack`, `sz`, `pagetable`, `trapframe`, `context`,
  `ofile`, `cwd`, `name`): "private to the process, so p->lock need not be held"
  ([[kernel/proc.h:95]]).
* **The process table, for [[procdump]]**, which reads it with no `p->lock` on purpose.

## How this was measured {#measured}

The counts on this page come from a copy of the kernel with a small recorder added to
[[acquire]], [[release]], [[push_off]], [[acquiresleep]], [[releasesleep]], [[sleep]] and
[[devintr]], and a call in [[procdump]] to print the results. The
xv6 source the site annotates was not changed. Spinlocks were tracked per hart, sleep-locks per
process. For each acquisition the recorder noted the lock's class (its name; a sleep-lock's
inner spinlock was named after its sleep-lock), every class already held, the `noff` reached,
and whether the hart was inside an interrupt handler. Separately it counted how often a process
went to sleep while holding each sleep-lock.

The workload, on three harts: boot, `ls | wc`, `usertests -q` (all tests passed), `stressfs`,
`forktest`, and `cat README | grep the | wc`, then one Ctrl-P to print the results.

The findings are in the sections they belong to: [order](#order), [nesting](#nesting),
[handlers](#handlers) and the [inventory](#inventory).

The limits: a measurement only sees the paths the workload exercised. Most edges predicted by
reading the code were observed; the ones that were not (lazy allocation, Ctrl-P at other
moments, error-path messages) are listed under [order](#order). [[tour:49]] watches every lock in one
`ls | wc`, and [[tour:51]] rebuilds the graph.

## What RISC-V provides {#riscv}

Everything above rests on a few hardware features.

**The A extension.** RISC-V's "A" (atomic) extension, part of `rv64gc` which xv6 is compiled
for, has two kinds of instruction:

* **AMOs** (atomic memory operations): `amoswap`, `amoadd`, `amoand`, `amoor`, `amoxor`,
  `amomin`, `amomax`, `amominu`, `amomaxu`, each in a 32-bit `.w` and a 64-bit `.d` form. One
  instruction reads a memory word, combines it with a register, writes the result back and
  returns the old value, with no other hart able to touch the word in between. xv6 uses exactly
  one AMO in the whole kernel: the `amoswap.w.aq` in [[acquire]].
* **LR/SC** (load-reserved / store-conditional): `lr.w` loads a word and registers a
  reservation on it; a later `sc.w` stores only if the reservation is still valid. It always
  fails if another hart has written the word since, and may fail for other reasons, so it
  reports success or failure in a register. A short loop of LR/SC can build any atomic
  read-modify-write, compare-and-swap included. xv6 needs none: a swap is all a spinlock needs.

**Ordering bits.** Every AMO and LR/SC has an `.aq` and an `.rl` bit ([above](#fence));
both together make it sequentially consistent. xv6's swap has `.aq` only (the encoding
`0x0cf4a7af` has bit 26 set and bit 25 clear).

**RVWMO and fences.** The base memory model, RVWMO, and `fence pred,succ` are described
[above](#fence). xv6 uses `fence rw,w` before releasing a lock and before setting `started`,
and `fence r,rw` after reading `started` (virtio_disk.c also uses full `fence`s for device
memory). Fence-then-store is the standard RISC-V mapping for a C11 release store.

**CSRs and wfi.** `csrrci` reads and clears in one instruction; [[intr_on]] and [[intr_off]]
are the immediate forms `csrsi`/`csrci` (pseudo-instructions for `csrrsi`/`csrrci` with no
destination). Traps, `sret` and `wfi` are covered [above](#sie).

Nothing in the hardware knows about locks, `noff` or `intena`. The spinlock, the counter and
the handoff are all conventions built by xv6 on top of one atomic swap, one fence and one
status bit. [[tour:15]] starts from the hardware, and [[tour:19]] follows memory ordering
across harts.

## Test yourself {#quiz}

<details><summary>A system call holds <code>pi->lock</code> and then calls <code>killed()</code>, which takes <code>p->lock</code>. What are SIE, noff and intena inside <code>killed</code>?</summary>

SIE 0, noff 2, intena 1. The `acquire(&pi->lock)` took noff from 0 to 1 while SIE was on
(interrupts were enabled at [[kernel/trap.c:66]]), so intena is 1; the inner acquire adds a
level without touching intena. When `pi->lock` is finally released, SIE comes back on.

</details>

<details><summary>In this tree, what does <code>p->chan != 0</code> tell you?</summary>

That the process has registered for a wakeup on that channel and no wakeup has cleared it yet.
It may be `SLEEPING`, or still `RUNNING` between [[sleep_prepare]] and [[sleep]], or even
`RUNNABLE` after [[kkill]], which leaves `chan` set.

</details>

## Where to go next {#next}

* [[tour:13]] (`swtch` and the handoff) and [[tour:15]] to [[tour:19]] (spinlocks, sleep and
  wakeup, sleep-locks, lock ordering, memory ordering).
* [[tour:41]] to [[tour:48]], whose steps show the interrupt strip next to the stack.
* [[tour:49]] to [[tour:52]], "Locks and interrupt state".
* [[concept:stacks]] and [[concept:mode-stack-page-table]].
