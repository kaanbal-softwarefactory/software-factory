import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import assert from "node:assert/strict";
let browser;
try {
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  context.setDefaultTimeout(15000);
  const page = await context.newPage();
  const organizations = [];
  for (const [project, port] of [
    ["business-reference", 3100],
    ["business-barber-test", 3200],
  ]) {
    const password = execFileSync(
      "docker",
      [
        "compose",
        "-p",
        project,
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "--entrypoint",
        "cat",
        "bootstrap",
        "/bootstrap/customer-password",
      ],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
    ).trim();
    await page.goto(`http://localhost:${port}/auth/login`);
    await page.locator("#username").fill("customer");
    await page.locator("#password").fill(password);
    await page.locator("#kc-login").click();
    await page.getByRole("heading", { name: "Resumen", exact: true }).waitFor();
    const response = await context.request.get(
      `http://localhost:${port}/api/business/me`,
    );
    assert.equal(response.status(), 200);
    organizations.push((await response.json()).memberships[0].organization_id);
  }
  assert.notEqual(organizations[0], organizations[1]);
  // Browser cookies are shared across localhost ports; sessions must nevertheless coexist.
  for (const port of [3100, 3200])
    assert.equal(
      (
        await context.request.get(`http://localhost:${port}/api/business/me`)
      ).status(),
      200,
    );
  const a = await (
    await context.request.get("http://localhost:3100/api/business/public")
  ).json();
  const b = await (
    await context.request.get("http://localhost:3200/api/business/public")
  ).json();
  assert.equal(
    a.services.some((service) => service.name === "Corte de cabello"),
    false,
  );
  assert.equal(
    b.services.some((service) => service.name === "Corte de cabello"),
    true,
  );
  console.log(
    "PASS: both copies keep separate identities, organizations and catalogs, with simultaneous sessions in the same browser.",
  );
} catch {
  console.error(
    "Copy isolation acceptance failed; no credentials or authentication screens were logged.",
  );
  process.exitCode = 1;
} finally {
  await browser?.close();
}
