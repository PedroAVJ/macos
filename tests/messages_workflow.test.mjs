import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const skill = await readFile("skills/messages-inbox-hygiene/SKILL.md", "utf8");
const policy = await readFile("references/attention-policy.md", "utf8");

test("scheduled review is bounded and stateless", () => {
  assert.match(skill, /previous 24 hours/);
  assert.match(skill, /messages --json scan/);
  assert.match(skill, /stateless/);
  assert.match(skill, /metadata-only/);
});

test("source differences and zero mutation are explicit", () => {
  assert.match(skill, /source opt-out candidate/);
  assert.match(skill, /STOP\/BAJA/);
  assert.match(policy, /Never send, reply, react, forward, block, report, delete/);
  assert.match(policy, /Do not infer spam from frequency/);
});
