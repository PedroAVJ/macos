import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname;

test("Voice Memos retains independent scheduled workflows", async () => {
  const answer = await readFile(join(root, "skills", "answer-captured-questions", "SKILL.md"), "utf8");
  const health = await readFile(join(root, "skills", "discuss-health-observations", "SKILL.md"), "utf8");
  assert.match(answer, /^name: answer-captured-questions$/m);
  assert.match(health, /^name: discuss-health-observations$/m);
  for (const contents of [answer, health]) {
    assert.match(contents, /previous 24 hours/i);
    assert.match(contents, /stateless/i);
  }
});
