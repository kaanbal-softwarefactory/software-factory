import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import pg from "pg";
import { secret } from "../lib/config";

const db = new pg.Client({
  connectionString: process.env.MIGRATION_DATABASE_URL,
  host: process.env.PGHOST,
  port: Number(process.env.PGPORT || 5432),
  user: process.env.MIGRATION_PGUSER,
  password: secret("MIGRATION_PGPASSWORD"),
  database: process.env.PGDATABASE,
});
try {
  await db.connect();
  await db.query(
    "SELECT pg_advisory_lock(hashtext('business-base-migrations'))",
  );
  await db.query(
    "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())",
  );
  const directory = fileURLToPath(new URL("../migrations/", import.meta.url));
  for (const name of readdirSync(directory)
    .filter((n) => n.endsWith(".sql"))
    .sort()) {
    if (
      (
        await db.query("SELECT 1 FROM schema_migrations WHERE version=$1", [
          name,
        ])
      ).rowCount
    )
      continue;
    await db.query("BEGIN");
    try {
      await db.query(readFileSync(`${directory}/${name}`, "utf8"));
      await db.query("INSERT INTO schema_migrations(version) VALUES($1)", [
        name,
      ]);
      await db.query("COMMIT");
      console.log(`Applied ${name}`);
    } catch (error) {
      await db.query("ROLLBACK");
      throw error;
    }
  }
} finally {
  await db.end();
}
