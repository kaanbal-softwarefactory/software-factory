import { NextRequest, NextResponse } from "next/server";
import * as oidc from "openid-client";
import { createRemoteJWKSet, jwtVerify, customFetch } from "jose";
import { pool, transaction } from "../../../lib/db";
import {
  cookieOptions,
  digest,
  opaque,
  sameOrigin,
  sessionCookie,
  flowCookie,
} from "../../../lib/session";
import { callbackURL, localFetch, oidcConfig } from "../../../lib/oidc";
import { issuer, origin } from "../../../lib/config";
import { hasMFA } from "../../../lib/policy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ action: string }> },
) {
  const { action } = await context.params;
  try {
    const config = await oidcConfig();
    if (action === "login") {
      const verifier = oidc.randomPKCECodeVerifier(),
        state = oidc.randomState(),
        nonce = oidc.randomNonce(),
        binding = opaque();
      await pool.query(
        "DELETE FROM auth_flows WHERE created_at < now()-interval '10 minutes'",
      );
      await pool.query(
        "INSERT INTO auth_flows(id,verifier,state,nonce) VALUES($1,$2,$3,$4)",
        [digest(binding), verifier, state, nonce],
      );
      const url = oidc.buildAuthorizationUrl(config, {
        redirect_uri: callbackURL(),
        scope: "openid profile email",
        code_challenge: await oidc.calculatePKCECodeChallenge(verifier),
        code_challenge_method: "S256",
        state,
        nonce,
        ...(request.nextUrl.searchParams.get("fresh") === "1"
          ? { prompt: "login" }
          : {}),
        ...(request.nextUrl.searchParams.get("setup_mfa") === "1"
          ? { kc_action: "CONFIGURE_TOTP", prompt: "login" }
          : {}),
      });
      const response = NextResponse.redirect(url);
      response.cookies.set(flowCookie, binding, cookieOptions(600));
      return response;
    }
    if (action !== "callback")
      return NextResponse.json({ error: "No encontrado" }, { status: 404 });
    const binding = request.cookies.get(flowCookie)?.value;
    if (!binding) throw new Error("Missing flow");
    const flows = await pool.query(
      "DELETE FROM auth_flows WHERE id=$1 AND created_at>now()-interval '10 minutes' RETURNING *",
      [digest(binding)],
    );
    if (!flows.rowCount) throw new Error("Expired flow");
    const flow = flows.rows[0];
    const tokens = await oidc.authorizationCodeGrant(
      config,
      new URL(`/auth/callback${request.nextUrl.search}`, origin()),
      {
        pkceCodeVerifier: flow.verifier,
        expectedState: flow.state,
        expectedNonce: flow.nonce,
      },
    );
    const claims = tokens.claims();
    if (!claims?.sub || typeof claims.email !== "string")
      throw new Error("Required identity claims unavailable");
    const email = claims.email.toLowerCase();
    const session = opaque();
    await transaction(async (db) => {
      const users = await db.query(
        `INSERT INTO people(issuer,subject,email,email_verified,name) VALUES($1,$2,$3,$4,$5)
        ON CONFLICT(issuer,subject) DO UPDATE SET email=excluded.email,email_verified=excluded.email_verified,name=excluded.name RETURNING id,disabled`,
        [
          issuer().href.replace(/\/$/, ""),
          claims.sub,
          email,
          claims.email_verified === true,
          typeof claims.name === "string" ? claims.name : claims.email,
        ],
      );
      const user = users.rows[0];
      if (user.disabled) throw new Error("Disabled account");
      if (
        process.env.PUBLIC_REGISTRATION === "true" &&
        claims.email_verified === true
      ) {
        await db.query(
          `INSERT INTO memberships(organization_id,person_id,role)
          SELECT id,$1,'customer' FROM organizations WHERE slug=$2 AND public=true ON CONFLICT DO NOTHING`,
          [user.id, process.env.PUBLIC_ORGANIZATION || "demo"],
        );
      }
      await db.query(
        `INSERT INTO sessions(id,person_id,sid,mfa,expires_at) VALUES($1,$2,$3,$4,now()+interval '30 minutes')`,
        [
          digest(session),
          user.id,
          typeof claims.sid === "string" ? claims.sid : null,
          hasMFA({ amr: claims.amr, acr: claims.acr }),
        ],
      );
    });
    const response = NextResponse.redirect(`${origin()}/workspace`);
    response.cookies.set(sessionCookie, session, cookieOptions(1800));
    response.cookies.set(flowCookie, "", cookieOptions(0));
    return response;
  } catch {
    // Never echo provider responses, tokens, authorization codes or database details.
    const response = NextResponse.redirect(`${origin()}/?auth=failed`);
    response.cookies.set(flowCookie, "", cookieOptions(0));
    return response;
  }
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ action: string }> },
) {
  const { action } = await context.params;
  if (action === "backchannel") {
    try {
      const body = await request.formData(),
        token = body.get("logout_token");
      if (typeof token !== "string" || token.length > 16000)
        throw new Error("Invalid logout");
      const config = await oidcConfig(),
        jwks = config.serverMetadata().jwks_uri;
      if (!jwks) throw new Error("Missing JWKS");
      const keyset = createRemoteJWKSet(new URL(jwks), {
        [customFetch]: localFetch,
      });
      const { payload } = await jwtVerify(token, keyset, {
        issuer: issuer().href.replace(/\/$/, ""),
        audience: process.env.OIDC_CLIENT_ID || "business-base",
        maxTokenAge: "5m",
      });
      if (
        payload.nonce ||
        !payload.jti ||
        !payload.events ||
        typeof payload.events !== "object" ||
        !(
          "http://schemas.openid.net/event/backchannel-logout" in payload.events
        ) ||
        (!payload.sid && !payload.sub)
      )
        throw new Error("Invalid logout");
      await transaction(async (db) => {
        const event = await db.query(
          "INSERT INTO logout_events(id,expires_at) VALUES($1,now()+interval '10 minutes') ON CONFLICT DO NOTHING RETURNING id",
          [payload.jti],
        );
        if (!event.rowCount) return;
        await db.query(
          `DELETE FROM sessions WHERE person_id IN (SELECT id FROM people WHERE issuer=$1 AND ($2::text IS NULL OR subject=$2))
          AND ($3::text IS NULL OR sid=$3) AND created_at<=to_timestamp($4)+interval '1 second'`,
          [
            issuer().href.replace(/\/$/, ""),
            payload.sub || null,
            payload.sid || null,
            payload.iat,
          ],
        );
      });
      return new NextResponse(null, { status: 204 });
    } catch {
      return NextResponse.json({ error: "Logout inválido" }, { status: 400 });
    }
  }
  if (action !== "logout") return new NextResponse(null, { status: 404 });
  try {
    sameOrigin(request);
    const token = request.cookies.get(sessionCookie)?.value;
    if (token)
      await pool.query("DELETE FROM sessions WHERE id=$1", [digest(token)]);
    let redirect = `${origin()}/`;
    try {
      const config = await oidcConfig();
      if (config.serverMetadata().end_session_endpoint)
        redirect = oidc.buildEndSessionUrl(config, {
          client_id: process.env.OIDC_CLIENT_ID || "business-base",
          post_logout_redirect_uri: `${origin()}/`,
        }).href;
    } catch {
      /* Local session is already revoked even if the provider is unavailable. */
    }
    const response = NextResponse.json({ redirect });
    response.cookies.set(sessionCookie, "", cookieOptions(0));
    return response;
  } catch {
    return NextResponse.json(
      { error: "No se pudo cerrar la sesión" },
      { status: 400 },
    );
  }
}
