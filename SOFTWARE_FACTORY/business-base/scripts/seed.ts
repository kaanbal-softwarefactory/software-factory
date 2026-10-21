// Explicit local/Kaanbal demo fixtures. Never implicit in HTTP.
import { readFileSync } from "node:fs";
import pg from "pg";
import { secret } from "../lib/config";
import { enabledModules } from "../lib/features";
const config = JSON.parse(readFileSync("/bootstrap/instance.json", "utf8"));
const db = new pg.Client({
  host: process.env.PGHOST,
  database: process.env.PGDATABASE,
  user: process.env.MIGRATION_PGUSER,
  password: secret("MIGRATION_PGPASSWORD"),
});
await db.connect();
try {
  await db.query("BEGIN");
  const org = (
    await db.query(
      `INSERT INTO organizations(slug,name,description,public,timezone,experience,enabled_modules) VALUES('demo',$1,$2,true,'America/Mexico_City',$3,$4) ON CONFLICT(slug) DO UPDATE SET slug=excluded.slug RETURNING id,experience,enabled_modules`,
      [
        config.name,
        "Servicios pensados para ti, atención cercana y un equipo que te acompaña de principio a fin.",
        config.preset || "services",
        enabledModules(config.preset || "services", config.modules),
      ],
    )
  ).rows[0];
  const preset = org.experience;
  const organizationId = org.id;
  await db.query("SELECT set_config('app.organization_id',$1,true)", [organizationId]);
  for (const [subject, email, name, role] of [
    [config.ownerSubject, "owner@example.com", "Owner Demo", "owner"],
    [
      config.customerSubject,
      "customer@example.com",
      "Cliente Demo",
      "customer",
    ],
  ]) {
    const person = (
      await db.query(
        `INSERT INTO people(issuer,subject,email,email_verified,name) VALUES($1,$2,$3,true,$4) ON CONFLICT(issuer,subject) DO UPDATE SET subject=excluded.subject RETURNING id`,
        [config.issuer, subject, email, name],
      )
    ).rows[0].id;
    await db.query(
      "INSERT INTO memberships(organization_id,person_id,role) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
      [organizationId, person, role],
    );
  }
  if (enabledModules(preset, org.enabled_modules).includes("catalog") && !(await db.query("SELECT 1 FROM catalog LIMIT 1")).rowCount) {
    const services =
      config.preset === "barber"
        ? [
            [
              "Corte de cabello",
              "Tu estilo, con atención al detalle.",
              25000,
              30,
            ],
            [
              "Corte y barba",
              "Una experiencia completa para renovar tu imagen.",
              40000,
              60,
            ],
            ["Diseño de barba", "Acabado y cuidado personal.", 18000, 30],
          ]
        : [
            [
              "Asesoría inicial",
              "Un espacio para entender lo que necesitas.",
              45000,
              30,
            ],
            [
              "Sesión personalizada",
              "Acompañamiento centrado en tus objetivos.",
              90000,
              60,
            ],
            [
              "Seguimiento",
              "Continuamos contigo en el siguiente paso.",
              35000,
              30,
            ],
          ];
    for (const [name, description, price, duration] of services)
      await db.query(
        "INSERT INTO catalog(organization_id,name,description,price_cents,duration_minutes) VALUES($1,$2,$3,$4,$5)",
        [organizationId, name, description, price, duration],
      );
  }
  if (enabledModules(preset, org.enabled_modules).includes("appointments") && !(await db.query("SELECT 1 FROM resources LIMIT 1")).rowCount) {
    await db.query(
      "INSERT INTO resources(organization_id,name) VALUES($1,'Equipo de atención')",
      [organizationId],
    );
  }
  await db.query("COMMIT");
  console.log(
    "Business demo fixture ready; existing business data preserved.",
  );
} catch (error) {
  await db.query("ROLLBACK");
  throw error;
} finally {
  await db.end();
}
