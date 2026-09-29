#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const APPLESCRIPT_PATH = join(SCRIPT_DIR, "write_notes.applescript");
const MAX_TITLE_LENGTH = 2_000;
const MAX_BODY_LENGTH = 5 * 1024 * 1024;
const MAX_CHECKLIST_ITEMS = 500;
const MAX_CHECKLIST_ITEM_LENGTH = 10_000;

const CREATE_HELP = `Usage: notes create --title TITLE [--body TEXT | --stdin] [--json]

Create an ordinary Apple Note in the currently selected/default Notes folder.
The command drives Notes.app directly and never enumerates iCloud accounts.`;

const CHECKLIST_HELP = `Usage: notes checklist create --title TITLE (--item TEXT ... | --items-stdin) [--json]

Create native interactive checklist items in the currently selected/default
Notes folder. --items-stdin reads a JSON array of strings from stdin.`;

export class NotesWriteError extends Error {}

function takeValue(argv, index, option) {
  if (index + 1 >= argv.length) throw new NotesWriteError(`${option} requires a value`);
  return argv[index + 1];
}

function validateTitle(title) {
  if (!title) throw new NotesWriteError("--title is required");
  if (title.length > MAX_TITLE_LENGTH) throw new NotesWriteError("title is too long");
}

function parseCommon(argv, startIndex) {
  let title = "";
  let json = false;
  const rest = [];

  for (let index = startIndex; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--title") {
      title = takeValue(argv, index, token);
      index += 1;
    } else if (token === "--json") {
      json = true;
    } else if (token === "--account" || token === "--folder") {
      throw new NotesWriteError(
        `${token} is intentionally unsupported: the UI writer uses the currently selected/default Notes folder`,
      );
    } else {
      rest.push(token);
    }
  }

  validateTitle(title);
  return { title, json, rest };
}

export function parseInvocation(argv, stdinText = "") {
  if (argv.length === 0 || argv.includes("--help") || argv.includes("-h")) {
    const checklist = argv[0] === "checklist";
    return { help: checklist ? CHECKLIST_HELP : CREATE_HELP };
  }

  if (argv[0] === "create") {
    const { title, json, rest } = parseCommon(argv, 1);
    let body = "";
    let readStdin = false;

    for (let index = 0; index < rest.length; index += 1) {
      const token = rest[index];
      if (token === "--body") {
        if (readStdin || body !== "") throw new NotesWriteError("choose exactly one of --body or --stdin");
        body = takeValue(rest, index, token);
        index += 1;
      } else if (token === "--stdin") {
        if (readStdin || body !== "") throw new NotesWriteError("choose exactly one of --body or --stdin");
        readStdin = true;
      } else {
        throw new NotesWriteError(`unknown create option: ${token}`);
      }
    }

    if (readStdin) body = stdinText;
    if (body.length > MAX_BODY_LENGTH) throw new NotesWriteError("body is too long");
    return { operation: "create", title, body, json };
  }

  if (argv[0] === "checklist") {
    if (argv[1] !== "create") throw new NotesWriteError('expected "notes checklist create"');
    const { title, json, rest } = parseCommon(argv, 2);
    const items = [];
    let itemsFromStdin = false;

    for (let index = 0; index < rest.length; index += 1) {
      const token = rest[index];
      if (token === "--item") {
        if (itemsFromStdin) throw new NotesWriteError("choose --item or --items-stdin, not both");
        items.push(takeValue(rest, index, token));
        index += 1;
      } else if (token === "--items-stdin") {
        if (itemsFromStdin || items.length > 0) throw new NotesWriteError("choose --item or --items-stdin, not both");
        itemsFromStdin = true;
      } else {
        throw new NotesWriteError(`unknown checklist option: ${token}`);
      }
    }

    if (itemsFromStdin) {
      let decoded;
      try {
        decoded = JSON.parse(stdinText);
      } catch {
        throw new NotesWriteError("--items-stdin requires a JSON array of strings");
      }
      if (!Array.isArray(decoded) || decoded.some((item) => typeof item !== "string")) {
        throw new NotesWriteError("--items-stdin requires a JSON array of strings");
      }
      items.push(...decoded);
    }

    if (items.length === 0) throw new NotesWriteError("at least one checklist item is required");
    if (items.length > MAX_CHECKLIST_ITEMS) throw new NotesWriteError("too many checklist items");
    if (items.some((item) => item.length === 0)) throw new NotesWriteError("checklist items cannot be empty");
    if (items.some((item) => item.length > MAX_CHECKLIST_ITEM_LENGTH)) {
      throw new NotesWriteError("a checklist item is too long");
    }
    return { operation: "checklist", title, items, json };
  }

  throw new NotesWriteError(`unknown Notes write command: ${argv[0]}`);
}

function permissionAwareError(stderr) {
  const message = stderr.trim().replace(/^.*execution error:\s*/s, "").replace(/\s*\(-?\d+\)\s*$/, "");
  if (/not authorized|denied|Accessibility|Automation|-1743|-25211/i.test(stderr)) {
    return "macOS denied Notes UI automation to this host. Grant Accessibility and Automation access to Claude or Codex once, then retry.";
  }
  return message || "Notes UI automation failed";
}

export function runInvocation(invocation, spawn = spawnSync) {
  const args = invocation.operation === "create"
    ? [APPLESCRIPT_PATH, "create", invocation.title, invocation.body]
    : [APPLESCRIPT_PATH, "checklist", invocation.title, ...invocation.items];
  const result = spawn("/usr/bin/osascript", args, {
    encoding: "utf8",
    maxBuffer: 8 * 1024 * 1024,
    timeout: 30_000,
  });
  if (result.error?.code === "ETIMEDOUT") {
    throw new NotesWriteError("Notes UI automation timed out while waiting for the live Notes window");
  }
  if (result.error) throw new NotesWriteError(result.error.message);
  if (result.status !== 0) throw new NotesWriteError(permissionAwareError(result.stderr ?? ""));
  if ((result.stdout ?? "").trim() !== "OK") throw new NotesWriteError("Notes UI writer returned an unexpected result");

  return {
    ok: true,
    title: invocation.title,
    native_checklist: invocation.operation === "checklist",
    ...(invocation.operation === "checklist" ? { item_count: invocation.items.length } : {}),
  };
}

function main() {
  const wantsStdin = process.argv.includes("--stdin") || process.argv.includes("--items-stdin");
  const stdinText = wantsStdin ? readFileSync(0, "utf8") : "";
  let invocation;

  try {
    invocation = parseInvocation(process.argv.slice(2), stdinText);
    if (invocation.help) {
      process.stdout.write(`${invocation.help}\n`);
      return;
    }
    const result = runInvocation(invocation);
    if (invocation.json) process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    else process.stdout.write(`Created Apple Note "${invocation.title}"${invocation.operation === "checklist" ? " as a native checklist" : ""}.\n`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (invocation?.json || process.argv.includes("--json")) {
      process.stderr.write(`${JSON.stringify({ ok: false, error: message }, null, 2)}\n`);
    } else {
      process.stderr.write(`notes: ${message}\n`);
    }
    process.exitCode = 2;
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
