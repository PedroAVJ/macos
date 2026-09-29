import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";

const root = fileURLToPath(new URL("..", import.meta.url));
const cli = join(root, "scripts", "icloud-drive");

function run(args, driveRoot) {
  return spawnSync(cli, args, {
    encoding: "utf8",
    env: { ...process.env, ICLOUD_DRIVE_ROOT: driveRoot },
  });
}

test("copy-file verifies bytes and refuses a different overwrite", async () => {
  const fixture = await mkdtemp(join(tmpdir(), "icloud-plugin-"));
  const drive = join(fixture, "drive");
  await mkdir(drive);
  const source = join(fixture, "source.txt");
  await writeFile(source, "identity archive fixture\n");

  const first = run(["copy-file", source, "Records/Identity/source.txt"], drive);
  assert.equal(first.status, 0, first.stderr);
  assert.match(first.stdout, /copied and verified/);
  assert.equal(await readFile(join(drive, "Records", "Identity", "source.txt"), "utf8"), "identity archive fixture\n");

  const second = run(["copy-file", source, "Records/Identity/source.txt"], drive);
  assert.equal(second.status, 0, second.stderr);
  assert.match(second.stdout, /verified existing/);

  await writeFile(source, "different\n");
  const conflict = run(["copy-file", source, "Records/Identity/source.txt"], drive);
  assert.equal(conflict.status, 2);
  assert.match(conflict.stderr, /different contents/);
});

test("commands stay relative to the configured root", async () => {
  const fixture = await mkdtemp(join(tmpdir(), "icloud-plugin-"));
  const drive = join(fixture, "drive");
  await mkdir(drive);
  const escape = run(["status", "../outside"], drive);
  assert.equal(escape.status, 2);
  assert.match(escape.stderr, /relative to iCloud Drive/);
});
