# Cleanup eligibility

The `memory` and `storage` skills measure; this reference decides whether a
measured item may appear in a cleanup recommendation at all. It does not
authorize deleting, quitting, restarting, or stopping anything. Recommendations
remain read-only until the user authorizes the exact action.

## Candidate gates

An item qualifies only when all of these are true:

1. The exact file, directory, application, or process tree exists now.
2. Its owner and purpose are known.
3. It is proven irrelevant to the user's current and intended workload.
4. Its removal or shutdown is material enough to matter, or it is clearly
   broken, runaway, or duplicated.
5. The exact action and user-visible impact are understood.

Failure of any gate means exclusion, not a lower ranking. A target, percentage,
pressure level, or desire to produce a non-empty answer never relaxes the gates.
If nothing qualifies, return no candidates.

## Preserve active work

Exclude every active repository, clone, worktree, build, simulator, bridge,
remote-control path, service, application, and its task-owned descendants.
Generated output inside an active worktree is active work too. Git-ignored
status, regenerability, age, low CPU, a version mismatch, or the absence of an
open file handle does not make it disposable. A resource created by a running
task belongs to that task until its closeout.

Do not recommend deleting cache state of any kind, including global, shared,
application, package-manager, build-system, dependency, or project-local
caches. Do not measure caches to fill a storage shortfall.

Do not use Trash as a destination, staging area, archive, or recommendation.
For an explicitly authorized exact disposable target, remove it permanently and
directly. If ownership, relevance, publication, or authorization is uncertain,
preserve the item in place and report the uncertainty.

## Processes

A process candidate must be running now, proven unrelated to intended work, and
large enough in aggregate to materially improve usable memory, unless it is
clearly broken or runaway. User-confirmed applications, simulators, bridges,
agents, browsers, remote sessions, and services are intended work; do not list
them because they are old, idle, numerous, or large. Do not clutter the answer
with small helpers or ordinary operating-system daemons. Prefer one graceful
operation on the exact owning application or root process.

## Answer shape

Return only qualifying actions. When none qualify, say so directly:

```text
Storage candidates: none proven.
Memory/process candidates: none proven.
```

When candidates qualify, include the exact target or process owner, measured
size or aggregate RSS, proof of irrelevance, exact action, and impact.
