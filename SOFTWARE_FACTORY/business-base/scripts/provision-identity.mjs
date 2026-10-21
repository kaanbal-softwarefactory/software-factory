// Explicit Kaanbal DEMO bootstrap. Never runs from HTTP or the worker.
import { writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
if (process.env.BUSINESS_PROFILE !== "demo") throw new Error("Demo profile required");
const base = new URL(process.env.IDENTITY_ADMIN_ORIGIN || "");
const app = new URL(process.env.APP_ORIGIN || "");
const issuer = new URL(process.env.OIDC_ISSUER || "");
if (app.protocol !== "https:" || issuer.protocol !== "https:") throw new Error("Public HTTPS origins required");
for (const key of ["IDENTITY_ADMIN_PASSWORD", "OIDC_CLIENT_SECRET", "OWNER_PASSWORD", "CUSTOMER_PASSWORD"])
  if (!process.env[key]) throw new Error(`Missing ${key}`);
async function provision() {
  const response = await fetch(new URL("/realms/master/protocol/openid-connect/token", base), {
    method: "POST", body: new URLSearchParams({grant_type:"password",client_id:"admin-cli",username:"business-bootstrap",password:process.env.IDENTITY_ADMIN_PASSWORD}),
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new Error("Identity bootstrap authentication failed");
  const token = (await response.json()).access_token;
  async function api(path, method="GET", body) {
    const r = await fetch(new URL(`/admin/realms${path}`, base), {method, headers:{authorization:`Bearer ${token}`,"content-type":"application/json"},
      ...(body === undefined ? {} : {body:JSON.stringify(body)}), signal:AbortSignal.timeout(10000)});
    if (r.status === 404 && method === "GET") return null;
    if (!r.ok) throw new Error(`Identity operation failed (${r.status})`);
    return r.status === 201 || r.status === 204 ? null : r.json();
  }
  if (!(await api("/business"))) await api("", "POST", {
    realm:"business",enabled:true,displayName:process.env.BUSINESS_NAME || "Business Demo",
    registrationAllowed:false,verifyEmail:true,resetPasswordAllowed:true,loginWithEmailAllowed:true,
    bruteForceProtected:true,failureFactor:5,maxFailureWaitSeconds:900,sslRequired:"external",
    accessTokenLifespan:300,ssoSessionIdleTimeout:1800,ssoSessionMaxLifespan:28800,
    smtpServer:{host:process.env.SMTP_HOST,port:"1025",from:"notifications@example.com"},
  });
  const clients = await api("/business/clients?clientId=business-base");
  if (clients.length && (clients[0].redirectUris?.length !== 1 || clients[0].redirectUris[0] !== `${app.origin}/auth/callback`))
    throw new Error("Existing client belongs to another public origin; use a new system name");
  if (!clients.length) await api("/business/clients", "POST", {
    clientId:"business-base",enabled:true,protocol:"openid-connect",publicClient:false,
    secret:process.env.OIDC_CLIENT_SECRET,standardFlowEnabled:true,directAccessGrantsEnabled:false,
    redirectUris:[`${app.origin}/auth/callback`],webOrigins:[app.origin],defaultClientScopes:["profile","email"],
    attributes:{"pkce.code.challenge.method":"S256","backchannel.logout.url":`http://${process.env.BUSINESS_INTERNAL_APP}:3000/auth/backchannel`,
      "backchannel.logout.session.required":"true","post.logout.redirect.uris":`${app.origin}/`},
  });
  // Only create missing fixtures. An update never resets a user's password/MFA.
  const users = {};
  for (const username of ["owner","customer"]) {
    const matches = await api(`/business/users?username=${username}&exact=true`);
    if (!matches.length) {
      const id = randomUUID();
      await api("/business/users", "POST", {id,username,email:`${username}@example.com`,emailVerified:true,enabled:true,
        firstName:username === "owner" ? "Owner" : "Cliente",lastName:"Demo",
        requiredActions:username === "owner" ? ["CONFIGURE_TOTP"] : [],
        credentials:[{type:"password",value:process.env[`${username.toUpperCase()}_PASSWORD`],temporary:false}]});
    }
    users[username] = (await api(`/business/users?username=${username}&exact=true`))[0].id;
  }
  writeFileSync("/bootstrap/instance.json", JSON.stringify({name:process.env.BUSINESS_NAME || "Business Demo",preset:process.env.BUSINESS_PRESET || "services",
    issuer:issuer.href,ownerSubject:users.owner,customerSubject:users.customer}), {mode:0o600});
}
try {
  let done = false;
  for(let attempt=0;attempt<30;attempt++) {
    try { await provision(); done = true; break; }
    catch { if(attempt < 29) await new Promise(r=>setTimeout(r,3000)); }
  }
  if (!done) throw new Error();
  await import("./configure-identity.mjs");
  if (process.exitCode) throw new Error();
  console.log("Demo identity initialized; existing credentials and factors preserved.");
} catch {
  console.error("Identity provisioning failed. No provider responses or credentials were logged.");
  process.exitCode = 1;
}
