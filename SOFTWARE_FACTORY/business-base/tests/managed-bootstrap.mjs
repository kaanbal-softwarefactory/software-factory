// Real Keycloak/PostgreSQL acceptance. Captures child output: never logs secrets.
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import assert from "node:assert/strict";
import pg from "pg";
for (const [key,file] of Object.entries({IDENTITY_ADMIN_PASSWORD:"admin-password",OIDC_CLIENT_SECRET:"client-secret",OWNER_PASSWORD:"owner-password",CUSTOMER_PASSWORD:"customer-password"}))
  process.env[key] = readFileSync(`/credentials/${file}`,"utf8").trim();
function run(command,args) {
  const result = spawnSync(command,args,{encoding:"utf8",env:process.env,timeout:180000});
  if (result.status !== 0) throw new Error(`Acceptance step failed (${command}, status ${result.status}); output withheld`);
}
try {
  run("npm",["run","migrate"]);
  run("node",["scripts/provision-identity.mjs"]);
  run("npx",["tsx","scripts/seed.ts"]);
  const before = JSON.parse(readFileSync("/bootstrap/instance.json","utf8"));
  run("node",["scripts/provision-identity.mjs"]);
  run("npx",["tsx","scripts/seed.ts"]);
  const after = JSON.parse(readFileSync("/bootstrap/instance.json","utf8"));
  assert.deepEqual(before,after,"Bootstrap must preserve subjects and metadata");
  const db = new pg.Client({host:process.env.PGHOST,user:"business_runtime",database:"business",password:readFileSync(process.env.PGPASSWORD_FILE,"utf8").trim()});
  await db.connect();
  try {
    assert.equal((await db.query("select count(*)::integer as n from organizations")).rows[0].n,1);
    assert.equal((await db.query("select count(*)::integer as n from people")).rows[0].n,2);
    assert.equal((await db.query("select count(*)::integer as n from memberships where role='owner'")).rows[0].n,1);
    assert.equal((await db.query("select count(*)::integer as n from catalog")).rows[0].n,0,"Runtime RLS must deny an unset organization");
    const role = (await db.query("select rolsuper,rolbypassrls from pg_roles where rolname=current_user")).rows[0];
    assert.equal(role.rolsuper,false); assert.equal(role.rolbypassrls,false);
  } finally { await db.end(); }
  console.log("PASS: production-mode identity, migrations, fixtures, repeat bootstrap, stable subjects and runtime RLS.");
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
