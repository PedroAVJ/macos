---
name: contacts
description: Read and manage live Apple Contacts on macOS through the bundled Contacts-framework CLI. Use for contact lookup, relationship discovery and exact relationship additions, bounded inventories, account/container disambiguation, exact contact reads, adding verified email addresses, and adding or removing postal addresses without visual automation.
---

# Apple Contacts

Use `scripts/contacts.sh --json ...` from this skill directory. The command
reads and writes the live macOS Contacts store through Apple's public Contacts
framework; it does not keep a second contact database or store contact data in
the plugin.

## Commands

| Operation | Command |
| --- | --- |
| Check access and containers | `scripts/contacts.sh --json doctor` |
| List raw contact references | `scripts/contacts.sh --json list [--container NAME] [--limit 100] [--offset 0]` |
| Search by name, nickname, phone, email, or organization | `scripts/contacts.sh --json search QUERY [--container NAME]` |
| Read one raw contact card | `scripts/contacts.sh --json read CONTACT_ID` |
| Read the unified My Card | `scripts/contacts.sh --json me` |
| Discover My Card relationships | `scripts/contacts.sh --json relationships` |
| Discover one raw card's relationships | `scripts/contacts.sh --json relationships CONTACT_ID` |
| Add an exact relationship | `scripts/contacts.sh --json relationship add OWNER_CONTACT_ID RELATED_CONTACT_ID --label manager` |
| Add a verified email address | `scripts/contacts.sh --json email add CONTACT_ID --label home --value EMAIL` |
| Add a postal address | `scripts/contacts.sh --json address add CONTACT_ID --label home --street STREET --city CITY --state STATE [--postal-code CODE] --country COUNTRY --country-code ISO_CODE` |
| Remove one postal address | `scripts/contacts.sh --json address remove CONTACT_ID ADDRESS_ID --confirm` |

## Relationship Model

Apple stores each relationship as a labeled, directional value on one card. A
My Card entry such as `sister -> Jane Doe` contains the relationship label and
the related person's name, but not the related contact's persistent ID. It does
not automatically create the inverse relationship on Jane's card.

Use `relationships` as the discovery front door. It reads the unified My Card,
then exact-matches each related name against raw contact names and nicknames.
Treat `unmatched` and `ambiguous` results as review items; never guess or write
based on a fuzzy name match.

If Apple does not expose a unified My Card, set the correct card as My Card in
Contacts. Until then, pass an exact raw card ID to `relationships`; never infer
which card represents the user.

`read` exposes structured identity, work, communication, address, date,
relationship, and image-availability fields. Notes are intentionally excluded:
modern Apple platforms protect note access with a restricted entitlement.

Each phone entry preserves Apple's raw `value` and adds `e164`, `e164_source`,
and `default_country_code`. `e164_source: explicit` means the stored value
included `+`; `explicit_legacy_mexico` means stored `+521` was canonicalized to
current `+52`; `default_country` means the national number was expanded using
`CNContactsUserDefaults` for this Mac; and `unavailable` means the plugin could
not safely normalize the format. Treat the source as provenance rather than
rewriting the live contact.

Use Contacts as the durable identity and connection index. Keep narrative
history, sensitive dossiers, inferred traits, and changing context in the
system that owns those records rather than flattening them into contact fields.

### Compounding Default

When an in-scope workflow obtains a durable contact coordinate directly from
the person or another authoritative first-party source, resolve the exact raw
card and check whether the verified value is already present. Add a missing
supported value during the same workflow instead of leaving it only in a chat,
calendar invitation, or other transient source. The bundled additive capture
commands currently support email addresses and postal addresses.

This standing default authorizes additive capture only. Never infer a value,
silently correct it, overwrite or remove an existing value, merge cards, or
cross account containers. If the value is uncertain or a correction could
change the person's identity or delivery route, ask before saving it. When the
user explicitly approves a corrected exact value, save only that approved
value and preserve every existing value.

Relationship addition takes two exact raw contact IDs: the owner card that will
store the directional relationship and the related contact whose current full
name becomes the relationship value. The standard `manager` label is also
accepted as `boss` and stored using Apple's manager relationship label. The
operation is idempotent and reads the owner card back before reporting success.
Never add a relationship from a display-name-only or fuzzy match.

Resolve the skill directory from the installed plugin rather than assuming a
developer checkout path. A verified `contacts` command shim may be used when
available.

## Raw Cards and Containers

Contacts can link cards from iCloud, Google, and other accounts into one person
in the UI. Search deliberately returns the raw cards with their persistent IDs
and container names so writes can target the intended account.

1. Use a bounded `list` page or search using a durable identifier such as a
   complete phone number or a sufficiently specific name.
2. If more than one card matches, choose the intended container explicitly.
   Prefer iCloud for Apple-owned personal contact data unless the user says
   otherwise.
3. Read the chosen raw ID before writing. Do not use a display name alone as a
   write identity.

## Write Contract

Email addition requires one exact raw contact ID and an exact verified value.
It is idempotent across labels: if the normalized email already exists, the
command returns `already_present`; otherwise it appends the requested label and
reads the card back before reporting `added`. Email addition never replaces a
different address and never guesses a typo correction.

The user's exact request to add a relationship authorizes that addition to the
resolved owner card. Read both raw cards first, preserve their container
identities, and use `relationship add` only when both IDs are exact. After the
write, verify the relationship label and related name on the returned owner
card. Relationship values are directional; this command does not write an
inverse label onto the related person's card.

The user's exact request to add an address authorizes that addition to the
resolved card. Stop before writing when the person or account container remains
ambiguous.

Address addition is idempotent: an exact existing address returns
`already_present`. A different address with the same label returns a conflict
instead of overwriting it. Resolve the conflict with the user rather than
silently replacing data.

After a write, read the returned contact ID again and verify the address ID,
label, street, city, state, postal code, country, and country code. Do not
report completion from the save request alone.

Address removal is destructive. Read the exact contact and address ID first,
then use `--confirm`. Never remove all addresses or a whole contact by
inference.

Treat contact values as private. Keep them out of plugin source, public
searches, public documents, outbound messages, and logs unless the user
explicitly authorizes that disclosure.
