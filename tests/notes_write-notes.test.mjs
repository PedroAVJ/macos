import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  NotesWriteError,
  parseInvocation,
  runInvocation,
} from "../scripts/write_notes.mjs";

test("ordinary note text remains process arguments rather than script source", () => {
  const invocation = parseInvocation([
    "create",
    "--title",
    'Quarterly "review" & $(whoami)',
    "--body",
    "literal ${TOKEN} and `uname`",
  ]);
  let captured;
  const result = runInvocation(invocation, (command, args, options) => {
    captured = { command, args, options };
    return { status: 0, stdout: "OK\n", stderr: "" };
  });

  assert.equal(captured.command, "/usr/bin/osascript");
  assert.match(captured.args[0], /write_notes\.applescript$/);
  assert.equal(captured.args[1], "create");
  assert.equal(captured.args[2], invocation.title);
  assert.equal(captured.args[3], invocation.body);
  assert.equal(captured.options.encoding, "utf8");
  assert.equal(captured.options.timeout, 30_000);
  assert.deepEqual(result, {
    ok: true,
    title: invocation.title,
    native_checklist: false,
  });
});

test("UI script bypasses the sync-blocked Notes account dictionary", async () => {
  const source = await readFile(
    new URL("../scripts/write_notes.applescript", import.meta.url),
    "utf8",
  );
  assert.match(source, /application "System Events"/);
  assert.match(source, /ICMacTextViewAccessibilityActionMakeTodo/);
  assert.doesNotMatch(source, /tell application "Notes"/);
  assert.doesNotMatch(source, /default account|accounts of/i);
});

test("checklist stdin requires and preserves a JSON array of strings", () => {
  const invocation = parseInvocation(
    ["checklist", "create", "--title", "Packing", "--items-stdin", "--json"],
    '["Passport","Cargador USB-C"]',
  );
  assert.deepEqual(invocation.items, ["Passport", "Cargador USB-C"]);
  assert.equal(invocation.json, true);

  assert.throws(
    () => parseInvocation(
      ["checklist", "create", "--title", "Packing", "--items-stdin"],
      '["Passport",2]',
    ),
    /JSON array of strings/,
  );
});

test("writer never enumerates or accepts an account selector", () => {
  assert.throws(
    () => parseInvocation(["create", "--title", "Private", "--account", "iCloud"]),
    /intentionally unsupported/,
  );
});

test("native checklist result reports only title and item count", () => {
  const invocation = parseInvocation([
    "checklist",
    "create",
    "--title",
    "Packing",
    "--item",
    "Passport",
    "--item",
    "Medication",
  ]);
  const result = runInvocation(invocation, () => ({ status: 0, stdout: "OK\n", stderr: "" }));
  assert.deepEqual(result, {
    ok: true,
    title: "Packing",
    native_checklist: true,
    item_count: 2,
  });
});

test("permission failures name the host permission once and do not claim an account error", () => {
  const invocation = parseInvocation(["create", "--title", "Private"]);
  assert.throws(
    () => runInvocation(invocation, () => ({
      status: 1,
      stdout: "",
      stderr: "execution error: Accessibility access is required (-25211)\n",
    })),
    (error) => {
      assert.ok(error instanceof NotesWriteError);
      assert.match(error.message, /Grant Accessibility and Automation access/);
      assert.doesNotMatch(error.message, /iCloud|account/i);
      return true;
    },
  );
});

test("a real UI timeout is not mislabeled as a permission failure", () => {
  const invocation = parseInvocation(["create", "--title", "Private"]);
  assert.throws(
    () => runInvocation(invocation, () => ({
      error: Object.assign(new Error("spawnSync ETIMEDOUT"), { code: "ETIMEDOUT" }),
      status: null,
      stdout: "",
      stderr: "",
    })),
    /timed out while waiting for the live Notes window/,
  );
});
