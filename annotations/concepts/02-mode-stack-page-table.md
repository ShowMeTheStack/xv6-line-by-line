---
title: "Mode, stack and page table: the master question"
summary: At every instant each hart is in some privilege mode, on some stack, with some page table. The eight kinds of transition that change them, and every combination that occurs.
---
Stop xv6 at any instruction, pick any [[g:hart]], and ask three questions:

1. **Which [[g:privilege-mode]]?** User (U), supervisor (S) or machine (M). It decides which
   instructions and which memory the code may use.
2. **Which stack?** Whichever memory [[g:reg:sp|sp]] points into: a user stack, a kernel stack,
   the hart's boot or scheduler stack, or, briefly, none that may be used.
   [[concept:stacks]] describes each one.
3. **Which page table?** The one [[g:csr:satp|satp]] names: a process's user page table, the
   kernel page table, or none (paging off). It decides what every address means.

If you can answer all three at every step of a tour, you understand where you are. This page
shows how the answers change. Two more settings decide what happens *next*, so they appear in
the tables below as well: [[g:csr:stvec|stvec]], the address where the next trap in supervisor
mode will start, and the `SIE` bit of [[g:csr:sstatus|sstatus]], which says whether interrupts
can be taken in supervisor mode.

## Who changes what {#who}

The key to the whole page: **the hardware changes the mode; xv6's own instructions change the
stack and the page table.** A trap does not touch `sp` or `satp`, and neither do `sret` and
`mret`. So every transition is a short sequence of steps, and in between the three answers can
briefly disagree with each other.

| Setting | Changed by the hardware | Changed by xv6's code |
|---|---|---|
| mode | a trap (to S), `sret` (to the mode saved in `sstatus.SPP`), `mret` (to the mode saved in `mstatus.MPP`) | only through those instructions |
| `sp` | never | four instructions: [[kernel/entry.S:17]], [[kernel/trampoline.S:76]], [[kernel/swtch.S:26]], [[kernel/trampoline.S:118]] |
| `satp` | never | [[kernel/start.c:28]] (0), [[kvminithart]], [[kernel/trampoline.S:92]], [[kernel/trampoline.S:111]] |
| `stvec` | never | [[trapinithart]] and [[kernel/trap.c:47]] (to [[kernelvec]]), [[kernel/trap.c:112]] (to [[uservec]]) |
| `SIE` | a trap clears it (saving the old value in `SPIE`); `sret` restores it from `SPIE` | [[intr_on]], [[intr_off]], [[push_off]] / [[pop_off]] around every spinlock, and [[kerneltrap]]'s `w_sstatus` at [[kernel/trap.c:163]] |

When a trap is taken into supervisor mode, the hardware does exactly this: it saves the
`pc` in `sepc`, the reason in `scause` (and a faulting address, if any, in `stval`), the
previous mode in `sstatus.SPP`, copies `SIE` into `SPIE` and clears `SIE`, switches to
supervisor mode, and jumps to `stvec`. Every register, `sp` included, keeps its value.

{{fig:transitions-map|The places a hart can be, by privilege mode, and the eight kinds of transition between them. Each box's border shows the stack in use there; the two trampoline boxes are grey because part of each runs with no usable stack. Machine mode is visited only at boot.}}

## The eight transitions at a glance {#glance}

| | Transition | Trigger | Mode | Stack | Page table |
|---|---|---|---|---|---|
| [T1](#t1) | system call | `ecall` in user code | U → S | user → none (trap) → kernel ([[kernel/trampoline.S:76]] loads it; usable from [[kernel/trampoline.S:92]]) | user → kernel ([[kernel/trampoline.S:92]]) |
| [T2](#t2) | user exception | page fault, illegal instruction, … in user code | U → S | same as T1 | same as T1 |
| [T3](#t3) | device interrupt | UART or disk, through the [[g:plic|PLIC]], while in user mode | U → S | same as T1 | same as T1 |
| [T4](#t4) | timer interrupt | `time` reaches `stimecmp`, while in user mode | U → S | same as T1 | same as T1 |
| [T5](#t5) | return to user | [[usertrap]] returns, or [[forkret]] calls [[userret]] | S → U | kernel → none ([[kernel/trampoline.S:111]]) → user ([[kernel/trampoline.S:118]] loads it; usable from the `sret` on [[kernel/trampoline.S:153]]) | kernel → user ([[kernel/trampoline.S:111]]) |
| [T6](#t6) | context switch | [[sched]] or [[scheduler]] calls [[swtch]] | S → S | kernel ↔ scheduler ([[kernel/swtch.S:26]]) | kernel throughout |
| [T7](#t7) | kernel trap | an interrupt (or exception) while in supervisor mode | S → S | unchanged; a [[g:kernelvec-frame]] is pushed on it | unchanged |
| [T8](#t8) | boot | power-on | M → S | none → boot ([[kernel/entry.S:17]]), later boot → scheduler role | none → kernel ([[kvminithart]]) |

T3 and T4 also happen while the hart is in supervisor mode; then they arrive as T7. T6 follows
every `sleep` and `exit`; a timer interrupt (T4 or T7) is what forces a process that never
blocks to give up the hart.

## T1: system call {#t1}

A user program calls a system call stub such as `write` in [[user/usys.S]], which puts the call
number in `a7` and executes `ecall`. Follow the three answers:

| Step | Where | Mode | Stack | Page table |
|---|---|---|---|---|
| `ecall` | [[user/usys.S]] | U | user | user |
| trap: `sepc` = address of the `ecall`, `scause` = 8, `SPP` = U, `SIE` cleared, jump to `stvec` = [[uservec]] | hardware | **S** | none: `sp` still holds the user's value | user |
| user `a0` into `sscratch`; all user registers into the trapframe | [[kernel/trampoline.S:32-73]] | S | none | user |
| `ld sp, 8(a0)`: `sp` = top of the kernel stack | [[kernel/trampoline.S:76]] | S | **none**: `sp` holds a kernel-stack address the user page table does not map | user |
| `csrw satp, t1` | [[kernel/trampoline.S:92]] | S | **kernel** (usable from here) | **kernel** |
| `jalr t0`: call [[usertrap]] | [[kernel/trampoline.S:98]] | S | kernel | kernel |
| `stvec` = [[kernelvec]]; save `sepc` in the trapframe; `epc += 4`; `intr_on()` | [[kernel/trap.c:47-66]] | S | kernel | kernel |
| [[syscall]] runs the call | [[kernel/trap.c:68]] | S | kernel | kernel |

Throughout, the kernel stack starts empty: [[usertrap]]'s frame is the first thing on it.
Interrupts stay off until [[usertrap]] has saved `sepc` and switched `stvec`, because an
interrupt would overwrite `sepc`, `scause` and `sstatus`; for a system call they are turned
on at line 66, so a long system call can be interrupted ([T7](#t7)). The way back is [T5](#t5).
[[tour:5]], [[tour:7]] and [[tour:43]] follow this path step by step.

## T2: user exception {#t2}

The same entry as T1, through [[uservec]] onto the empty kernel stack and into
[[usertrap]], with a different `scause`. What [[usertrap]] does next depends on the cause:

* a load or store page fault (`scause` 13 or 15) at an address below the process size that
  is not mapped yet: [[vmfault]] allocates the page (lazy allocation, used by `sbrklazy`) and
  the program continues as if nothing had happened, through [T5](#t5);
* anything else (an illegal instruction, a fault on a guard page or an unmapped address, …):
  [[usertrap]] prints `unexpected scause`, marks the process killed, and calls [[kexit]] on its
  kernel stack. That process never returns to user mode; its hart goes to the scheduler
  through [T6](#t6).

Only the system-call branch of [[usertrap]] calls `intr_on()`, so an exception is handled
with interrupts off. [[tour:10]] covers faults.

## T3: device interrupt {#t3}

Again the T1 entry, with `scause` = `0x8000000000000009` (supervisor external interrupt).
[[devintr]] asks the PLIC which device interrupted, runs [[uartintr]] or
[[virtio_disk_intr]] on the process's kernel stack, and tells the PLIC it is done. The
interrupted process returns to user mode through [T5](#t5), usually unaware that anything
happened. Note whose kernel stack this is: the handler runs on the stack of *whichever process
happened to be running*, which is often not the process waiting for the device. The handler
does the minimum (passes typed characters to the console code, or marks a disk request
finished) and calls [[wakeup]]; the waiting process does the rest later, on its own stack.
[[tour:9]] and [[tour:44]] follow one interrupt.

## T4: timer interrupt {#t4}

[[kernel:start]] enabled the Sstc extension ([[timerinit]]), so each hart has a supervisor-mode
compare register, `stimecmp`. When the hart's `time` reaches it, the hart raises a supervisor
timer interrupt directly, with `scause` = `0x8000000000000005`. From user mode it arrives
through the T1 entry. [[devintr]] calls [[clockintr]], which on hart 0 advances [[ticks]] and
on every hart sets the next `stimecmp`, about a tenth of a second later; [[devintr]] then
returns 2.
[[usertrap]] then calls [[yield]] ([[kernel/trap.c:86]]), which starts [T6](#t6): the process
is suspended with `usertrap → yield → sched` on its kernel stack.

Machine mode plays no part. Older RISC-V xv6 versions had to take timer interrupts in machine
mode and pass them on; this one never enters machine mode after boot.
[[tour:11]] and [[tour:45]] follow a full time slice.

## T5: return to user {#t5}

The way out of every T1 to T4, and the way a new process reaches user mode for the first time.

| Step | Where | Mode | Stack | Page table |
|---|---|---|---|---|
| `intr_off()`; `stvec` = [[uservec]] | [[kernel/trap.c:108-112]] | S | kernel | kernel |
| fill the trapframe's kernel fields (`kernel_sp` = top of this kernel stack, …); `SPP` = U, `SPIE` = 1; `sepc` = saved user `pc` | [[kernel/trap.c:116-131]] | S | kernel | kernel |
| [[usertrap]] returns the user `satp` value; its `ret` lands in [[userret]] | [[kernel/trap.c:94]] | S | kernel (now empty) | kernel |
| `csrw satp, a0` | [[kernel/trampoline.S:111]] | S | **none**: `sp` holds a kernel-stack address | **user** |
| `ld sp, 48(a0)` | [[kernel/trampoline.S:118]] | S | **none**: `sp` holds the user's stack pointer, which supervisor code cannot use | user |
| restore the other registers; `sret`: `pc` = `sepc`, mode = U, `SIE` = `SPIE` | [[kernel/trampoline.S:153]] | **U** | **user** (usable from here) | user |

A process that has never run takes a shortcut: [[forkret]] calls [[prepare_return]] and then
jumps to [[userret]] through a function pointer ([[kernel/proc.c:542]]), from the top of its
fresh kernel stack. After `exec`, the same steps load the *new* program's `sp` and `pc`, which
[[kexec]] stored in the trapframe.

T5 mirrors T1 step for step: the trap makes the user stack unusable and line 92 makes the kernel
stack usable; line 111 makes the kernel stack unusable, line 118 loads the user's `sp`, and only
the `sret`, by changing the mode back to user, makes the user stack usable again. Supervisor code
cannot use user pages (`sstatus.SUM` is never set in this tree), so between lines 118 and 153
`userret` uses no stack, just as `uservec` uses none before line 76.

Interrupts are off from line 108 until the `sret`, for a reason the comment at
[[kernel/trap.c:105]] gives: from line 112 on, `stvec` points at [[uservec]], and an interrupt
taken in supervisor mode would go there, onto code that assumes it came from user mode. Once
in user mode, the supervisor interrupts enabled in `sie` are taken whatever `SIE` says (the
RISC-V rule for a mode less privileged than the interrupt's), and `SIE` itself is back to 1.

## T6: context switch {#t6}

Always between a process's kernel thread and the hart's scheduler, never directly between two
processes. Process A on hart 1 gives the hart to process B:

| Step | Where | Mode | Stack | Page table |
|---|---|---|---|---|
| A, holding `A->lock`, calls `swtch(&A->context, &mycpu()->context)` | [[kernel/proc.c:495]] in [[sched]] | S | A's kernel | kernel |
| `ld sp, 8(a1)` | [[kernel/swtch.S:26]] | S | **hart 1's scheduler** | kernel |
| `ret` into [[scheduler]] after its own `swtch` call; release `A->lock` | [[kernel/proc.c:456-463]] | S | scheduler | kernel |
| pick B, mark it `RUNNING`, call `swtch(&c->context, &B->context)` | [[kernel/proc.c:446-453]] | S | scheduler | kernel |
| `ld sp, 8(a1)` | [[kernel/swtch.S:26]] | S | **B's kernel** | kernel |
| `ret` into B's [[sched]] (or into [[forkret]] for a new process) | [[kernel/swtch.S:40]] | S | B's kernel | kernel |

The mode never changes, and neither does the page table: every kernel thread and every
scheduler runs with the kernel page table, so `swtch` has no reason to touch `satp`. B's user
page table is installed only later, in [T5](#t5). Interrupts are off throughout, because
`p->lock` is held from [[sched]]'s caller until the other side releases it. That handoff is
also what stops another hart from picking A while hart 1 is still on A's kernel stack.
[[tour:13]] and [[tour:45]] go through it line by line.

## T7: kernel trap {#t7}

A trap taken while the hart is already in supervisor mode goes to [[kernelvec]], because
[[usertrap]] (or [[trapinithart]], at boot) set `stvec` there.

| Step | Where | Mode | Stack | Page table |
|---|---|---|---|---|
| trap: `SPP` = S, `SIE` cleared, jump to [[kernelvec]] | hardware | S | unchanged: a kernel stack or the scheduler stack | kernel |
| `addi sp, sp, -256` and save 17 registers | [[kernel/kernelvec.S:14-35]] | S | same stack, frame pushed | kernel |
| [[kerneltrap]]: [[devintr]]; for a timer interrupt with a current process, [[yield]] | [[kernel/trap.c:149-158]] | S | same stack (and [T6](#t6) if it yields) | kernel |
| put back `sepc` and `sstatus`; restore registers; `addi sp, sp, 256`; `sret` | [[kernel/trap.c:162]], [[kernel/kernelvec.S:61-64]] | S | same stack, frame popped | kernel |

Nothing switches here: same mode, same stack, same page table. Only interrupts are
handled; an exception in kernel code means a kernel bug, and [[kerneltrap]] panics.
[[concept:stacks#same]] shows what the stack looks like with the frame on it, including the
case where the process yields and is later resumed on another hart. [[tour:8]] and
[[tour:44]] trace it.

## T8: boot {#t8}

| Step | Where | Mode | Stack | Page table |
|---|---|---|---|---|
| after a few instructions in QEMU's boot ROM at `0x1000`, each hart jumps to `0x80000000` | [[kernel/entry.S:7]] | M | none (`sp` = 0) | none (machine mode does not translate addresses) |
| `add sp, sp, a0` | [[kernel/entry.S:17]] | M | **boot** | none |
| [[kernel:start]]: previous mode = S, `mepc` = [[kernel:main]], `satp` = 0, delegate all traps to S, open PMP, start the timer, `tp` = hart ID | [[kernel/start.c:18-48]] | M | boot | none |
| `mret` | [[kernel/start.c:51]] | **S** | boot | none (`satp` = 0) |
| [[kvminithart]]; [[trapinithart]] sets `stvec` = [[kernelvec]] | [[kernel/main.c:21-24]] (hart 0), [[kernel/main.c:39-40]] (others) | S | boot | **kernel** |
| `scheduler()` | [[kernel/main.c:44]] | S | **scheduler** (same memory) | kernel |
| first `intr_on()` | [[kernel/proc.c:441]] | S | scheduler | kernel |

`mret` is the "return from a trap that never happened" ([[tour:46]]): [[kernel:start]] fills
in the registers a trap from supervisor mode would have left, and `mret` "returns" to
supervisor mode at [[kernel:main]]. After that, **machine mode is never entered again**:
`mtvec` and `mscratch` are never written in this tree, every exception that can occur in
supervisor or user mode, and every supervisor-level interrupt, is delegated to supervisor mode
([[kernel/start.c:31-32]]), machine-level interrupts are not delegatable on QEMU (their `mideleg` bits read back 0) and xv6 never enables
them, and the timer is a supervisor timer. Interrupts stay off until the scheduler's first `intr_on()`.
[[tour:2]] and [[tour:42]] walk through boot.

## Every combination that occurs {#table}

These are all the combinations of mode, stack and page table that exist at this commit, with
the trap vector and interrupt state that go with them:

| Mode | Active stack | Page table (`satp`) | `stvec` | Interrupts | Where |
|---|---|---|---|---|---|
| M | none: `sp` = 0, then `stack0`'s base, not yet usable | none: no translation in machine mode | not used | off | QEMU's boot ROM at `0x1000`, [[_entry]] before line 17 |
| M | boot | none: no translation in machine mode | not used | off | [[_entry]] from line 17, [[kernel:start]] |
| S | boot | 0 (off), then kernel | not set yet, then [[kernelvec]] | off | [[kernel:main]] |
| S | scheduler | kernel | [[kernelvec]] | off, except the window at [[kernel/proc.c:441-442]] | the scheduler loop; [[kerneltrap]] taken in that window |
| S | kernel | kernel | [[kernelvec]] | on during a system call while no spinlock is held; otherwise off | [[usertrap]], system calls, [[forkret]], [[kexit]], [[kerneltrap]] for a process |
| S | kernel | kernel | [[uservec]] | off | from [[kernel/trap.c:112]] to [[userret]]'s `csrw satp` |
| S | none: `sp` holds the user's value | user | [[uservec]] | off | [[uservec]] up to line 76; [[userret]] from line 118 to `sret` (line 153) |
| S | none: `sp` holds a kernel-stack address | user | [[uservec]] | off | [[uservec]] lines 76–92; [[userret]] lines 111–118 |
| U | user | user | [[uservec]] | on, whatever `SIE` says (only those enabled in `sie`: external and timer) | the user program |

Some combinations **never** occur, and each absence is a design decision:

* **U-mode on a kernel or scheduler stack.** The only way into user mode is the `sret` at
  [[kernel/trampoline.S:153]], after line 118 has loaded the user's `sp`.
* **C code on a user stack, or with a user page table.** The trampoline covers every moment
  where those are installed in supervisor mode, and it uses no stack.
* **The user's `sp` value with the kernel page table.** [[uservec]] changes `sp` before `satp`,
  and [[userret]] changes `satp` before `sp`, so the user's `sp` is only ever paired with the
  user page table.
* **A user page table on the scheduler stack.** The scheduler is reached only through `swtch`
  from kernel code, which always runs with the kernel page table.
* **Machine mode after boot.**
* **Two harts on one kernel stack**, or one hart on another hart's scheduler stack. See
  [[concept:stacks#harts]].

## Test yourself {#quiz}

<details><summary>A hart is in supervisor mode with <code>sp</code> = <code>0x3fffffe000</code> and a user page table in <code>satp</code>. Where is it?</summary>

In the trampoline, in one of the two windows where `sp` holds a kernel-stack address the user
page table does not map: [[uservec]] between lines 76 and 92, or [[userret]] between lines 111 and 118. `0x3fffffe000` is the top of `KSTACK(0)`,
so the process is the one in slot 0. (In [[userret]] the stack is back at its top because
[[usertrap]] has returned. After [[forkret]] it would be 48 bytes lower, below `forkret`'s
frame.)

</details>

<details><summary>Supervisor mode, <code>sp</code> = <code>0x80009810</code>. Which page table, and what is running?</summary>

Hart 1's scheduler loop, on its scheduler stack (hart 1's slice of [[stack0]]), with the kernel
page table. If `sp` were lower than that on the same slice, the hart would be inside a function
the scheduler calls ([[acquire]], [[release]]), or handling an interrupt taken in the loop's
window through [[kernelvec]] and [[kerneltrap]].

</details>

<details><summary>Can a hart be in user mode with the kernel page table installed?</summary>

No. [[userret]] installs the user page table at line 111, before the `sret` at line 153, and
every way into user mode goes through it. The reverse also holds: a trap from user mode keeps
the user page table until [[uservec]]'s line 92.

</details>

<details><summary>A timer interrupt arrives while hart 2 sits in the scheduler's interrupt window. Which stack does the handler use, and does the hart switch to a process?</summary>

[[kernelvec]] pushes its frame onto hart 2's scheduler stack, just below `0x8000a810`.
[[kerneltrap]] does not call [[yield]], because `myproc()` is 0 ([[kernel/trap.c:157]]). The
frame is popped and the loop continues; any process the interrupt made runnable is found by
the next scan.

</details>

<details><summary>Process A is suspended in <code>sleep</code>. Which page table will be installed when it resumes?</summary>

The kernel page table. A resumes inside the kernel, through `swtch` from some hart's
scheduler, and stays on the kernel page table until it returns to user mode through
[[userret]]. Its own user page table is installed only at [[kernel/trampoline.S:111]].

</details>
