---
name: control-host
description: Inspect the current macOS control-host setup, including macOS, architecture, ADB, and scrcpy. Use when checking whether this Mac can control or inspect another device, or when comparing the live setup with the user's prior Mac host baseline.
---

# Mac Control Host

Inspect the live Mac first. The plugin contains no operator baseline. Compare
only an explicitly supplied prior snapshot; live output takes precedence
whenever they differ.

## Inspect

Run only the checks relevant to the question:

```bash
sw_vers
uname -m
command -v adb
adb version
command -v scrcpy
scrcpy --version
```

If comparison with a user-provided prior setup is useful, read
`../../context/mac-control-host.md` after collecting the live result.

## Boundaries

- Treat missing commands as a result; do not install anything unless the user asks.
- Do not start ADB, pair a device, connect to an endpoint, or launch scrcpy for
  a read-only inspection.
- Do not persist pairing codes, IP addresses, ports, device serials, credentials,
  or other secrets in public source or a plugin cache.
- Report whether each fact was measured live or came from the historical file.
