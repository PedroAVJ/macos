---
name: memory
description: Measure current Mac RAM pressure, swap, compression, and process-owner trees for a resource-hygiene decision. Use when the user asks what is consuming memory, what could be quit, or whether processes have accumulated.
---

# Mac Memory

Own the live macOS measurement. Apply `toolchain:resource-hygiene` to decide
whether any measured process may be recommended for stopping. Do not define or
weaken cleanup eligibility in this skill. If Toolchain is unavailable, report
the measurements without inventing candidates.

Start read-only. A diagnostic request does not authorize quitting, restarting,
or killing anything.

## Snapshot

```bash
<plugin-root>/scripts/snapshot.sh memory
```

Resolve `scripts/snapshot.sh` relative to the plugin root; from this skill file
it is `../../scripts/snapshot.sh`. Without the script:

```bash
sysctl -n kern.memorystatus_vm_pressure_level
sysctl -n hw.memsize
sysctl vm.swapusage
vm_stat
ps -axo pid=,ppid=,etime=,pcpu=,pmem=,rss=,command=
df -h /System/Volumes/Data /System/Volumes/VM
```

The kernel pressure level is categorical:

| Level | State | Activity Monitor |
| --- | --- | --- |
| 0 | Normal | Green |
| 1 | Warning | Yellow |
| 2 | Urgent | Yellow |
| 3 | Critical | Red |
| 4 | Jetsam approaching | Internal severe state |

Pressure, swap, and compression establish urgency. They are not an optimization
score and do not define a required stopping target. Use three samples five
seconds apart only when distinguishing a transient burst from sustained
pressure matters. Level 3 or 4 warrants one concise warning, but never changes
cleanup eligibility or authorization.

Swap files share the APFS container. Low disk headroom raises OOM risk, but
reclaiming disk is a storage action and does not replace measuring RAM demand.

## Process-owner evidence

Aggregate descendants by owning application or top-level process. For each
material owner, capture the exact root PID, aggregate RSS, process count, elapsed
time, and current CPU. When needed, inspect parentage, CWD, open files, service
registries, or the owning control plane to establish what the tree is doing.

Pass those live facts and the user's stated workload to
`toolchain:resource-hygiene`. It owns the candidate/no-candidate result. This
skill owns only the Mac-specific evidence and pressure interpretation.

Never diagnose a memory leak from one snapshot. A leak requires observing one
PID or stable process family grow over time; many processes at one instant show
accumulation or workload pressure, not heap growth.

## Answer

Return the concise Toolchain-qualified process list, or its no-candidate result.
Do not add other processes merely because pressure remains elevated. When useful,
attach the current kernel level and aggregate RSS evidence to qualifying entries.
