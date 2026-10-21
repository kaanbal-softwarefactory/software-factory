// Run only against a disposable local copy. Credentials arrive through mounted files.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import pg from "pg";
import { pool, inOrganization } from "../lib/db";
import { secret } from "../lib/config";
import { digest, opaque } from "../lib/session";

const admin = new pg.Client({
  host: process.env.PGHOST,
  database: process.env.PGDATABASE,
  user: process.env.MIGRATION_PGUSER,
  password: secret("MIGRATION_PGPASSWORD"),
});
const base = process.env.TEST_APP_URL || "http://app:3000",
  origin = process.env.APP_ORIGIN || "http://localhost:3100";
const ids = {
  a: randomUUID(),
  b: randomUUID(),
  owner: randomUUID(),
  customer: randomUUID(),
  other: randomUUID(),
  service: randomUUID(),
  resource: randomUUID(),
  request: randomUUID(),
  foreign: randomUUID(),
};
const tokens = { owner: opaque(), customer: opaque(), other: opaque() };
async function request(
  path: string,
  as: keyof typeof tokens = "owner",
  body?: unknown,
) {
  return fetch(`${base}/api/business/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      cookie: `business_session_${digest(origin).slice(0, 16)}=${tokens[as]}`,
      origin,
      "Content-Type": "application/json",
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}
before(async () => {
  await admin.connect();
  await admin.query(
    "INSERT INTO organizations(id,slug,name,timezone) VALUES($1,$2,$3,'UTC'),($4,$5,$6,'UTC')",
    [ids.a, `a-${ids.a}`, "Example A", ids.b, `b-${ids.b}`, "Example B"],
  );
  for (const key of ["owner", "customer", "other"] as const) {
    await admin.query(
      "INSERT INTO people(id,issuer,subject,email,email_verified,name) VALUES($1,$2,$3,$4,true,$3)",
      [
        ids[key],
        "https://identity.example.com",
        ids[key],
        `${key}@example.com`,
      ],
    );
    await admin.query(
      "INSERT INTO memberships(organization_id,person_id,role) VALUES($1,$2,$3)",
      [ids.a, ids[key], key === "owner" ? "owner" : "customer"],
    );
    await admin.query(
      "INSERT INTO sessions(id,person_id,mfa,expires_at) VALUES($1,$2,true,now()+interval '10 minutes')",
      [digest(tokens[key]), ids[key]],
    );
  }
  await inOrganization(ids.a, async (db) => {
    await db.query(
      "INSERT INTO catalog(id,organization_id,name,price_cents,duration_minutes) VALUES($1,$2,'Service',1000,30)",
      [ids.service, ids.a],
    );
    await db.query(
      "INSERT INTO resources(id,organization_id,name) VALUES($1,$2,'Resource')",
      [ids.resource, ids.a],
    );
    await db.query(
      "INSERT INTO requests(id,organization_id,person_id,name,email,message) VALUES($1,$2,$3,'Customer','customer@example.com','Private request')",
      [ids.request, ids.a, ids.customer],
    );
  });
  await inOrganization(ids.b, async (db) => {
    await db.query(
      "INSERT INTO requests(id,organization_id,name,email,message) VALUES($1,$2,'Foreign','other@example.com','Do not disclose')",
      [ids.foreign, ids.b],
    );
  });
});
after(async () => {
  await admin.end();
  await pool.end();
});

test("runtime role cannot bypass RLS and receives no rows without tenant context", async () => {
  const role = (
    await pool.query(
      "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user",
    )
  ).rows[0];
  assert.equal(role.rolsuper, false);
  assert.equal(role.rolbypassrls, false);
  assert.equal((await pool.query("SELECT * FROM requests")).rowCount, 0);
});
test("RLS blocks cross-organization writes even with a known foreign UUID", async () => {
  await assert.rejects(
    inOrganization(ids.a, (db) =>
      db.query(
        "INSERT INTO requests(organization_id,name,email,message) VALUES($1,'No','no@example.com','Rejected')",
        [ids.b],
      ),
    ),
    /row-level security/,
  );
});
test("organization context never leaks through pooled connections", async () => {
  await inOrganization(ids.a, (db) => db.query("SELECT * FROM requests"));
  assert.equal((await pool.query("SELECT * FROM requests")).rowCount, 0);
});
test("knowing an organization ID grants no access", async () => {
  assert.equal((await request(`${ids.b}/requests`)).status, 403);
});
test("customer sees only their own requests; an operator cannot mutate another organization", async () => {
  const visible = await (await request(`${ids.a}/requests`, "customer")).json();
  assert.deepEqual(
    visible.map((row: { id: string }) => row.id),
    [ids.request],
  );
  assert.equal((await request(`${ids.a}/requests`, "other")).status, 200);
  assert.equal(
    (await (await request(`${ids.a}/requests`, "other")).json()).length,
    0,
  );
  assert.equal(
    (
      await request(`${ids.a}/requests`, "owner", {
        id: ids.foreign,
        state: "closed",
      })
    ).status,
    404,
  );
});
test("customer cannot mutate requests or read members/audit", async () => {
  assert.equal(
    (
      await request(`${ids.a}/requests`, "customer", {
        id: ids.request,
        state: "closed",
      })
    ).status,
    403,
  );
  assert.equal((await request(`${ids.a}/members`, "customer")).status, 403);
  assert.equal((await request(`${ids.a}/audit`, "customer")).status, 403);
});
test("HTTP rejects forged origins, missing sessions and oversized JSON", async () => {
  assert.equal((await fetch(`${base}/api/business/me`)).status, 401);
  assert.equal(
    (
      await fetch(`${base}/api/business/contact`, {
        method: "POST",
        headers: {
          origin: "https://evil.example.com",
          "Content-Type": "application/json",
        },
        body: "{}",
      })
    ).status,
    403,
  );
  assert.equal(
    (await request("contact", "customer", { message: "x".repeat(17000) }))
      .status,
    413,
  );
});
test("invitation requires the exact verified email and cannot be reused", async () => {
  const invite = await (
    await request(`${ids.a}/invitations`, "owner", {
      email: "customer@example.com",
      role: "staff",
    })
  ).json();
  assert.equal(
    (
      await request("accept-invitation", "other", {
        organization: ids.a,
        token: invite.token,
      })
    ).status,
    404,
  );
  assert.equal(
    (
      await request("accept-invitation", "customer", {
        organization: ids.a,
        token: invite.token,
      })
    ).status,
    200,
  );
  assert.equal(
    (
      await request("accept-invitation", "customer", {
        organization: ids.a,
        token: invite.token,
      })
    ).status,
    404,
  );
  await admin.query(
    "UPDATE memberships SET role='customer' WHERE person_id=$1",
    [ids.customer],
  );
});
test("suspending a membership takes effect on the next request", async () => {
  assert.equal(
    (
      await request(`${ids.a}/members`, "owner", {
        person_id: ids.other,
        role: "customer",
        active: false,
      })
    ).status,
    200,
  );
  assert.equal((await request(`${ids.a}/requests`, "other")).status, 403);
  await admin.query("UPDATE memberships SET active=true WHERE person_id=$1", [
    ids.other,
  ]);
});
test("two concurrent bookings can create only one confirmed reservation", async () => {
  const start = new Date();
  start.setUTCDate(start.getUTCDate() + 2);
  start.setUTCHours(12, 0, 0, 0);
  while (start.getUTCDay() === 0 || start.getUTCDay() === 6)
    start.setUTCDate(start.getUTCDate() + 1);
  const body = {
    service_id: ids.service,
    resource_id: ids.resource,
    starts_at: start.toISOString(),
  };
  const results = await Promise.all([
    request(`${ids.a}/appointments`, "customer", body),
    request(`${ids.a}/appointments`, "other", body),
  ]);
  assert.deepEqual(results.map((r) => r.status).sort(), [200, 409]);
  const winner = results[0].ok ? "customer" : "other",
    loser = winner === "customer" ? "other" : "customer";
  const appointments = await (
    await request(`${ids.a}/appointments`, winner)
  ).json();
  const id = appointments[0].id;
  assert.equal(
    (await request(`${ids.a}/cancel-appointment`, loser, { id })).status,
    404,
  );
  assert.equal(
    (await request(`${ids.a}/cancel-appointment`, winner, { id })).status,
    200,
  );
});
test("audit records cannot be altered using the runtime database role", async () => {
  await assert.rejects(
    inOrganization(ids.a, (db) => db.query("DELETE FROM audit")),
    /permission denied/,
  );
});
test("public contact is persisted in the configured site and honeypot does not create records", async () => {
  const payload = {
    name: "Example Visitor",
    email: "visitor@example.com",
    message: `Integration request ${ids.a}`,
  };
  assert.equal((await request("contact", "customer", payload)).status, 202);
  assert.equal(
    (await request("contact", "customer", { ...payload, website: "spam" }))
      .status,
    202,
  );
  const publicOrg = (
    await admin.query("SELECT id FROM organizations WHERE slug='demo'")
  ).rows[0].id;
  const stored = await inOrganization(publicOrg, (db) =>
    db.query("SELECT count(*)::int AS count FROM requests WHERE message=$1", [
      payload.message,
    ]),
  );
  assert.equal(stored.rows[0].count, 1);
});
