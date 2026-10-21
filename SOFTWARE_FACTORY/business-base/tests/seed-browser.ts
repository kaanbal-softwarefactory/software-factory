import pg from "pg";
import { secret } from "../lib/config";
let input = "";
for await (const chunk of process.stdin) input += chunk;
const fixture = JSON.parse(input);
if (!String(fixture.email).endsWith("@example.com"))
  throw new Error("Fixtures must use example.com");
const db = new pg.Client({
  host: process.env.PGHOST,
  database: process.env.PGDATABASE,
  user: process.env.MIGRATION_PGUSER,
  password: secret("MIGRATION_PGPASSWORD"),
});
await db.connect();
try {
  const person = (
    await db.query(
      "INSERT INTO people(issuer,subject,email,email_verified,name) VALUES($1,$2,$3,true,$4) RETURNING id",
      [fixture.issuer, fixture.subject, fixture.email, "Responsable de prueba"],
    )
  ).rows[0].id;
  await db.query(
    "INSERT INTO memberships(organization_id,person_id,role) SELECT id,$1,'owner' FROM organizations WHERE slug='demo'",
    [person],
  );
  console.log("Browser fixture initialized.");
} finally {
  await db.end();
}
