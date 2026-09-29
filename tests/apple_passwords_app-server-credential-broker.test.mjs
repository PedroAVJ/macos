import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import test from "node:test";

const root = fileURLToPath(new URL("..", import.meta.url));
const live = process.env.CREDENTIAL_BROKER_LIVE_TESTS === "1";
const liveReason = "set CREDENTIAL_BROKER_LIVE_TESTS=1 to create a synthetic Keychain item and run the GUI or Codex app-server path";
const broker = join(root, "runtime", "bin", "macbook-credential-broker");
const launcher = join(root, "scripts", "launch-credential-broker-mcp");
const installedBroker = join(
  homedir(),
  "Library",
  "Application Support",
  "MacBookCredentialBroker",
  "bin",
  "macbook-credential-broker",
);

function send(child, message) {
  child.stdin.write(JSON.stringify({ jsonrpc: "2.0", ...message }) + "\n");
}

function waitFor(queue, waiters, predicate, label, timeoutMs = 30000) {
  const index = queue.findIndex(predicate);
  if (index >= 0) return Promise.resolve(queue.splice(index, 1)[0]);
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error(`Timed out waiting for ${label}`));
    }, timeoutMs);
    waiters.push({
      predicate,
      resolve(value) {
        clearTimeout(timeout);
        resolve(value);
      },
    });
  });
}

async function closeChild(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.stdin.end();
  await new Promise((resolve) => {
    const timeout = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
      resolve();
    }, 5000);
    child.once("close", () => {
      clearTimeout(timeout);
      resolve();
    });
  });
}

test("signed Codex app-server runs the production broker synthetic path", { skip: live ? false : liveReason }, async () => {
  const config = `mcp_servers.macbook_credential_broker={command=${JSON.stringify(
    launcher,
  )},args=[],cwd=${JSON.stringify(root)},enabled=true,startup_timeout_sec=10,tool_timeout_sec=700}`;
  const child = spawn(
    "codex",
    ["app-server", "--stdio", "-c", config],
    {
      cwd: root,
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let appServerStderr = "";
  child.stderr.on("data", (chunk) => {
    appServerStderr += chunk.toString();
  });

  const queue = [];
  const waiters = [];
  const lines = createInterface({ input: child.stdout });
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
      id: 1,
      method: "initialize",
      params: {
        clientInfo: {
          name: "macbook-credential-broker-delivery-test",
          title: "MacBook Credential Broker Delivery Test",
          version: "1.0.0",
        },
        capabilities: {
          experimentalApi: true,
          requestAttestation: false,
          mcpServerOpenaiFormElicitation: false,
          extensions: {},
        },
      },
    });
    const initialized = await waitFor(
      queue,
      waiters,
      (message) => message.id === 1,
      "app-server initialize response",
    );
    assert.ok(initialized.result);
    send(child, { method: "initialized" });

    send(child, {
      id: 2,
      method: "thread/start",
      params: {
        cwd: root,
        ephemeral: true,
        environments: [],
        approvalPolicy: {
          granular: {
            sandbox_approval: false,
            rules: false,
            skill_approval: false,
            request_permissions: false,
            mcp_elicitations: true,
          },
        },
        approvalsReviewer: "user",
      },
    });
    const started = await waitFor(
      queue,
      waiters,
      (message) => message.id === 2,
      "ephemeral thread start response",
    );
    assert.ok(started.result?.thread?.id, JSON.stringify(started.error));
    const threadId = started.result.thread.id;

    send(child, {
      id: 3,
      method: "mcpServer/tool/call",
      params: {
        threadId,
        server: "macbook_credential_broker",
        tool: "run_credential_broker_self_test",
        arguments: {},
      },
    });
    const elicitation = await waitFor(
      queue,
      waiters,
      (message) =>
        message.method === "mcpServer/elicitation/request" || message.id === 3,
      "broker elicitation through signed Codex app-server",
    );
    assert.equal(
      elicitation.method,
      "mcpServer/elicitation/request",
      `Tool call returned before elicitation: ${JSON.stringify(elicitation)}`,
    );
    assert.equal(elicitation.params.serverName, "macbook_credential_broker");
    assert.equal(elicitation.params.threadId, threadId);
    assert.match(elicitation.params.message, /temporary fake Keychain secret/);
    assert.equal(elicitation.params.requestedSchema.properties.approve.type, "boolean");
    send(child, {
      id: elicitation.id,
      result: {
        action: "accept",
        content: { approve: true },
        _meta: null,
      },
    });

    const result = await waitFor(
      queue,
      waiters,
      (message) => message.id === 3,
      "production broker self-test result",
    );
    assert.equal(result.error, undefined, JSON.stringify(result.error));
    assert.equal(result.result.isError, undefined, JSON.stringify(result.result));
    assert.equal(result.result.structuredContent.passed, true);
    assert.equal(result.result.structuredContent.realCredentialUsed, false);
    assert.equal(result.result.structuredContent.secretReturned, false);
    assert.equal(result.result.structuredContent.temporaryItemDeleted, true);

    const identical = spawnSync("cmp", ["-s", broker, installedBroker]);
    assert.equal(identical.status, 0);
    const signature = spawnSync("codesign", ["--verify", "--strict", installedBroker], {
      encoding: "utf8",
    });
    assert.equal(signature.status, 0, signature.stderr);
  } catch (error) {
    throw new Error(`${error.message}\nApp-server stderr:\n${appServerStderr}`);
  } finally {
    await closeChild(child);
  }
});
