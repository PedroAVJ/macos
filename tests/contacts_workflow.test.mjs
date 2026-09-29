import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname;

test("Contacts preserves raw-card and verified-write boundaries", async () => {
  const skill = await readFile(join(root, "skills", "contacts", "SKILL.md"), "utf8");
  const source = await readFile(join(root, "cli", "contacts.swift"), "utf8");
  assert.match(skill, /choose the intended container explicitly/);
  assert.match(skill, /read the returned contact ID again/);
  assert.match(source, /unifyResults = false/);
  assert.match(source, /CNSaveRequest/);
  assert.doesNotMatch(source, /8674642606|8679052707|Fidel Velazquez|Calle Guti/);
});

test("Contacts exposes bounded inventory and name-based My Card relationships", async () => {
  const skill = await readFile(join(root, "skills", "contacts", "SKILL.md"), "utf8");
  const source = await readFile(join(root, "cli", "contacts.swift"), "utf8");
  assert.match(source, /CNContactRelationsKey/);
  assert.match(source, /label\.hasPrefix\("_\$!<"\)/);
  assert.match(source, /unifiedMeContactWithKeys/);
  assert.match(source, /command == "relationships"/);
  assert.match(source, /"linkage": "name_only"/);
  assert.match(source, /me_card_unavailable/);
  assert.match(source, /relationships takes zero arguments for My Card or one raw contact ID/);
  assert.match(source, /min\(max\(requestedLimit, 1\), 500\)/);
  assert.match(skill, /contains the relationship label and[\s\S]*not the related contact's persistent ID/);
  assert.match(skill, /never guess or write[\s\S]*fuzzy name match/);
});

test("Contacts adds exact directional relationships idempotently", async () => {
  const skill = await readFile(join(root, "skills", "contacts", "SKILL.md"), "utf8");
  const source = await readFile(join(root, "cli", "contacts.swift"), "utf8");
  const readme = await readFile(join(root, "README.md"), "utf8");

  assert.match(source, /command == "relationship"/);
  assert.match(source, /relationship add requires owner contact ID and related contact ID/);
  assert.match(source, /CNLabelContactRelationManager/);
  assert.match(source, /mutable\.contactRelations\.append/);
  assert.match(source, /status": "already_present"/);
  assert.match(source, /The saved relationship could not be read back/);
  assert.match(skill, /two exact raw contact IDs/i);
  assert.match(skill, /directional relationship/i);
  assert.match(readme, /boss` is accepted as an alias/i);
});

test("Contacts compounds verified emails additively and idempotently", async () => {
  const skill = await readFile(join(root, "skills", "contacts", "SKILL.md"), "utf8");
  const source = await readFile(join(root, "cli", "contacts.swift"), "utf8");
  const readme = await readFile(join(root, "README.md"), "utf8");

  assert.match(source, /command == "email"/);
  assert.match(source, /email add requires one raw contact ID/);
  assert.match(source, /mutable\.emailAddresses\.append/);
  assert.match(source, /The saved email address could not be read back/);
  assert.match(skill, /Compounding Default/);
  assert.match(skill, /directly from[\s\S]*authoritative first-party source/i);
  assert.match(skill, /Never infer a value[\s\S]*silently correct it/i);
  assert.match(readme, /additive and idempotent/i);
});

test("Contacts exposes E.164 phone candidates with normalization provenance", async () => {
  const skill = await readFile(join(root, "skills", "contacts", "SKILL.md"), "utf8");
  const source = await readFile(join(root, "cli", "contacts.swift"), "utf8");
  const readme = await readFile(join(root, "README.md"), "utf8");

  assert.match(source, /CNContactsUserDefaults\.shared\(\)\.countryCode/);
  assert.match(source, /case "MX": return \("52", 10\)/);
  assert.match(source, /trimmed\.hasPrefix\("\+"\)/);
  assert.match(source, /source = "default_country"/);
  assert.match(source, /"e164_source": source/);
  assert.match(skill, /preserves Apple's raw `value` and adds `e164`/i);
  assert.match(readme, /marked `default_country`/i);
});
