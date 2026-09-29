# Local host comparison notes

This plugin ships no operator host baseline. Measure the current Mac first.
If the user provides a prior diagnostic snapshot, compare only the requested
macOS version, architecture, tool availability, and versions, and label old
measurements as historical. Store any durable baseline in private user-owned
configuration outside Git, never in this plugin or an installed cache.

Do not store pairing codes, device serials, IP addresses, credentials, or other
private device details here.
