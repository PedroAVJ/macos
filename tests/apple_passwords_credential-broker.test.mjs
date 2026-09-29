import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import test from "node:test";

const root = fileURLToPath(new URL("..", import.meta.url));
const live = process.env.CREDENTIAL_BROKER_LIVE_TESTS === "1";
const liveReason = "set CREDENTIAL_BROKER_LIVE_TESTS=1 to create a synthetic Keychain item and run the GUI or Codex app-server path";
const broker = join(root, "runtime", "bin", "macbook-credential-broker");

function send(child, message) {
  child.stdin.write(JSON.stringify(message) + "\n");
}

function nextMatching(queue, waiters, predicate, label = "broker JSON-RPC message") {
  const index = queue.findIndex(predicate);
  if (index >= 0) return Promise.resolve(queue.splice(index, 1)[0]);
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      const waiterIndex = waiters.findIndex((entry) => entry.resolve === resolve);
      if (waiterIndex >= 0) waiters.splice(waiterIndex, 1);
      reject(new Error(`Timed out waiting for ${label}`));
    }, 15000);
    waiters.push({
      predicate,
      resolve(value) {
        clearTimeout(timeout);
        resolve(value);
      },
    });
  });
}

function waitForClose(child) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
  return new Promise((resolve) => child.once("close", resolve));
}

test("broker ships as a signed universal binary", () => {
  const version = spawnSync(broker, ["--version"], { encoding: "utf8" });
  assert.equal(version.status, 0);
  assert.equal(version.stdout.trim(), "1.0.0");

  const architectures = spawnSync("lipo", ["-archs", broker], { encoding: "utf8" });
  assert.equal(architectures.status, 0);
  assert.match(architectures.stdout, /arm64/);
  assert.match(architectures.stdout, /x86_64/);

  const signature = spawnSync("codesign", ["--verify", "--strict", broker], {
    encoding: "utf8",
  });
  assert.equal(signature.status, 0, signature.stderr);
});

test("synthetic Keychain and secure-field path passes without a real credential", { skip: live ? false : liveReason }, async () => {
  const testDirectory = mkdtempSync(join(tmpdir(), "macbook-broker-self-test-"));
  const testBroker = join(testDirectory, "macbook-credential-broker-test");
  const architecture = process.arch === "arm64" ? "arm64" : "x86_64";
  try {
    const compile = spawnSync(
      "xcrun",
      [
        "swiftc",
        "-D",
        "BROKER_SELF_TEST_BUILD",
        "-parse-as-library",
        "-O",
        "-target",
        `${architecture}-apple-macos13.0`,
        join(root, "native", "MacBookCredentialBroker.swift"),
        "-framework",
        "AppKit",
        "-framework",
        "ApplicationServices",
        "-framework",
        "Security",
        "-o",
        testBroker,
      ],
      { encoding: "utf8" },
    );
    assert.equal(compile.status, 0, compile.stderr);
    const sign = spawnSync(
      "codesign",
      [
        "--force",
        "--sign",
        "-",
        "--identifier",
        "com.pedroavj.macbook.credential-broker.self-test",
        testBroker,
      ],
      { encoding: "utf8" },
    );
    assert.equal(sign.status, 0, sign.stderr);

    const child = spawn(testBroker, ["mcp"], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    let brokerStderr = "";
    child.stderr.on("data", (chunk) => {
      brokerStderr += chunk.toString();
    });
    const lines = createInterface({ input: child.stdout });
    const queue = [];
    const waiters = [];
    lines.on("line", (line) => {
      const message = JSON.parse(line);
      const waiterIndex = waiters.findIndex((entry) => entry.predicate(message));
      if (waiterIndex >= 0) {
        const [waiter] = waiters.splice(waiterIndex, 1);
        waiter.resolve(message);
      } else {
        queue.push(message);
      }
    });

    try {
      send(child, {
        jsonrpc: "2.0",
        id: 10,
        method: "initialize",
        params: {
          protocolVersion: "2025-06-18",
          capabilities: { elicitation: { form: {} } },
          clientInfo: { name: "macbook-self-test", version: "1.0.0" },
        },
      });
      await nextMatching(queue, waiters, (message) => message.id === 10, "self-test initialize response");
      send(child, { jsonrpc: "2.0", method: "notifications/initialized" });
      send(child, {
        jsonrpc: "2.0",
        id: 11,
        method: "tools/call",
        params: { name: "run_credential_broker_self_test", arguments: {} },
      });
      const elicitation = await nextMatching(
        queue,
        waiters,
        (message) => message.method === "elicitation/create",
        "self-test elicitation request",
      );
      assert.match(elicitation.params.message, /temporary fake Keychain secret/);
      send(child, {
        jsonrpc: "2.0",
        id: elicitation.id,
        result: { action: "accept", content: { approve: true } },
      });
      const result = await nextMatching(queue, waiters, (message) => message.id === 11, "self-test tool result");
      assert.equal(result.result.isError, undefined, result.result.content[0].text);
      assert.equal(result.result.structuredContent.passed, true);
      assert.equal(result.result.structuredContent.realCredentialUsed, false);
      assert.equal(result.result.structuredContent.secretReturned, false);
      assert.equal(result.result.structuredContent.temporaryItemDeleted, true);
    } catch (error) {
      throw new Error(`${error.message}\nBroker stderr:\n${brokerStderr}`);
    } finally {
      child.stdin.end();
      await waitForClose(child);
    }
  } finally {
    rmSync(testDirectory, { recursive: true, force: true });
  }
});

test("MCP approval works while sensitive calls reject an untrusted launcher", async () => {
  const child = spawn(broker, ["mcp"], {
    stdio: ["pipe", "pipe", "pipe"],
  });
  const lines = createInterface({ input: child.stdout });
  const queue = [];
  const waiters = [];
  lines.on("line", (line) => {
    const message = JSON.parse(line);
    const waiterIndex = waiters.findIndex((entry) => entry.predicate(message));
    if (waiterIndex >= 0) {
      const [waiter] = waiters.splice(waiterIndex, 1);
      waiter.resolve(message);
    } else {
      queue.push(message);
    }
  });

  try {
    send(child, {
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-06-18",
        capabilities: { elicitation: { form: {} } },
        clientInfo: { name: "macbook-test", version: "1.0.0" },
      },
    });
    const initialized = await nextMatching(queue, waiters, (message) => message.id === 1);
    assert.equal(initialized.result.serverInfo.name, "macbook-credential-broker");
    send(child, { jsonrpc: "2.0", method: "notifications/initialized" });

    send(child, { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
    const listed = await nextMatching(queue, waiters, (message) => message.id === 2);
    const names = listed.result.tools.map((tool) => tool.name);
    assert.ok(names.includes("authorize_and_fill_credential"));
    assert.ok(names.includes("test_credential_approval_channel"));
    assert.ok(names.includes("run_credential_broker_self_test"));
    assert.ok(!names.some((name) => /read|reveal|export|copy/.test(name)));

    send(child, {
      jsonrpc: "2.0",
      id: 3,
      method: "tools/call",
      params: { name: "test_credential_approval_channel", arguments: {} },
    });
    const elicitation = await nextMatching(
      queue,
      waiters,
      (message) => message.method === "elicitation/create",
    );
    assert.match(elicitation.params.message, /No-secret/);
    assert.deepEqual(Object.keys(elicitation.params.requestedSchema.properties), ["approve"]);
    send(child, {
      jsonrpc: "2.0",
      id: elicitation.id,
      result: { action: "accept", content: { approve: true } },
    });
    const approvalResult = await nextMatching(queue, waiters, (message) => message.id === 3);
    assert.equal(approvalResult.result.structuredContent.approved, true);
    assert.equal(approvalResult.result.structuredContent.secretRead, false);
    assert.equal(approvalResult.result.structuredContent.externalActionPerformed, false);

    send(child, {
      jsonrpc: "2.0",
      id: 4,
      method: "tools/call",
      params: {
        name: "authorize_and_fill_credential",
        arguments: { credential: "macos-login", purpose: "contract test" },
      },
    });
    const denied = await nextMatching(queue, waiters, (message) => message.id === 4);
    assert.equal(denied.result.isError, true);
    assert.match(denied.result.content[0].text, /signed Codex or Claude host/);
    assert.equal(denied.result.structuredContent.secretReturned, false);
  } finally {
    child.stdin.end();
    await waitForClose(child);
  }
});
