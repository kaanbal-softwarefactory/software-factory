import { test } from "node:test";
import assert from "node:assert/strict";
import { authorize, ownOrManage, Problem, hasMFA } from "../lib/policy";
import { membership, sameOrigin, type Actor } from "../lib/session";
import { NextRequest } from "next/server";

test("a customer cannot administer the inbox or memberships", () => {
  assert.throws(
    () => authorize("customer", "inbox.manage"),
    (e) => e instanceof Problem && e.status === 403,
  );
  assert.throws(() => authorize("admin", "members.manage"));
  assert.doesNotThrow(() => authorize("owner", "members.manage"));
});
test("an authenticated customer cannot cancel another customer booking", () => {
  assert.throws(
    () => ownOrManage("customer", "alice", "bob", "appointments.manage"),
    (e) => e instanceof Problem && e.status === 404,
  );
  assert.doesNotThrow(() =>
    ownOrManage("customer", "alice", "alice", "appointments.manage"),
  );
});
test("organization identifiers are not proof of membership", () => {
  const user = {
    memberships: [{ organization_id: "a", role: "owner" }],
  } as Actor;
  assert.throws(
    () => membership(user, "b"),
    (e) => e instanceof Problem && e.status === 403,
  );
});
test("state changes require a same-origin JSON request", () => {
  process.env.APP_ORIGIN = "https://app.example.com";
  assert.throws(() =>
    sameOrigin(
      new NextRequest("https://app.example.com/api", {
        method: "POST",
        headers: {
          origin: "https://evil.example.com",
          "content-type": "application/json",
        },
      }),
    ),
  );
  assert.throws(() =>
    sameOrigin(
      new NextRequest("https://app.example.com/api", {
        method: "POST",
        headers: {
          origin: "https://app.example.com",
          "content-type": "text/plain",
        },
      }),
    ),
  );
  assert.doesNotThrow(() =>
    sameOrigin(
      new NextRequest("https://app.example.com/api", {
        method: "POST",
        headers: {
          origin: "https://app.example.com",
          "content-type": "application/json",
        },
      }),
    ),
  );
});
test("password-only or unrecognized assurance cannot unlock administration", () => {
  assert.equal(hasMFA({ amr: ["pwd"] }), false);
  assert.equal(hasMFA({ acr: "1" }), false);
  assert.equal(hasMFA({ amr: ["pwd", "otp"] }), true);
  const user = {
    mfa: false,
    memberships: [{ organization_id: "a", role: "owner" }],
  } as Actor;
  assert.throws(
    () => membership(user, "a"),
    (e) => e instanceof Problem && e.status === 403,
  );
});
