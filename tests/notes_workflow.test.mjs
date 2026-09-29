import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname;

test("Notes retains both the call mechanism and semantic workflow", async () => {
  const mechanism = await readFile(join(root, "skills", "notes", "SKILL.md"), "utf8");
  const workflow = await readFile(join(root, "skills", "process-recorded-call", "SKILL.md"), "utf8");
  const cli = await readFile(join(root, "bin", "notes"), "utf8");
  assert.match(mechanism, /computer-use:computer-use/);
  assert.match(mechanism, /Claude/);
  assert.match(mechanism, /Shift\+Command\+L/);
  assert.match(mechanism, /native interactive checklist/);
  assert.match(mechanism, /notes create --title/);
  assert.match(mechanism, /notes checklist create/);
  assert.match(mechanism, /notes calls list --json/);
  assert.match(workflow, /notes calls path CALL_UUID/);
  assert.match(cli, /node .*write_notes\.mjs/);
  assert.doesNotMatch(cli, /python3 .*write_notes/);
});
