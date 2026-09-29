import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname;

test("Reminders retains deterministic EventKit-gap UI scripting", async () => {
  const skill = await readFile(join(root, "skills", "reminders", "SKILL.md"), "utf8");
  assert.match(skill, /Use `remindctl` for public EventKit fields/);
  assert.match(skill, /AppleScript UI scripting through `System Events`/);
});
