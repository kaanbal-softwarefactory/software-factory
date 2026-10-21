import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

test("a new application copies source and provenance, never runtime data or dependencies", () => {
  const target = join(mkdtempSync(join(tmpdir(), "business-copy-")), "app");
  const created = spawnSync(
    process.execPath,
    [
      "scripts/create-copy.mjs",
      "--output",
      target,
      "--name",
      "business-example",
      "--preset",
      "barber",
    ],
    { encoding: "utf8" },
  );
  assert.equal(created.status, 0, created.stderr);
  assert.equal(existsSync(join(target, "app/page.tsx")), true);
  assert.equal(existsSync(join(target, "node_modules")), false);
  assert.equal(existsSync(join(target, ".next")), false);
  assert.equal(
    JSON.parse(readFileSync(join(target, "business.config.json"), "utf8"))
      .preset,
    "barber",
  );
  assert.equal(
    JSON.parse(readFileSync(join(target, "business.manifest.json"), "utf8"))
      .generated_from,
    "kaanbal-business-base@0.1.0",
  );
  assert.notEqual(
    spawnSync(
      process.execPath,
      ["scripts/create-copy.mjs", "--output", target],
      { encoding: "utf8" },
    ).status,
    0,
  );
});
test("the generator refuses to overwrite the reference or copy recursively into itself", () => {
  assert.notEqual(
    spawnSync(process.execPath, ["scripts/create-copy.mjs", "--output", "."], {
      encoding: "utf8",
    }).status,
    0,
  );
  assert.notEqual(
    spawnSync(
      process.execPath,
      ["scripts/create-copy.mjs", "--output", "app/recursive"],
      { encoding: "utf8" },
    ).status,
    0,
  );
});
