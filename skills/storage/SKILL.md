---
name: storage
description: Measure current Mac APFS headroom and the exact shortfall to a selected free-space target for a resource-hygiene decision. Use when the user asks what is consuming storage or what could be removed.
---

# Mac Storage

Own the live macOS and APFS measurement. Apply `toolchain:resource-hygiene` to
decide whether any measured item may be recommended for removal. Do not define
or weaken cleanup eligibility in this skill. If Toolchain is unavailable,
report the target and shortfall without inventing candidates.

Start read-only. A diagnostic or recommendation request is not deletion
authorization.

## Snapshot and target

```bash
<plugin-root>/scripts/snapshot.sh storage
```

Resolve `scripts/snapshot.sh` relative to the plugin root; from this skill file
it is `../../scripts/snapshot.sh`. Without the script:

```bash
df -Pk /System/Volumes/Data /System/Volumes/VM
diskutil apfs list | grep -E "Capacity (In Use|Not Allocated)"
```

Use exactly **20% free capacity** unless the user chooses another target:

```text
target_free = data_volume_capacity * selected_percentage
shortfall = max(0, target_free - current_available)
```

Do not add a safety buffer. At or above the target, report that no storage
removal is needed. Below it, report the exact shortfall.

## Candidate measurement

Give the target, shortfall, and live ownership context to
`toolchain:resource-hygiene` before measuring removal candidates. It owns the
candidate/no-candidate decision. Measure only exact targets that have passed
Toolchain's ownership and relevance gates, then return the measured size for its
materiality decision. Do not broaden the scan merely to make the arithmetic work.

For an exact target that passed those initial gates, use the narrowest applicable
read-only checks:

```bash
du -sk <exact-qualified-target>
lsof +D <exact-qualified-target>
```

When Git ownership is relevant, also inspect the repository's status, branches,
worktrees, remote publication, and task ownership. Return that evidence to
Toolchain rather than inferring disposability from size or regeneration alone.

Logical `du` size is only a projection. After separately authorized removal,
re-read `df -Pk /System/Volumes/Data` after each material exact target and stop
when the selected percentage is physically reached.

## Answer

Return only the target line and Toolchain-qualified actions:

```text
Storage target: <current free> -> <target free> (<percentage>); need <shortfall>
- <exact qualified target> — <measured size> — <proof and impact>
Total listed: <size>; projected target: <free space and percentage>
```

If nothing qualifies, return the target line followed by `Storage candidates:
none proven.` If qualified targets do not cover the shortfall, finish with the
exact remaining gap. Never manufacture a complete list.
