import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { access, readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const read = (...parts) => readFile(join(root, ...parts), "utf8");

test("the broker MCP server keeps its durable identity", async () => {
  const mcp = JSON.parse(await read(".mcp.json"));
  assert.deepEqual(Object.keys(mcp.mcpServers).filter((name) => name !== "apple-notes"), ["macbook-credential-broker"]);
  const broker = mcp.mcpServers["macbook-credential-broker"];
  assert.equal(broker.type, "stdio");
  assert.equal(broker.command, "/bin/sh");
  assert.match(broker.args.join(" "), /launch-credential-broker-mcp/);

  const source = await read("native", "MacBookCredentialBroker.swift");
  assert.match(source, /keychainService = "com\.pedroavj\.macbook\.credential-broker"/);
  const build = await read("scripts", "build-credential-broker");
  assert.match(build, /--identifier com\.pedroavj\.macbook\.credential-broker/);
  for (const name of ["install-credential-broker", "launch-credential-broker-mcp"]) {
    assert.match(await read("scripts", name), /Application Support\/MacBookCredentialBroker/);
  }
  await access(join(root, "runtime", "bin", "macbook-credential-broker"));
});

test("credential authorization never gives the agent a secret-return path", async () => {
  const skill = await read("skills", "credential-authorization", "SKILL.md");
  const source = await read("native", "MacBookCredentialBroker.swift");
  assert.match(skill, /Never request, repeat, transcribe, reveal, export, log/);
  assert.match(skill, /Never run `security \.\.\. -w`/);
  assert.match(skill, /Never press Return/);
  assert.match(skill, /AXWebArea/);
  assert.match(skill, /fixed `macos-login`/);

  assert.match(source, /authorize_and_fill_credential/);
  assert.match(source, /kAXSecureTextFieldSubrole/);
  assert.match(source, /containsWebArea/);
  assert.match(source, /parentIsApprovedHost/);
  assert.match(source, /secretReturned": false/);
  assert.doesNotMatch(source, /"(?:get|read|reveal|export|copy)_credential"/);
  assert.doesNotMatch(source, /pbcopy|NSPasteboard|security find-generic-password/);
});

test("autofill routes native unlock to this plugin's broker", async () => {
  const skill = await read("skills", "passwords-autofill", "SKILL.md");
  assert.match(skill, /`credential-authorization` broker/);
  assert.doesNotMatch(skill, /macbook broker|macbook@/i);
});

test("credential broker scripts are valid shell", () => {
  for (const name of ["build-credential-broker", "install-credential-broker", "launch-credential-broker-mcp"]) {
    execFileSync("bash", ["-n", join(root, "scripts", name)]);
  }
});
