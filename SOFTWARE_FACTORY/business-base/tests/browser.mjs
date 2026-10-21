// Local-only acceptance test. Generated credentials remain in memory or Docker volumes.
// No screenshots, traces, DOM dumps or logging of login/MFA enrollment screens.
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { randomBytes, randomUUID, createHmac } from "node:crypto";
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
const args = process.argv.slice(2),
  option = (key, fallback) => {
    const i = args.indexOf(key);
    return i < 0 ? fallback : args[i + 1];
  };
const project = option("--project", "business-reference"),
  base = option("--origin", "http://localhost:3100"),
  identity = option("--identity", "http://localhost:8180");
if (
  !/^business-[a-z0-9-]+$/.test(project) ||
  ![base, identity].every((v) => {
    const u = new URL(v);
    return u.protocol === "http:" && u.hostname === "localhost";
  })
)
  throw new Error("Use a local disposable business-* project");
const directory = resolve(option("--screenshots", "coverage/browser"));
mkdirSync(directory, { recursive: true });
const compose = ["compose", "--project-name", project];
function credential(name) {
  return execFileSync(
    "docker",
    [
      ...compose,
      "run",
      "--rm",
      "-T",
      "--no-deps",
      "--entrypoint",
      "cat",
      "bootstrap",
      `/bootstrap/${name}`,
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  ).trim();
}
function totp(secret) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secret.replace(/\s/g, "").toUpperCase())
    bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  const key = Buffer.from(
      (bits.match(/.{8}/g) || []).map((b) => parseInt(b, 2)),
    ),
    counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const hash = createHmac("sha1", key).update(counter).digest(),
    offset = hash[hash.length - 1] & 15;
  return String((hash.readUInt32BE(offset) & 0x7fffffff) % 1000000).padStart(
    6,
    "0",
  );
}
let stage = "initialize",
  browser,
  debugPage;
try {
  stage = "configure identity assurance";
  execFileSync(
    "docker",
    [...compose, "run", "--rm", "-T", "--no-deps", "configure-identity"],
    { stdio: ["ignore", "pipe", "pipe"] },
  );
  stage = "identity administration login";
  const tokenResponse = await fetch(
    `${identity}/realms/master/protocol/openid-connect/token`,
    {
      method: "POST",
      body: new URLSearchParams({
        grant_type: "password",
        client_id: "admin-cli",
        username: "local-admin",
        password: credential("admin-password"),
      }),
    },
  );
  assert.equal(tokenResponse.status, 200);
  const adminToken = (await tokenResponse.json()).access_token,
    subject = randomUUID(),
    password = randomBytes(24).toString("base64url"),
    username = `smoke-${subject.slice(0, 8)}`,
    email = `${username}@example.com`;
  const headers = {
    authorization: `Bearer ${adminToken}`,
    "Content-Type": "application/json",
  };
  stage = "identity assurance mapper";
  const clients = await (
    await fetch(
      `${identity}/admin/realms/business/clients?clientId=business-base`,
      { headers },
    )
  ).json();
  const client = clients[0];
  const mappers = await (
    await fetch(
      `${identity}/admin/realms/business/clients/${client.id}/protocol-mappers/models`,
      { headers },
    )
  ).json();
  // Reconcile the mapper when testing a reference created before the current prototype revision.
  if (!mappers.some((mapper) => mapper.protocolMapper === "oidc-amr-mapper")) {
    const added = await fetch(
      `${identity}/admin/realms/business/clients/${client.id}/protocol-mappers/models`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          name: "Authentication methods",
          protocol: "openid-connect",
          protocolMapper: "oidc-amr-mapper",
          config: { "id.token.claim": "true", "access.token.claim": "true" },
        }),
      },
    );
    assert.equal(added.status, 201);
  }
  stage = "create isolated MFA account";
  const created = await fetch(`${identity}/admin/realms/business/users`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${adminToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      id: subject,
      username,
      email,
      emailVerified: true,
      enabled: true,
      firstName: "Responsable",
      lastName: "Prueba",
      requiredActions: ["CONFIGURE_TOTP"],
      credentials: [{ type: "password", value: password, temporary: false }],
    }),
  });
  assert.equal(created.status, 201);
  // Keycloak may generate the user ID itself; its Location is authoritative.
  const actualSubject = created.headers.get("location").split("/").pop();
  stage = "prepare browser fixture";
  execFileSync(
    "docker",
    [
      ...compose,
      "run",
      "--rm",
      "-T",
      "--no-deps",
      "migrate",
      "npx",
      "tsx",
      "tests/seed-browser.ts",
    ],
    {
      input: JSON.stringify({
        issuer: `${identity}/realms/business`,
        subject: actualSubject,
        email,
      }),
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  stage = "launch Chromium";
  browser = await chromium.launch({ headless: true });
  const customerContext = await browser.newContext({
      timezoneId: "America/Mexico_City",
      viewport: { width: 1440, height: 1000 },
    }),
    customer = await customerContext.newPage();
  customerContext.setDefaultTimeout(15000);
  customerContext.setDefaultNavigationTimeout(15000);
  debugPage = customer;
  stage = "landing";
  await customer.goto(base);
  await customer.getByRole("heading", { name: "Nuestros servicios" }).waitFor();
  await customer.screenshot({
    path: resolve(directory, "landing.png"),
    fullPage: true,
  });
  stage = "customer OIDC login";
  await customer.getByRole("link", { name: "Mi cuenta ↗" }).click();
  await customer.locator("#username").fill("customer");
  await customer.locator("#password").fill(credential("customer-password"));
  await customer.locator("#kc-login").click();
  await customer
    .getByRole("heading", { name: "Resumen", exact: true })
    .waitFor({ timeout: 30000 });
  assert.equal(
    await customer
      .getByRole("button", { name: "Equipo y accesos", exact: true })
      .count(),
    0,
  );
  stage = "customer request";
  await customer.goto(`${base}/#contact`);
  await customer.locator("input[name=name]").fill("Cliente de prueba");
  await customer.locator("input[name=email]").fill("customer@example.com");
  const message = `Solicitud de navegador ${subject.slice(0, 8)}`;
  await customer.locator("textarea[name=message]").fill(message);
  await customer.getByRole("button", { name: "Enviar solicitud ↗" }).click();
  await customer
    .getByRole("status")
    .filter({ hasText: "Recibimos tu solicitud" })
    .waitFor();
  await customer.goto(`${base}/workspace`);
  await customer
    .getByRole("button", { name: "Mis solicitudes", exact: true })
    .click();
  await customer.getByText(message, { exact: true }).waitFor();
  await customer.screenshot({
    path: resolve(directory, "customer-portal.png"),
    fullPage: true,
  });
  stage = "MFA enrollment";
  const ownerContext = await browser.newContext({
      timezoneId: "America/Mexico_City",
      viewport: { width: 1440, height: 1000 },
    }),
    owner = await ownerContext.newPage();
  ownerContext.setDefaultTimeout(15000);
  ownerContext.setDefaultNavigationTimeout(15000);
  debugPage = owner;
  await owner.goto(`${base}/auth/login`);
  await owner.locator("#username").fill(username);
  await owner.locator("#password").fill(password);
  await owner.locator("#kc-login").click();
  stage = "MFA enrollment: secret field";
  const secretField = owner.locator("input[name=totpSecret]");
  await secretField.waitFor({ state: "attached" });
  // The hidden field contains Keycloak's raw secret, not its Base32 representation.
  await owner.locator("#mode-manual").click();
  const otpSecret = await owner.locator("#kc-totp-secret-key").innerText();
  stage = "MFA enrollment: code";
  const enrolledCode = totp(otpSecret);
  await owner.locator("input[name=totp]").fill(enrolledCode);
  const label = owner.locator("input[name=userLabel]");
  if (await label.count()) await label.fill("Acceptance test");
  stage = "MFA enrollment: submit";
  await owner.locator("input[type=submit],button[type=submit]").first().click();
  stage = "MFA enrollment: callback";
  await owner
    .getByRole("heading", { name: "Resumen", exact: true })
    .waitFor({ timeout: 30000 });
  stage = "MFA verified login";
  await owner.goto(`${base}/auth/login?fresh=1`);
  if (await owner.locator("#username").count())
    await owner.locator("#username").fill(username);
  await owner.locator("#password").fill(password);
  await owner.locator("#kc-login").click();
  // Enrollment already consumed that code; wait for the next TOTP window.
  while (totp(otpSecret) === enrolledCode)
    await new Promise((resolve) => setTimeout(resolve, 500));
  await owner.locator("input[name=otp]").fill(totp(otpSecret));
  await owner.locator("input[type=submit],button[type=submit]").first().click();
  await owner
    .getByRole("heading", { name: "Resumen", exact: true })
    .waitFor({ timeout: 30000 });
  const assurance = await owner.request.get(`${base}/api/business/me`);
  assert.equal((await assurance.json()).mfa, true);
  stage = "inbox management";
  await owner.getByRole("button", { name: "Solicitudes", exact: true }).click();
  await owner.getByText(message, { exact: true }).waitFor();
  const item = owner.locator("article").filter({ hasText: message });
  await item.getByRole("button", { name: "Asignarme" }).click();
  await item.getByText("assigned", { exact: true }).waitFor();
  await owner.screenshot({
    path: resolve(directory, "admin-inbox.png"),
    fullPage: true,
  });
  stage = "responsive portal";
  await owner.setViewportSize({ width: 390, height: 844 });
  await owner.screenshot({
    path: resolve(directory, "admin-mobile.png"),
    fullPage: true,
  });
  assert.equal(
    await owner.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
    false,
  );
  stage = "logout";
  await customer.getByRole("button", { name: "Salir", exact: true }).click();
  // RP initiated logout may require confirmation at the IdP when no id_token_hint is retained.
  const confirm = customer.locator("#kc-logout");
  if (await confirm.count()) await confirm.click();
  console.log(
    "PASS: landing, real OIDC login, owner MFA enrollment, customer resource isolation, contact → inbox, assignment, responsive layout and session logout.",
  );
} catch {
  if (debugPage)
    console.error(
      "Safe page diagnostics:",
      JSON.stringify({
        path: new URL(debugPage.url()).pathname,
        fields: await debugPage
          .locator("input,button")
          .evaluateAll((elements) =>
            elements.map((e) => ({
              tag: e.tagName,
              id: e.id,
              name: e.getAttribute("name"),
              type: e.getAttribute("type"),
            })),
          )
          .catch(() => []),
      }),
    );
  console.error(
    `Browser acceptance failed at stage: ${stage}. No credential or authentication-page output was collected.`,
  );
  process.exitCode = 1;
} finally {
  await browser?.close();
}
