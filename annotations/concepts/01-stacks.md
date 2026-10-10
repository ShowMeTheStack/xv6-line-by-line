---
title: The stacks of xv6
summary: Which stack a hart is running on, what lives on each one, and the four instructions that switch between them.
---
Every C function needs a [[g:stack]]: memory for its local variables, the registers it must
preserve, and the address to return to. The register [[g:reg:sp|sp]] points at the current
top of that memory, and every call moves it further down. A [[g:hart]] (one CPU core) has
exactly one `sp`, so, apart from a few instructions at power-on and two short stretches in the
trampoline ([described below](#none)), at any instant it is running on exactly one stack:
whichever memory `sp` points into. We call that the hart's *active stack*.

This page answers two questions for every moment of xv6's life: **which stack is active, and
what changed it?** xv6 has three kinds of stack, plus a few instructions at power-on and two
short stretches in which `sp` points at nothing the running code may use:

| Kind | How many | Size | Virtual address | Created by | Guard page |
|---|---|---|---|---|---|
| [user stack](#user) | one per process | 1 page | just above the program in its user page table (`0x3000`–`0x3fff` for `init`) | [[kexec]] | yes: mapped, but `PTE_U` cleared |
| [kernel stack](#kernel) | one per proc slot: 64 | 1 page | [[KSTACK]]`(slot)`, high in the kernel page table (`0x3fffffd000` for slot 0) | [[proc_mapstacks]], once, at boot | yes: unmapped |
| [boot stack](#boot), which becomes the [scheduler stack](#scheduler) | one per hart | 4096 bytes | a slice of [[stack0]] at `0x80007890 + 4096 × hart` (virtual = physical) | the build: `stack0` is a global array in `.bss` | **none** |

The tour strip at the top of every tour step names the active stack with the same words, and
lines in the source view that move `sp` to another stack, or change a stack's role, carry a
⇄ mark in the line-number gutter. The companion page
[[concept:mode-stack-page-table]] adds the other two things you should always be able to name:
the privilege mode and the page table.

{{fig:stacks-sp-loop|One hart's `sp` on its way from one process to another. Process A is interrupted by a timer while in user mode, gives up the CPU, and the hart's scheduler resumes process B, which had been interrupted the same way earlier. Only three instructions move `sp` between stacks in this loop; every other change to `sp` is a function call or return within one stack.}}

## Four instructions move `sp` to another stack {#switches}

Function calls move `sp` all the time, but only *within* one stack: a function's first
instruction is usually `addi sp, sp, -N` and its last ones undo it. Moving `sp` to a
*different* stack is rare. In all of xv6 it happens at exactly four instructions:

| # | Instruction | Where | From → to | When |
|---|---|---|---|---|
| 1 | `add sp, sp, a0` | [[kernel/entry.S:17]] in [[_entry]] | nothing → boot stack | once per hart, at power-on |
| 2 | `ld sp, 8(a0)` | [[kernel/trampoline.S:76]] in [[uservec]] | user stack → the process's kernel stack (usable once `csrw satp` on line 92 installs the kernel page table) | every trap from user mode |
| 3 | `ld sp, 8(a1)` | [[kernel/swtch.S:26]] in [[swtch]] | kernel stack → scheduler stack (called from [[sched]]), or scheduler stack → kernel stack (called from [[scheduler]]) | twice per context switch |
| 4 | `ld sp, 48(a0)` | [[kernel/trampoline.S:118]] in [[userret]] | kernel stack → user stack (usable once `sret`, line 153, returns to user mode) | every return to user mode |

(Strictly, [[kernel/entry.S:12]], `la sp, stack0`, writes `sp` too, as the first step of
switch 1's calculation: it puts `stack0`'s base address in `sp`, and line 17 adds the hart's
offset. Only after line 17 does `sp` point at the top of a usable slice.)

Instructions 2 to 4 *load* `sp` from memory, so some earlier code must have written the right
value there. Knowing who wrote it is half of understanding each switch:

* Instruction 2 reads `trapframe->kernel_sp`, which [[prepare_return]] wrote the last time the
  process left the kernel ([[kernel/trap.c:117]]). It is always the top of the kernel stack.
* Instruction 3 reads `context.sp`. [[swtch]] itself saved it there ([[kernel/swtch.S:11]]) the
  last time that thread stopped; for a brand-new process, [[allocproc]] wrote it
  ([[kernel/proc.c:147]]).
* Instruction 4 reads `trapframe->sp`. [[uservec]] saved the user's value there on the way in
  ([[kernel/trampoline.S:41]]); after an `exec`, [[kexec]] replaced it with the new program's
  stack pointer ([[kernel/exec.c:137]]).

Some things look like stack switches and are not:

* **Traps, `mret` and `sret` never touch `sp`.** The hardware changes the privilege mode and the
  program counter, and nothing else that matters here. That is why [[uservec]] starts with the
  user's `sp` still in place (no longer usable, because supervisor code cannot use user pages),
  why [[userret]]'s `sret` ([[kernel/trampoline.S:153]]) makes the user stack loaded by switch 4
  usable again without moving `sp`, and why [[kernel:start]]'s `mret` ([[kernel/start.c:51]]) lands in
  [[kernel:main]] on the same boot stack.
* **[[kernel:main]] calling [[scheduler]]** ([[kernel/main.c:44]]) keeps the same memory. Only
  the stack's *role* changes, from boot stack to scheduler stack.
* **[[kernelvec]]** ([[kernel/kernelvec.S:14]]) pushes a 256-byte frame onto whatever stack is
  current. There is no separate interrupt stack. See [below](#same).

## Where the stacks live {#where}

{{fig:stacks-memory-map|Where the memory for each kind of stack comes from, and the virtual addresses `sp` holds while using it. The kernel-stack pages are ordinary free pages; only their virtual addresses have gaps between them. `stack0` is part of the kernel's `.bss` and has no gaps at all.}}

Three points in this map matter for the rest of the page:

* A **user stack** exists only in its own process's page table. Neither other processes nor the
  kernel page table have it at a user address. The kernel reaches it, when it must (for example
  to copy `argv` onto it), through its *physical* address, which the kernel page table maps at
  the same number (the [[g:direct-map]]).
* A **kernel stack** exists only in the kernel page table, never in a user page table. This is
  why [[uservec]] must switch page tables before it can push anything.
* **`stack0`** is mapped at its own physical address, like all kernel data. That is why it keeps
  working at the instant [[kvminithart]] turns paging on.

## The boot stack {#boot}

When QEMU starts, every hart runs a few instructions in QEMU's boot ROM at `0x1000` and then
jumps to `0x80000000` ([[kernel/entry.S]]), in machine mode with paging off, and with nothing useful in `sp`. C code cannot run yet: the first function call
would store its return address through a garbage pointer. [[stack0]] provides the memory: one
array of `4096 * NCPU` bytes declared in [[kernel/start.c:11]]. [[NCPU]] is 8, so the array is
32 KiB, one 4096-byte slice per hart, and the build places it at `0x80007890`
(`kernel/kernel.sym`). The Makefile starts QEMU with 3 harts (`CPUS := 3`), so only three
slices are ever used:

```text
stack0 in this build
  0x8000f890   end of stack0
               slices 3 to 7: never used with 3 harts
  0x8000a890   top of hart 2's slice  <- hart 2's first sp
  0x80009890   top of hart 1's slice  <- hart 1's first sp
  0x80008890   top of hart 0's slice  <- hart 0's first sp
  0x80007890   stack0 (start of hart 0's slice)
```

**Switch number 1** ([[kernel/entry.S:17]]) computes `sp = stack0 + (hartid + 1) * 4096`, the
top of the hart's own slice (stacks grow down, so the top is where they start). All the harts
run this line at about the same time, and each gets a different answer.

The boot stack then carries the hart through three stages without another switch:

1. [[_entry]] and [[kernel:start]] run in machine mode with paging off. `0x80008890` is a
   physical address.
2. `mret` ([[kernel/start.c:51]]) drops to supervisor mode and jumps to [[kernel:main]]. It does
   not touch `sp`.
3. In [[kernel:main]], [[kvminithart]] turns paging on ([[kernel/main.c:21]] on hart 0,
   [[kernel/main.c:39]] on the others). The next instruction still uses the same `sp`, and it
   still works, because the kernel page table maps `0x80008890` to physical `0x80008890`.

Hart 0 does almost all the work of booting on this stack: every initialization call in
[[kernel:main]], from [[consoleinit]] to [[userinit]], runs on it and returns. The other harts wait
for hart 0's signal and make a few short calls of their own.

Two frames are never popped. [[kernel:start]] never returns (it leaves with `mret`), so its
16-byte frame stays at the top of the slice; [[kernel:main]] never returns either, so its 16-byte
frame stays below that. With `gdb` you can see them on every hart for as long as the machine
runs.

## The scheduler stack {#scheduler}

[[kernel/main.c:44]] is an ordinary call: `scheduler();`. No instruction moves `sp` to another
stack. [[scheduler]]'s frame goes right below [[kernel:main]]'s, on the same slice, and because
`scheduler` never returns, that slice is from now on this hart's **scheduler stack**. It is the
same memory as the boot stack with a new role. xv6 allocates nothing else for it, and it is not
inside `struct cpu`.

In this build `scheduler`'s frame is 96 bytes, so inside the loop `sp` sits at a fixed spot:

```text
hart 0's scheduler stack (its slice of stack0)
  0x80008890   top
               start       16 bytes   left over from boot
               main        16 bytes   left over from boot
               scheduler   96 bytes
  0x80008810   <- sp in the scheduler loop; saved in cpus[0].context.sp
               about 3.9 KiB unused
  0x80007890   bottom, with no guard page below
```

(On hart 1 the loop's `sp` is `0x80009810`, on hart 2 `0x8000a810`. All three were read with
`gdb` from a running system.)

**Leaving it.** When the loop finds a `RUNNABLE` process, it calls
`swtch(&c->context, &p->context)` ([[kernel/proc.c:453]]). [[swtch]] stores `ra`, `sp`
(`0x80008810`) and `s0`–`s11` into `cpus[0].context`, then **switch number 3** loads the
process's saved `sp`. The scheduler's frame stays where it is, untouched, for as long as the
process runs.

**Coming back.** When the process gives up the hart, [[sched]] calls
`swtch(&p->context, &mycpu()->context)` ([[kernel/proc.c:495]]). Switch number 3 loads
`0x80008810` back, and `swtch`'s `ret` lands just after line 453, as if the call there had
returned normally.

Three facts follow from this:

* `cpus[i].context` is not the scheduler stack. It lives in the [[cpus]] array (at `0x8000f9d0`
  in this build) and holds a *pointer into* the stack, plus the scheduler's other saved
  registers. It is a [save area](#save-areas).
* A hart only ever switches to its *own* `mycpu()->context`, so no other hart ever runs on its
  scheduler stack.
* xv6 never switches from one process's kernel stack straight to another's. Every switch goes
  through a scheduler stack: process → scheduler in [[sched]], scheduler → process in
  [[scheduler]].

**Interrupts on the scheduler stack.** Each pass of the loop opens a short window with
interrupts enabled ([[kernel/proc.c:441-442]]). An interrupt that arrives
there, including one that woke the hart from `wfi`, lands on the scheduler stack: [[kernelvec]]
pushes its frame right below `scheduler`'s. Caught with `gdb` on hart 0: `sp` was `0x80008710`
(256 bytes below `0x80008810`) when [[kerneltrap]] started, and `sepc` pointed at the
instruction that turns interrupts back off. There is no current process at that moment, so
[[kerneltrap]] does not call [[yield]] ([[kernel/trap.c:157]]): the frame is popped and the loop
continues.

## Kernel stacks {#kernel}

A process needs a stack for the kernel code that runs on its behalf: system calls, page
faults, interrupts that arrive while it runs, and the work of being suspended and resumed. That
is its [[g:kernel-stack]]. The [[g:user-stack]] cannot serve. User code controls `sp` and may
have pointed it anywhere, and the program could read or change anything the kernel stored in
its memory.

**Where they are.** [[KSTACK]] in [[kernel/memlayout.h]] places stack *i* at
`TRAMPOLINE - (i + 1) * 2 * PGSIZE`. With [[TRAMPOLINE]] = `0x3ffffff000`:

```text
kernel page table, near the top of the address space
  0x3ffffff000   trampoline
  0x3fffffe000   (unmapped)
  0x3fffffd000   KSTACK(0)    slot 0's stack; its top is 0x3fffffe000
  0x3fffffc000   (unmapped)   guard page for slot 0
  0x3fffffb000   KSTACK(1)    top 0x3fffffc000
  0x3fffffa000   (unmapped)   guard page for slot 1
   ...
  0x3ffff7f000   KSTACK(63)   top 0x3ffff80000
  0x3ffff7e000   (unmapped)   guard page for slot 63
```

**Who creates them.** [[proc_mapstacks]], called once by [[kvmmake]] on hart 0's boot stack,
allocates 64 pages with [[kalloc]] and maps each at `KSTACK(i)`, readable and writable, not
executable, not accessible from user mode. In one boot of this build the pages were
`0x87f99000` (slot 0) down to `0x87f5a000` (slot 63): 64 physically adjacent pages. The guard
gaps exist only among the *virtual* addresses. (The [[g:direct-map]] also maps each of these
pages at its physical address, with no guard. xv6 never uses those addresses as `sp`.)

**Who owns them.** Slots, not processes. [[procinit]] sets `p->kstack = KSTACK(i)` once
([[kernel/proc.c:57]]), and nothing changes it again: [[allocproc]] and [[freeproc]] never touch
`kstack`, and the pages are never freed. When the process in slot 3 exits and a later process
gets slot 3, the new process runs on the same page. Whatever the old one left there is stale,
and harmless: the new process starts at the top and never reads below its own `sp`.

**Who switches to them.**

* **Switch number 2**, in [[uservec]], on every trap from user mode. It always loads the *top*,
  because [[prepare_return]] always writes `p->kstack + PGSIZE` into `kernel_sp`. So whenever a
  process is running in user mode, its kernel stack holds nothing of value.
* **Switch number 3**, in [[scheduler]]: to wherever the process stopped (the `sp` that
  [[sched]]'s `swtch` saved), or, for a process that has never run, to the top
  ([[kernel/proc.c:147]]).

**What lives on one.** During a system call, the frames of the kernel's C call chain, starting
with [[usertrap]]. Here is the shell, read with `gdb` while it waited for a key:

```text
sh (pid 2, slot 1), asleep inside read(): its kernel stack
  0x3fffffc000   top; trapframe->kernel_sp points here
                 usertrap       32 bytes   saved ra = 0x3ffffff09c (userret)
                 syscall        32 bytes
                 sys_read       48 bytes
                 fileread       48 bytes
                 consoleread    96 bytes
                 sleep          32 bytes
                 sched          48 bytes
  0x3fffffbeb0   <- p->context.sp, saved by swtch
                 3760 bytes unused
  0x3fffffb000   bottom; guard page below
```

Notice `usertrap`'s saved return address. [[uservec]] calls [[usertrap]] with `jalr t0`
([[kernel/trampoline.S:98]]), which puts the address of the next instruction in `ra`. That next
instruction is [[userret]], at `0x3ffffff09c` in the trampoline page, so when `usertrap` returns
it falls straight into the return-to-user path.

Most chains are this shallow. The deepest ones go through `exec`: [[sys_exec]] keeps the path
and an array of [[MAXARG]] argument pointers in its frame (480 bytes in this build), and
[[kexec]] another 32-entry array, `ustack` (544 bytes). In the [interrupt example
below](#same), the stack was nearly 1.9 KiB deep when the process gave up the hart.

## User stacks {#user}

**Who creates one.** [[kexec]], on every successful `exec` ([[kernel/exec.c:89-97]]).
After loading the program's segments it rounds the size up to a page boundary and allocates
`USERSTACK + 1` = 2 more pages ([[USERSTACK]] is 1). [[uvmclear]] clears `PTE_U` on the lower
one, which becomes the [[g:guard-page]]; the upper one is the stack. For `init` that gives:

```text
init's user stack right after kexec("/init")
  0x4000   top (= the process size, sz)
  0x3ff0   "/init\0"                    each string starts on a multiple of 16
  0x3fe0   argv[0] = 0x3ff0, argv[1] = 0
           <- sp = 0x3fe0; also in a1, and argc = 1 in a0
  0x3000   bottom of the stack page
  0x2000   guard page (PTE_U cleared)
  0x1000   data
  0x0000   text
```

The physical page is whatever [[kalloc]] returned (`0x87f4a000` for `init` in one boot).

**Building it is not using it.** While [[kexec]] fills in the new stack, the hart is running on
the process's *kernel* stack. The `sp` in [[kexec]] is a C variable, not the register, and the
arguments reach the new page through [[copyout]] and the new page table. Even the array
`ustack` (line 32) is a local variable on the kernel stack; it is copied to the user stack at
line 117. Nothing changes for the hart until [[kexec]] stores the final value in
`trapframe->sp` ([[kernel/exec.c:137]]), and even then the register gets it only on the way out.

**Who switches to it.** Only **switch number 4**, [[userret]]'s `ld sp, 48(a0)`
([[kernel/trampoline.S:118]]), moves `sp` to the user stack's address. From there until `sret`
([[kernel/trampoline.S:153]]) the hart is still in supervisor mode with the user page table, so
it cannot use that stack yet: supervisor code cannot access user pages (`sstatus.SUM` is never
set in this tree). The code only loads registers and pushes nothing, and tour strips say "no
usable stack" there. `sret` returns to user mode, and from then on the program uses the stack
as it likes. The kernel never relies on what the program does with `sp`: [[uservec]] saves whatever
value it finds and never stores anything through it.

**What protects it.** The stack is one page and does not grow. A program that needs more runs
into the guard page. The page is mapped, but without `PTE_U` a user-mode access faults;
[[usertrap]] asks [[vmfault]] whether this is a lazily allocated heap page, `vmfault` refuses
because the page is already mapped, and the process is killed. A single frame bigger than a
page could jump over the guard into the program's data; the guard only catches gradual
growth.

**fork and exit.** [[uvmcopy]] copies every page below `sz` into the child, the stack and the
guard page included, with their flags, so the child's guard keeps `PTE_U` cleared. The
child's saved `sp` is the parent's, because the trapframe is copied too: the same virtual
address, in the child's own copy. A user stack is freed with the rest of the user memory, by
[[freeproc]] when the parent's [[kwait]] collects the child.

## No usable stack {#none}

Twice on every round trip through the kernel, for a short stretch of the [[g:trampoline]], `sp`
holds a value that the code running may not use. Both stretches exist because the hardware
switches privilege mode at a trap or `sret`, while `sp` and `satp` must be switched by separate
instructions. Each stretch has two halves, split by the instruction that moves `sp`.

1. **[[uservec]], from its first instruction (line 22) to `csrw satp` at line 92.** A trap from
   user mode changes the mode and the program counter, not `sp` and not `satp`.
   * *Line 22 to line 76:* the hart is in supervisor mode with the user's `sp` and the user's
     page table, and supervisor code cannot use user pages. `uservec` pushes nothing: it frees
     `a0` by moving it into `sscratch` ([[kernel/trampoline.S:32]]) and saves every user
     register into the trapframe through `a0`.
   * *Line 76 to line 92:* switch number 2 loads the kernel-stack address, but the user page
     table is still installed and does not map kernel stacks, so nothing may be pushed until
     `csrw satp` switches to the kernel page table at [[kernel/trampoline.S:92]].

   Tour strips say "no usable stack" for this whole stretch and "kernel stack" from line 92 on.
2. **[[userret]], from `csrw satp` ([[kernel/trampoline.S:111]]) to `sret` ([[kernel/trampoline.S:153]]).**
   * *Line 111 to line 118:* the user page table is installed, and `sp` still holds a
     kernel-stack address it does not map. The code uses no stack.
   * *Line 118 to line 153:* switch number 4 has put the user's stack pointer in `sp`, but the
     hart is still in supervisor mode, which cannot use user pages, the same situation as the
     first half of `uservec`. The code keeps loading registers from the trapframe and pushes
     nothing.

   `sret` changes the mode to user, and only then is the user stack usable.

The second stretch mirrors the first: on the way in, the trap makes the user stack unusable
(line 22), line 76 loads the kernel-stack address, and line 92 makes it usable; on the way out,
line 111 makes the kernel stack unusable, line 118 loads the user's `sp`, and `sret` (line 153)
makes it usable.

Notice the order. On the way in, `sp` changes *before* `satp`; on the way out, `satp` changes
before `sp`. So the user's `sp` value is only ever paired with the user page table, and C code
only ever runs with a kernel `sp` and the kernel page table. The mismatched pair in between is
covered by a few lines of assembly that touch only registers and the trapframe. Interrupts are
off in both stretches: the trap cleared `SIE` on the way in, and [[prepare_return]] turned them
off ([[kernel/trap.c:108]]) before the way out.

## Interrupts borrow the current stack {#same}

A trap taken while the hart is already in supervisor mode goes to [[kernelvec]]: an interrupt
during a system call, or in the scheduler's interrupt window. (Traps from user mode go to
[[uservec]] instead and land on the empty kernel stack.) `kernelvec` has no stack of its own.
Its first instruction, `addi sp, sp, -256` ([[kernel/kernelvec.S:14]]), makes room on **the
stack that is already active**, and it saves 17 registers there: `ra`, `gp`, `t0`–`t2`,
`a0`–`a7` and `t3`–`t6`. That block is the [[g:kernelvec-frame]]. `s0`–`s11` are left out
because [[kerneltrap]], being C, preserves them; `sp` because the matching `addi` restores it;
`tp` for a reason we come to in a moment.

Depending on what was interrupted, the frame lands on one of two stacks:

* **A process's kernel stack**, for an interrupt during a system call ([[usertrap]] enables
  interrupts at [[kernel/trap.c:66]]). This one was caught with `gdb` while pid 2 was in the
  middle of `exec`ing the shell; it was still named `init`, because [[kexec]] renames the
  process only near the end:

  ```text
  pid 2 (slot 1), preempted by a timer interrupt in the middle of exec
    0x3fffffc000   usertrap
                   syscall
                   sys_exec      480 bytes
                   kexec         544 bytes
                   namei, namex, dirlookup, readi, brelse,
                   releasesleep, release, pop_off
                   kernelvec frame, 256 bytes   <- pop_off had just re-enabled interrupts
                   kerneltrap
                   yield                        <- sp = 0x3fffffb8d0 on entry to yield
                   sched
                   <- p->context.sp
  ```

* **The hart's scheduler stack**, for an interrupt in the scheduler's window, as
  [shown above](#scheduler).

**Yielding with a frame in the middle.** If the interrupt was the timer and the hart has a
current process, [[kerneltrap]] calls [[yield]] ([[kernel/trap.c:157]]), and the process is
suspended with the kernelvec frame in the middle of its kernel stack, exactly as in the picture.
Later, some hart's scheduler resumes it: `swtch` returns into [[sched]], [[yield]] returns,
[[kerneltrap]] puts back the `sepc` and `sstatus` it saved on entry ([[kernel/trap.c:162]]),
because other traps in the meantime will have overwritten those registers, and `kernelvec`
pops its frame and `sret`s into the interrupted code.

**Why `tp` is not restored.** The process may be resumed by a *different* hart. Its kernel
stack, and the kernelvec frame on it, go wherever the process goes, but `tp` holds the ID of
the hart, and [[swtch]] deliberately leaves it alone. When the process resumes on hart 2, `tp`
already says 2. Restoring the value saved on hart 0 would make [[cpuid]] wrong from then on,
which is the point of the comment at [[kernel/kernelvec.S:44]]. (For the same reason
`kernelvec` does not save it.)

**Never more than one.** The trap clears `SIE`, so `kernelvec` and [[kerneltrap]] run with
interrupts off. `kerneltrap` never turns them on, and a process that yields from it resumes
with them still off (the lock [[yield]] took was acquired with interrupts off, so releasing it
does not turn them on) until `kernelvec`'s `sret` restores the previous state. So in normal
operation interrupt handlers do not nest, and a stack holds at most one kernelvec frame.
Exceptions in kernel code are not handled at all: [[kerneltrap]] panics.

## Save areas are not stacks {#save-areas}

Four places hold registers while their owner is not running. None of them is a stack: no
frames, no pushing or popping, just fixed slots that are overwritten each time. The glossary
calls them [[g:save-area|save areas]].

| Save area | Where it lives | Written by | Read by | Holds |
|---|---|---|---|---|
| [[g:trapframe]] | its own page per process, from [[allocproc]]; at [[TRAPFRAME]] (`0x3fffffe000`) in the user page table, and at its physical address in the kernel | [[uservec]] (user registers), [[usertrap]] (`epc`), [[prepare_return]] (kernel fields), [[syscall]], [[kfork]], [[kexec]] | [[userret]], [[uservec]] (kernel fields), [[syscall]] (arguments) | 31 user registers, the user `pc`, and four values `uservec` needs |
| `p->context` | inside `struct proc`, in the [[proc]] array | [[swtch]] called from [[sched]]; [[allocproc]] for a new process | [[swtch]] called from [[scheduler]] | `ra`, `sp` and `s0`–`s11` of a suspended kernel thread |
| `cpus[i].context` | inside `struct cpu`, in the [[cpus]] array | [[swtch]] called from [[scheduler]] | [[swtch]] called from [[sched]] | the same 14 registers of hart *i*'s scheduler |
| [[g:csr:sscratch|sscratch]] | a CSR (a special register), one per hart | [[kernel/trampoline.S:32]] | [[kernel/trampoline.S:72]] | the user's `a0`, for about 35 instructions |

Two of these contain a value of `sp`: `trapframe->sp` points into the user stack,
`context.sp` into a kernel or scheduler stack. Holding a pointer into a stack does not make
something a stack.

One coincidence in the numbers: [[TRAPFRAME]] is `0x3fffffe000`, which is also the top of
`KSTACK(0)`. They never meet. The trapframe is mapped there only in user page tables, the
kernel stack only in the kernel page table, and the top of a stack is one past its last byte:
the first push goes to `0x3fffffdff8`.

## Where a suspended process lives {#suspended}

Put the pieces together for a process that is not running, say the shell waiting for a key:

{{fig:stacks-suspended|The shell, asleep in `read`. Everything needed to resume it is in three places: `p->context` (where its kernel thread stopped), its kernel stack (the C call chain), and its trapframe (the user registers, including the user `sp`). No hart is using any of them.}}

Resuming it takes all three, in order. Some hart's [[scheduler]] loads `p->context`, which
puts `sp` back at `0x3fffffbeb0` (switch 3). The functions on the kernel stack return one by
one, up to [[usertrap]], which returns into [[userret]]. `userret` loads `sp = 0x4f10` from the
trapframe (switch 4) and returns to user mode. [[tour:47]] follows this in detail.

## fork, exec and exit, seen from the stacks {#lifecycle}

**fork.** The parent runs [[kfork]] on its own kernel stack (`usertrap → syscall → sys_fork →
kfork`). The child gets:

* a **fresh, empty kernel stack**: its slot's page, with `context.ra = forkret` and
  `context.sp` = the top ([[kernel/proc.c:146-147]]). None of the parent's
  kernel frames are copied; the child never returns through `sys_fork`, `syscall` or `usertrap`;
* a **copy of the user stack**, made by [[uvmcopy]] along with the rest of user memory;
* a **copy of the trapframe** ([[kernel/proc.c:279]]), so its saved `sp` and `epc` match the
  parent's, with `a0` set to 0 so that `fork` returns 0 in the child. The copy also holds the
  parent's `kernel_sp`, which would be wrong for the child, but [[prepare_return]] rewrites it
  before the child can trap.

The child's first run: a scheduler's `swtch` loads the top of its kernel stack (switch 3) and
returns into [[forkret]], which therefore runs on an empty stack (`gdb` shows `sp` =
`0x3fffffe000` at its first instruction for pid 1, slot 0). `forkret` calls
[[prepare_return]] and then calls [[userret]] through a function pointer
([[kernel/proc.c:542]]); switch 4 moves `sp` to the user stack's address, and `sret` makes
that stack usable. `forkret`'s frame is abandoned,
never popped; the next trap starts again at the top and writes over it. For the very first
process, [[forkret]] also runs `fsinit` and `kexec("/init")` on this stack before returning
to user mode ([[kernel/proc.c:528-532]]).

**exec.** [[kexec]] runs on the calling process's kernel stack, and that stack, the slot and
the trapframe page are the same before and after. Only the user side is replaced. It builds a
complete new page table with a new user stack, as described [above](#user), while the old user
stack stays intact in the old page table, so a failure before the commit
([[kernel/exec.c:133]]) can still return -1 to the old program. At the commit it installs the
new page table, `epc` and `sp`, then frees the old image, old user stack included
([[kernel/exec.c:138]]). The system call returns through [[usertrap]] and [[userret]] as usual,
and switch 4 loads the *new* `sp`: the first instruction of the new program runs on the new
stack.

**exit.** [[kexit]] runs on the process's kernel stack (called from [[sys_exit]], or from
[[usertrap]] when the process has been killed). It closes files, hands children to `init`,
marks itself `ZOMBIE` and calls [[sched]], which never returns ([[kernel/proc.c:363]]). The
frames `usertrap → syscall → sys_exit → kexit → sched` stay on the kernel stack, and
`p->context` points into them, but nobody will ever resume them. A process could not free
the stack it is standing on, and it still needs it while `swtch` runs; xv6 sidesteps the
problem because kernel stacks belong to slots and are never freed. The parent, in [[kwait]],
calls [[freeproc]] ([[kernel/proc.c:398]]), which frees the trapframe and the user page table
with all user memory, the user stack included, and marks the slot `UNUSED`. The kernel stack
stays mapped, waiting for the slot's next process.

The parent cannot reach the zombie too early. The child holds its `p->lock` from [[kexit]]
through `swtch`, and its hart's scheduler releases that lock only after `swtch` has moved
`sp` off the child's stack ([[kernel/proc.c:463]]). [[kwait]] must acquire the same lock
before it can even see `ZOMBIE`.

## Three harts at once {#harts}

Each hart has its own `sp`, so with QEMU's three harts up to three stacks are active at the
same moment, one per hart. A typical snapshot (the addresses are real, the combination is
illustrative):

| Hart | Running | Mode | Active stack | Page table (`satp`) |
|---|---|---|---|---|
| 0 | its scheduler loop, nothing to run | S | hart 0's scheduler stack, `sp` = `0x80008810` | kernel |
| 1 | `sh` inside `read`, about to sleep | S | `sh`'s kernel stack, `KSTACK(1)` | kernel |
| 2 | `cat` copying a file | U | `cat`'s user stack | `cat`'s user page table |
| none | `init`, asleep in `wait` | | its frames wait on `KSTACK(0)`; no hart uses them | |

The rules that keep this safe:

* A scheduler stack is only ever used by its own hart.
* A kernel stack is used by at most one hart at a time: the hart running that process. The
  same stack can be used by different harts at different times, because a process can be
  resumed anywhere.
* The handoff of `p->lock` across `swtch` ([[tour:13]]) is what guarantees the second rule. The
  lock is held from the moment a process decides to stop until the scheduler on its hart has
  finished switching away. Until then, no other hart's [[scheduler]] can choose that process
  and load its `context.sp`, so two harts never run on one kernel stack.

At every instant, then, each hart has a privilege mode, an active stack and a page table, and
only these combinations occur at this commit:

| Mode | Active stack | Page table | When |
|---|---|---|---|
| M | none (`sp` = 0, then `stack0`'s base, not yet usable) | none (paging off) | QEMU's boot ROM at `0x1000`, [[_entry]] before line 17 |
| M | boot | none (paging off) | [[_entry]] from line 17, [[kernel:start]] |
| S | boot | none, then kernel | [[kernel:main]] before it calls [[scheduler]] |
| S | scheduler | kernel | the scheduler loop, and [[kerneltrap]] taken in its interrupt window |
| S | kernel | kernel | system calls, faults, interrupts and yields of a process; [[forkret]]; [[kexit]] |
| S | none (`sp` holds the user's value) | user | [[uservec]] until line 76, and [[userret]] from line 118 until `sret` (line 153) |
| S | none (`sp` holds a kernel-stack address) | user | [[uservec]] lines 76–92 and [[userret]] lines 111–118 |
| U | user | user | the program |

[[concept:mode-stack-page-table]] walks through how each of the eight kinds of transition
moves a hart from one row to another.

## Guard pages, and the stack that has none {#guards}

A stack that grows past its end silently overwrites whatever lies below it. A guard page turns
that into a fault.

* **User stacks**: the page below is mapped but has `PTE_U` cleared. An overflow faults in user
  mode and the process is killed ([see above](#user)).
* **Kernel stacks**: the page below each one is simply not mapped in the kernel page table. An
  overflow faults in supervisor mode. The result is a crash, not a clean one. The fault goes to
  [[kernelvec]], which tries to push its frame onto the same overflowed stack, which faults
  again, 256 bytes lower each time, until `sp` has passed the guard page. We tried it on a
  scratch copy of this build, adding a runaway recursion to `sys_write` for the shell (slot 1):

  ```text
  sp before 0x0000003fffffbf90
  scause=0xf sepc=0x8000560a stval=0x3fffffa000
  panic: kerneltrap
  ```

  `scause` 0xf is a store page fault. `sepc` is `sd t2, 48(sp)` *inside `kernelvec`* (the
  addresses are from the modified build; in the unmodified kernel this instruction is at
  `0x800055ba`), and
  `stval` is the lowest byte of slot 1's guard page: by then `sp` had already moved below the
  guard, and the frame's first few slots had landed in slot 2's stack page. The next attempt
  fitted entirely in slot 2's page, [[kerneltrap]] found a cause it does not handle, and
  panicked. So the guard page stopped the machine, but not before some writes reached the
  neighbouring kernel stack. Exceptions in the kernel are always fatal in xv6; the guard page
  makes sure an overflow is one of them.
* **The boot and scheduler stacks have no guard pages.** `stack0` is an ordinary array in
  `.bss`, mapped readable and writable along with the rest of the kernel's data, and its slices
  are not even page-aligned (`0x80007890`). A hart that overflows its slice writes into the top
  of the slice below it, where the hart below keeps its `start`, `main` and `scheduler` frames.
  Hart 0 would write into the variables just below `stack0`: [[ticks]] at `0x80007880`,
  [[initproc]] at `0x80007878`, [[kernel_pagetable]] at `0x80007870`. Nothing would fault. xv6
  gets away with it because the code that runs on these stacks is short and fixed: boot, the
  scheduler loop, and at most one interrupt handler on top.

## Common misconceptions {#misconceptions}

* **"xv6 has one kernel stack."** It has 64 process kernel stacks, one per slot, plus one
  boot-and-scheduler stack per hart.
* **"The scheduler has a stack of its own, inside `struct cpu`."** The scheduler runs on the
  hart's boot stack. `struct cpu` holds only `context`: saved registers, including a pointer
  into that stack.
* **"fork allocates a kernel stack and exit frees it."** All 64 are allocated at boot by
  [[proc_mapstacks]] and never freed. A process uses the one that belongs to its slot.
* **"A forked child starts with a copy of its parent's kernel stack."** It starts with an empty
  one and `ra = forkret`. The *user* stack is the copy.
* **"The trapframe and the context are stacks," or "the trapframe lives on the kernel
  stack."** They are [save areas](#save-areas) with fixed slots. The trapframe has a page of
  its own; the contexts live inside `struct proc` and `struct cpu`.
* **"swtch goes from process A to process B."** It always goes through a scheduler stack:
  A → scheduler in [[sched]], scheduler → B in [[scheduler]].
* **"An interrupt switches to an interrupt stack."** In supervisor mode, [[kernelvec]] pushes
  onto the current stack. From user mode, [[uservec]] moves to the process's own kernel stack.
* **"The hardware sets `sp` on a trap."** Traps, `sret` and `mret` never change `sp`. Four
  instructions in xv6's own code do.
* **"A process keeps kernel frames while it runs in user mode."** Its kernel stack is empty
  then; the next trap starts again at the top.
* **"`sp` and `ustack` in [[kexec]] are the user stack."** `sp` is a local variable and
  `ustack` a local array, both on the kernel stack. They describe the new user stack; the
  register reaches it only at [[userret]].
* **"A process always runs on the same hart."** Its kernel stack, kernelvec frame included,
  can be resumed by any hart. That is why `kernelvec` does not restore `tp`.
* **"Machine mode handles the timer."** Not in this tree. With the Sstc extension, timer
  interrupts go straight to supervisor mode; `mtvec` and `mscratch` are never written, and
  machine mode is never entered again after boot.
* **"`stack0` is only used during boot."** It is the scheduler stack until power-off.
* **"Guard pages make kernel stack overflow safe."** They make it loud. See the experiment
  above.

## Where to go next {#next}

* [[tour:2]] and [[tour:42]]: one hart's stacks from power-on to the first user instruction.
* [[tour:5]] and [[tour:7]]: the kernel stack and the trapframe during a system call.
* [[tour:8]]: traps taken inside the kernel, and the kernelvec frame.
* [[tour:11]], [[tour:12]] and [[tour:13]]: the timer, the scheduler stack and `swtch`.
* [[tour:20]], [[tour:21]] and [[tour:22]]: fork, exit and exec.
* [[tour:41]] to [[tour:48]], "The dance of privilege": every transition, with the stacks
  highlighted at every step. [[tour:47]] shows where a suspended process lives.
