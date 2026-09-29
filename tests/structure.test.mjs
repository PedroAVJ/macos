import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import test from "node:test";

const json = (p) => JSON.parse(readFileSync(new URL(`../${p}`, import.meta.url), "utf8"));
const skills = ["answer-captured-questions", "calendar", "contacts", "control-host", "credential-authorization", "discuss-health-observations", "icloud-drive", "memory", "messages-inbox-hygiene", "messages-writing-samples", "notes", "passwords-autofill", "process-recorded-call", "reminders", "storage", "voice-memos"];

test("ships every former Apple plugin skill under macos", () => {
  assert.deepEqual(readdirSync(new URL("../skills", import.meta.url)).sort(), skills);
  for (const s of skills) {
    const md = readFileSync(new URL(`../skills/${s}/SKILL.md`, import.meta.url), "utf8");
    assert.match(md, new RegExp(`^name: ${s}$`, "m"), s);
  }
});

test("manifests agree and keep both MCP servers", () => {
  const claude = json(".claude-plugin/plugin.json");
  const codex = json(".codex-plugin/plugin.json");
  assert.equal(claude.name, "macos");
  assert.equal(codex.name, "macos");
  assert.equal(claude.version, codex.version);
  assert.equal(json("package.json").version, codex.version);
  assert.deepEqual(Object.keys(json(".mcp.json").mcpServers).sort(), ["apple-notes", "macbook-credential-broker"]);
  assert.ok(existsSync(new URL(`../${codex.interface.logo}`, import.meta.url)));
  for (const cli of ["contacts", "messages", "notes", "voice-memos"]) assert.ok(existsSync(new URL(`../bin/${cli}`, import.meta.url)), cli);
});
