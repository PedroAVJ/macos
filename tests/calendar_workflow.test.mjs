import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname;

test("Calendar retains deterministic event operations", async () => {
  const skill = await readFile(join(root, "skills", "calendar", "SKILL.md"), "utf8");
  assert.match(skill, /do not need Computer Use/);
  assert.match(skill, /read the returned UID back/);
});
