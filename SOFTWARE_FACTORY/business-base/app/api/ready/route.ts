import { pool } from "../../../lib/db";
import { localFetch, oidcConfig } from "../../../lib/oidc";
import { issuer } from "../../../lib/config";
export const dynamic = "force-dynamic";
export async function GET() {
  try {
    const schema = await pool.query(
      "SELECT 1 FROM schema_migrations WHERE version='003_starter_experience.sql'",
    );
    if (!schema.rowCount) throw new Error("Migration missing");
    const role = (
      await pool.query(
        `SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user`,
      )
    ).rows[0];
    if (role.rolsuper || role.rolbypassrls)
      throw new Error("Unsafe database role");
    const discovery = await localFetch(
      new URL(
        `${issuer().href.replace(/\/$/, "")}/.well-known/openid-configuration`,
      ),
      { signal: AbortSignal.timeout(3000) },
    );
    if (!discovery.ok) throw new Error("Identity unavailable");
    await oidcConfig();
    return Response.json({ status: "ready" });
  } catch {
    return Response.json({ status: "not_ready" }, { status: 503 });
  }
}
