// Secrets are generated inside a named Docker volume, never in the repository or logs.
import { randomBytes, randomUUID } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { parseModules } from "./modules.mjs";
const root = "/bootstrap";
function value(name) {
  const path = `${root}/${name}`;
  if (!existsSync(path))
    writeFileSync(path, randomBytes(32).toString("hex"), { mode: 0o600 });
  return readFileSync(path, "utf8").trim();
}
for (const name of [
  "postgres-password",
  "runtime-password",
  "migration-password",
  "identity-password",
  "client-secret",
  "owner-password",
  "customer-password",
  "admin-password",
])
  value(name);
const appPort = Number(process.env.APP_PORT || 3100),
  identityPort = Number(process.env.IDENTITY_PORT || 8180);
const settings = {
  name: process.env.BUSINESS_NAME || "Estudio Demo",
  preset: process.env.BUSINESS_PRESET || "services",
  modules: parseModules(process.env.BUSINESS_MODULES),
  appPort,
  identityPort,
  issuer: `http://localhost:${identityPort}/realms/business`,
  ownerSubject: randomUUID(),
  customerSubject: randomUUID(),
};
const instance = `${root}/instance.json`;
if (!existsSync(instance))
  writeFileSync(instance, JSON.stringify(settings), { mode: 0o644 });
const config = JSON.parse(readFileSync(instance, "utf8"));
if (config.appPort !== appPort || config.identityPort !== identityPort)
  throw new Error(
    "This project already uses different ports. Use its original ports or create a new named copy.",
  );
const realm = {
  realm: "business",
  displayName: config.name,
  enabled: true,
  registrationAllowed: true,
  resetPasswordAllowed: true,
  verifyEmail: true,
  loginWithEmailAllowed: true,
  bruteForceProtected: true,
  failureFactor: 5,
  maxFailureWaitSeconds: 900,
  sslRequired: "none",
  accessTokenLifespan: 300,
  ssoSessionIdleTimeout: 1800,
  ssoSessionMaxLifespan: 28800,
  smtpServer: {
    host: "mail",
    port: "1025",
    from: "notifications@example.com",
    fromDisplayName: config.name,
  },
  clients: [
    {
      clientId: "business-base",
      name: config.name,
      enabled: true,
      protocol: "openid-connect",
      publicClient: false,
      secret: value("client-secret"),
      standardFlowEnabled: true,
      directAccessGrantsEnabled: false,
      redirectUris: [`http://localhost:${appPort}/auth/callback`],
      webOrigins: [`http://localhost:${appPort}`],
      defaultClientScopes: ["profile", "email"],
      attributes: {
        "pkce.code.challenge.method": "S256",
        "backchannel.logout.url": `http://app:3000/auth/backchannel`,
        "backchannel.logout.session.required": "true",
        "post.logout.redirect.uris": `http://localhost:${appPort}/`,
      },
      protocolMappers: [
        {
          name: "Authentication methods",
          protocol: "openid-connect",
          protocolMapper: "oidc-amr-mapper",
          config: { "id.token.claim": "true", "access.token.claim": "true" },
        },
      ],
    },
  ],
  users: [
    {
      id: config.ownerSubject,
      username: "owner",
      email: "owner@example.com",
      emailVerified: true,
      enabled: true,
      firstName: "Owner",
      lastName: "Demo",
      requiredActions: ["CONFIGURE_TOTP"],
      credentials: [
        { type: "password", value: value("owner-password"), temporary: false },
      ],
    },
    {
      id: config.customerSubject,
      username: "customer",
      email: "customer@example.com",
      emailVerified: true,
      enabled: true,
      firstName: "Cliente",
      lastName: "Demo",
      credentials: [
        {
          type: "password",
          value: value("customer-password"),
          temporary: false,
        },
      ],
    },
  ],
};
// Each process receives only its own secret volume. The web process cannot read the IdP,
// PostgreSQL administrator or migration credentials, even after a web compromise.
for (const [directory, names] of Object.entries({
  "/database-secrets": [
    "postgres-password",
    "runtime-password",
    "migration-password",
    "identity-password",
  ],
  "/runtime-secrets": ["runtime-password", "client-secret"],
  "/migration-secrets": ["migration-password", "runtime-password"],
  "/identity-secrets": ["identity-password", "admin-password"],
})) {
  mkdirSync(directory, { recursive: true });
  for (const name of names)
    writeFileSync(`${directory}/${name}`, value(name), { mode: 0o644 });
}
writeFileSync("/migration-secrets/instance.json", JSON.stringify(config), {
  mode: 0o644,
});
writeFileSync("/identity-secrets/realm.json", JSON.stringify(realm), {
  mode: 0o644,
});
console.log(
  "Local instance initialized. Credentials remain in the project secret volume.",
);
