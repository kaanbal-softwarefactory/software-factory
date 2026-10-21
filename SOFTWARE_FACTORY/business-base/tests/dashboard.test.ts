import { test } from "node:test";
import assert from "node:assert/strict";
import { dashboardHome, dashboardMembers } from "../lib/dashboard";
import type { Actor } from "../lib/session";

test("customer-only membership cannot select an administrative organization", () => {
  const user = { memberships: [{ organization_id: "a", role: "customer" }] } as Actor;
  assert.equal(dashboardHome(user), "/client");
  assert.deepEqual(dashboardMembers(user, "admin"), []);
});
test("separate dashboards never mix customer and team organizations", () => {
  const user = { memberships: [{ organization_id: "a", role: "owner" }, { organization_id: "b", role: "customer" }, { organization_id: "c", role: "staff" }] } as Actor;
  assert.equal(dashboardHome(user), "/admin");
  assert.deepEqual(dashboardMembers(user, "admin").map(m => m.organization_id), ["a", "c"]);
  assert.deepEqual(dashboardMembers(user, "client").map(m => m.organization_id), ["b"]);
});
