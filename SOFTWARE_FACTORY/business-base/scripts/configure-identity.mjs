// Idempotent local identity setup. A separate one-shot process owns this credential.
import { readFileSync } from "node:fs";
if (process.env.LOCAL_DEVELOPMENT !== "true")
  throw new Error("This provisioner is for the local trial only");
const base = process.env.IDENTITY_ADMIN_ORIGIN || "http://identity:8080";
async function configure() {
  const login = await fetch(
    `${base}/realms/master/protocol/openid-connect/token`,
    {
      method: "POST",
      body: new URLSearchParams({
        grant_type: "password",
        client_id: "admin-cli",
        username: "local-admin",
        password: readFileSync("/bootstrap/admin-password", "utf8").trim(),
      }),
    },
  );
  if (!login.ok) throw new Error();
  const token = (await login.json()).access_token;
  async function api(path, method = "GET", body) {
    const response = await fetch(`${base}/admin/realms/business${path}`, {
      method,
      headers: {
        authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) throw new Error();
    return response.status === 204 || response.status === 201
      ? null
      : response.json();
  }
  const alias = "business-browser",
    flows = await api("/authentication/flows");
  if (!flows.some((flow) => flow.alias === alias))
    await api("/authentication/flows/browser/copy", "POST", { newName: alias });
  const executions = await api(`/authentication/flows/${alias}/executions`);
  for (const [provider, reference] of [
    ["auth-username-password-form", "pwd"],
    ["auth-otp-form", "otp"],
  ]) {
    const execution = executions.find((item) => item.providerId === provider);
    if (!execution) throw new Error();
    const config = {
      "default.reference.value": reference,
      "default.reference.maxAge": "1800",
    };
    if (execution.authenticationConfig) {
      const existing = await api(
        `/authentication/config/${execution.authenticationConfig}`,
      );
      if (
        existing.config?.["default.reference.value"] !== reference ||
        existing.config?.["default.reference.maxAge"] !== "1800"
      )
        await api(
          `/authentication/config/${execution.authenticationConfig}`,
          "PUT",
          { ...existing, config: { ...existing.config, ...config } },
        );
    } else
      await api(`/authentication/executions/${execution.id}/config`, "POST", {
        alias: `business-${reference}`,
        config,
      });
  }
  const clients = await api("/clients?clientId=business-base"),
    client = clients[0];
  const mappers = await api(`/clients/${client.id}/protocol-mappers/models`);
  if (!mappers.some((mapper) => mapper.protocolMapper === "oidc-amr-mapper"))
    await api(`/clients/${client.id}/protocol-mappers/models`, "POST", {
      name: "Authentication methods",
      protocol: "openid-connect",
      protocolMapper: "oidc-amr-mapper",
      config: { "id.token.claim": "true", "access.token.claim": "true" },
    });
  await api("", "PUT", { browserFlow: alias });
  console.log(
    "Identity assurance configured: only completed password and OTP executions contribute MFA evidence.",
  );
}
for (let attempt = 0; attempt < 10; attempt++) {
  try {
    await configure();
    break;
  } catch {
    if (attempt === 9) {
      console.error(
        "Local identity configuration failed; no credential or provider response was logged.",
      );
      process.exitCode = 1;
    } else await new Promise((resolve) => setTimeout(resolve, 3000));
  }
}
