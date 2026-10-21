import { createHash, randomBytes } from "node:crypto";
import type { NextRequest } from "next/server";
import { pool } from "./db";
import { Problem, type Role } from "./policy";
import { origin } from "./config";

export const digest = (value: string) =>
  createHash("sha256").update(value).digest("hex");
export const opaque = () => randomBytes(32).toString("base64url");
// Cookies do not isolate by port. Distinct names keep local copies usable in the same browser.
const instance = digest(
  new URL(process.env.APP_ORIGIN || "http://localhost:3100").origin,
).slice(0, 16);
export const sessionCookie = `business_session_${instance}`;
export const flowCookie = `business_flow_${instance}`;
export function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: new URL(origin()).protocol === "https:",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}
export type Actor = {
  id: string;
  name: string;
  email: string;
  email_verified: boolean;
  mfa: boolean;
  memberships: {
    organization_id: string;
    slug: string;
    name: string;
    role: Role;
  }[];
};
export async function actor(request: NextRequest): Promise<Actor> {
  const token = request.cookies.get(sessionCookie)?.value;
  if (!token) throw new Problem(401, "Inicia sesión para continuar");
  const result = await pool.query(
    `SELECT u.id, u.name, u.email, u.email_verified, s.mfa FROM sessions s
    JOIN people u ON u.id=s.person_id WHERE s.id=$1 AND s.expires_at>now() AND u.disabled=false`,
    [digest(token)],
  );
  if (!result.rowCount) throw new Problem(401, "La sesión terminó");
  const user = result.rows[0];
  user.memberships = (
    await pool.query(
      `SELECT m.organization_id, m.role, o.slug, o.name FROM memberships m
    JOIN organizations o ON o.id=m.organization_id WHERE m.person_id=$1 AND m.active=true ORDER BY o.name`,
      [user.id],
    )
  ).rows;
  return user;
}
export function membership(user: Actor, organization: string) {
  const member = user.memberships.find(
    (m) => m.organization_id === organization,
  );
  if (!member) throw new Problem(403, "No perteneces a esta organización");
  if (["owner", "admin"].includes(member.role) && !user.mfa)
    throw new Problem(403, "Verifica MFA antes de acceder a la administración");
  return member;
}
export function sameOrigin(request: NextRequest) {
  if (request.headers.get("origin") !== origin())
    throw new Problem(403, "Origen no permitido");
  const type = request.headers.get("content-type") || "";
  if (!type.includes("application/json")) throw new Problem(415, "Usa JSON");
}
