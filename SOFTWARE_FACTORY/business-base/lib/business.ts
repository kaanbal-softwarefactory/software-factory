import { z } from "zod";
import type { PoolClient } from "pg";
import { inOrganization, pool } from "./db";
import { authorize, ownOrManage, Problem } from "./policy";
import { membership, digest, opaque, type Actor } from "./session";

const uuid = z.uuid();
const messageSchema = z.object({
  name: z.string().trim().min(2).max(120),
  email: z.email().max(254),
  message: z.string().trim().min(5).max(4000),
  website: z.string().max(200).optional(),
});
const serviceSchema = z.object({
  name: z.string().trim().min(2).max(120),
  description: z.string().max(1000).default(""),
  price_cents: z.number().int().min(0).max(100000000),
  duration_minutes: z.number().int().min(5).max(480),
});

async function audit(
  db: PoolClient,
  organization: string,
  user: string | null,
  action: string,
  resource: string,
) {
  await db.query(
    "INSERT INTO audit(organization_id,actor_id,action,resource) VALUES($1,$2,$3,$4)",
    [organization, user, action, resource],
  );
}
async function publicOrganization() {
  const result = await pool.query(
    "SELECT id,slug,name,description,whatsapp,timezone,experience FROM organizations WHERE slug=$1 AND public=true",
    [process.env.PUBLIC_ORGANIZATION || "demo"],
  );
  if (!result.rowCount) throw new Problem(404, "Sitio no configurado");
  return result.rows[0];
}
export async function publicSite() {
  const organization = await publicOrganization();
  return inOrganization(organization.id, async (db) => ({
    organization,
    services: (
      await db.query(
        "SELECT id,name,description,price_cents,duration_minutes FROM catalog WHERE active=true ORDER BY name",
      )
    ).rows,
    resources: (await db.query("SELECT id,name FROM resources ORDER BY name"))
      .rows,
  }));
}
export async function contact(input: unknown, user: Actor | null) {
  const body = messageSchema.parse(input),
    organization = await publicOrganization();
  if (body.website) return { accepted: true }; // Honeypot: same response, no mail or stored request.
  return inOrganization(organization.id, async (db) => {
    const limit = await db.query(
      `INSERT INTO public_limits(organization_id,count) VALUES($1,1)
      ON CONFLICT(organization_id) DO UPDATE SET count=CASE WHEN public_limits.window_start<now()-interval '1 minute' THEN 1 ELSE public_limits.count+1 END,
      window_start=CASE WHEN public_limits.window_start<now()-interval '1 minute' THEN now() ELSE public_limits.window_start END RETURNING count`,
      [organization.id],
    );
    if (limit.rows[0].count > 30)
      throw new Problem(429, "Demasiadas solicitudes; intenta más tarde");
    const person = user?.memberships.some(
      (m) => m.organization_id === organization.id,
    )
      ? user.id
      : null;
    const result = await db.query(
      "INSERT INTO requests(organization_id,person_id,name,email,message) VALUES($1,$2,$3,$4,$5) RETURNING id",
      [
        organization.id,
        person,
        body.name,
        body.email.toLowerCase(),
        body.message,
      ],
    );
    await audit(
      db,
      organization.id,
      person,
      "request.created",
      result.rows[0].id,
    );
    await db.query(
      `INSERT INTO notifications(organization_id,title) VALUES($1,'Nueva solicitud de contacto')`,
      [organization.id],
    );
    if (process.env.CONTACT_NOTIFICATION_EMAIL)
      await db.query(
        "INSERT INTO outbox(organization_id,recipient,title,message) VALUES($1,$2,$3,$4)",
        [
          organization.id,
          process.env.CONTACT_NOTIFICATION_EMAIL,
          "Nueva solicitud",
          "Hay una nueva solicitud en el inbox. Inicia sesión para consultarla.",
        ],
      );
    return { accepted: true };
  });
}

export async function listResource(
  user: Actor,
  organization: string,
  resource: string,
) {
  uuid.parse(organization);
  const member = membership(user, organization);
  return inOrganization(organization, async (db) => {
    switch (resource) {
      case "settings":
        authorize(member.role, "catalog.manage");
        return (
          await db.query(
            "SELECT name,description,whatsapp,timezone FROM organizations WHERE id=$1",
            [organization],
          )
        ).rows;
      case "requests":
        return (
          await db.query(
            `SELECT id,name,email,message,state,assigned_to,created_at FROM requests
          WHERE ($1::boolean OR person_id=$2) ORDER BY created_at DESC LIMIT 200`,
            [member.role !== "customer", user.id],
          )
        ).rows;
      case "catalog":
        return (await db.query("SELECT * FROM catalog ORDER BY name")).rows;
      case "resources":
        return (await db.query("SELECT id,name FROM resources ORDER BY name"))
          .rows;
      case "appointments":
        return (
          await db.query(
            `SELECT a.id,a.person_id,a.starts_at,a.ends_at,a.state,c.name AS service,r.name AS resource
        FROM appointments a JOIN catalog c ON c.id=a.service_id JOIN resources r ON r.id=a.resource_id
        WHERE ($1::boolean OR a.person_id=$2) ORDER BY a.starts_at DESC LIMIT 200`,
            [member.role !== "customer", user.id],
          )
        ).rows;
      case "members":
        authorize(member.role, "members.manage");
        return (
          await db.query(
            `SELECT m.person_id,p.name,p.email,m.role,m.active FROM memberships m JOIN people p ON p.id=m.person_id WHERE m.organization_id=$1 ORDER BY p.name`,
            [organization],
          )
        ).rows;
      case "audit":
        authorize(member.role, "audit.read");
        return (
          await db.query(
            "SELECT action,resource,created_at FROM audit ORDER BY id DESC LIMIT 100",
          )
        ).rows;
      case "notifications":
        return (
          await db.query(
            `SELECT title,created_at FROM notifications WHERE person_id=$1 OR ($2::boolean AND person_id IS NULL) ORDER BY created_at DESC LIMIT 50`,
            [user.id, member.role !== "customer"],
          )
        ).rows;
      default:
        throw new Problem(404, "No encontrado");
    }
  });
}

export async function mutate(
  user: Actor,
  organization: string,
  resource: string,
  input: unknown,
) {
  uuid.parse(organization);
  const member = membership(user, organization);
  return inOrganization(organization, async (db) => {
    if (resource === "settings") {
      authorize(member.role, "catalog.manage");
      const body = z
        .object({
          name: z.string().trim().min(2).max(100),
          description: z.string().trim().max(2000),
          whatsapp: z
            .string()
            .max(30)
            .regex(/^[+0-9 ()-]*$/),
          timezone: z.string().min(1).max(80),
        })
        .parse(input);
      try {
        new Intl.DateTimeFormat("en", { timeZone: body.timezone }).format();
      } catch {
        throw new Problem(422, "Zona horaria inválida");
      }
      await db.query(
        "UPDATE organizations SET name=$1,description=$2,whatsapp=$3,timezone=$4 WHERE id=$5",
        [
          body.name,
          body.description,
          body.whatsapp,
          body.timezone,
          organization,
        ],
      );
      await audit(
        db,
        organization,
        user.id,
        "organization.updated",
        organization,
      );
      return { updated: true };
    }
    if (resource === "catalog") {
      authorize(member.role, "catalog.manage");
      const body = serviceSchema.parse(input);
      const result = await db.query(
        "INSERT INTO catalog(organization_id,name,description,price_cents,duration_minutes) VALUES($1,$2,$3,$4,$5) RETURNING id",
        [
          organization,
          body.name,
          body.description,
          body.price_cents,
          body.duration_minutes,
        ],
      );
      await audit(
        db,
        organization,
        user.id,
        "catalog.created",
        result.rows[0].id,
      );
      return result.rows[0];
    }
    if (resource === "requests") {
      authorize(member.role, "inbox.manage");
      const body = z
        .object({
          id: uuid,
          state: z.enum(["new", "assigned", "closed"]),
          assigned_to: uuid.nullable().optional(),
        })
        .parse(input);
      if (
        body.assigned_to &&
        !(
          await db.query(
            `SELECT 1 FROM memberships WHERE organization_id=$1 AND person_id=$2 AND active=true AND role IN ('owner','admin','staff')`,
            [organization, body.assigned_to],
          )
        ).rowCount
      )
        throw new Problem(422, "Responsable no válido");
      const result = await db.query(
        "UPDATE requests SET state=$1,assigned_to=$2 WHERE id=$3 RETURNING id",
        [
          body.state,
          body.assigned_to || (body.state === "assigned" ? user.id : null),
          body.id,
        ],
      );
      if (!result.rowCount) throw new Problem(404, "Solicitud no encontrada");
      await audit(db, organization, user.id, "request.updated", body.id);
      return result.rows[0];
    }
    if (resource === "invitations") {
      authorize(member.role, "members.manage");
      const body = z
        .object({
          email: z.email().max(254),
          role: z.enum(["admin", "staff", "customer"]),
        })
        .parse(input);
      const token = opaque();
      await db.query(
        "INSERT INTO invitations(id,organization_id,email,role) VALUES($1,$2,$3,$4)",
        [digest(token), organization, body.email.toLowerCase(), body.role],
      );
      await audit(
        db,
        organization,
        user.id,
        "invitation.created",
        "invitation",
      );
      return { token }; // Only delivered to the authorized creator; not logged or persisted in cleartext.
    }
    if (resource === "members") {
      authorize(member.role, "members.manage");
      const body = z
        .object({
          person_id: uuid,
          role: z.enum(["admin", "staff", "customer"]),
          active: z.boolean(),
        })
        .parse(input);
      // Owners are protected; transfer of ownership is a separate future operation.
      const result = await db.query(
        `UPDATE memberships SET role=$1,active=$2 WHERE organization_id=$3 AND person_id=$4 AND role<>'owner' RETURNING person_id`,
        [body.role, body.active, organization, body.person_id],
      );
      if (!result.rowCount) throw new Problem(404, "Miembro no editable");
      await audit(
        db,
        organization,
        user.id,
        "membership.updated",
        body.person_id,
      );
      return { updated: true };
    }
    if (resource === "appointments") {
      const body = z
        .object({
          service_id: uuid,
          resource_id: uuid,
          starts_at: z.iso.datetime({ offset: true }),
        })
        .parse(input);
      const start = new Date(body.starts_at);
      if (
        start.getTime() < Date.now() + 3600000 ||
        start.getTime() > Date.now() + 90 * 86400000
      )
        throw new Problem(
          422,
          "Reserva con al menos una hora de anticipación y hasta 90 días",
        );
      // Serialize per resource inside this transaction. All booking writers must use this path.
      const lock = await db.query(
        "SELECT id FROM resources WHERE id=$1 FOR UPDATE",
        [body.resource_id],
      );
      if (!lock.rowCount) throw new Problem(404, "Recurso no encontrado");
      const services = await db.query(
        "SELECT duration_minutes FROM catalog WHERE id=$1 AND active=true",
        [body.service_id],
      );
      if (!services.rowCount) throw new Problem(404, "Servicio no encontrado");
      const end = new Date(
        start.getTime() + services.rows[0].duration_minutes * 60000,
      );
      // Pilot schedule is deliberately simple and explicit: Mon-Fri, 09:00-18:00 in organization timezone.
      const schedule = await db.query(
        `SELECT extract(isodow from $1::timestamptz AT TIME ZONE timezone) AS day,
        ($1::timestamptz AT TIME ZONE timezone)::time >= time '09:00' AND ($2::timestamptz AT TIME ZONE timezone)::time <= time '18:00'
        AND ($1::timestamptz AT TIME ZONE timezone)::date=($2::timestamptz AT TIME ZONE timezone)::date AS valid FROM organizations WHERE id=$3`,
        [start, end, organization],
      );
      if (!schedule.rows[0]?.valid || Number(schedule.rows[0].day) > 5)
        throw new Problem(
          422,
          "Horario piloto: lunes a viernes de 09:00 a 18:00, zona del negocio",
        );
      if (
        (
          await db.query(
            `SELECT 1 FROM appointments WHERE resource_id=$1 AND state='confirmed' AND starts_at<$3 AND ends_at>$2`,
            [body.resource_id, start, end],
          )
        ).rowCount
      )
        throw new Problem(409, "Este horario ya está reservado");
      const result = await db.query(
        `INSERT INTO appointments(organization_id,person_id,resource_id,service_id,starts_at,ends_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING id`,
        [organization, user.id, body.resource_id, body.service_id, start, end],
      );
      await audit(
        db,
        organization,
        user.id,
        "appointment.created",
        result.rows[0].id,
      );
      return result.rows[0];
    }
    if (resource === "cancel-appointment") {
      const body = z.object({ id: uuid }).parse(input);
      const result = await db.query(
        "SELECT person_id FROM appointments WHERE id=$1 FOR UPDATE",
        [body.id],
      );
      if (!result.rowCount) throw new Problem(404, "Cita no encontrada");
      ownOrManage(
        member.role,
        user.id,
        result.rows[0].person_id,
        "appointments.manage",
      );
      await db.query("UPDATE appointments SET state='cancelled' WHERE id=$1", [
        body.id,
      ]);
      await audit(db, organization, user.id, "appointment.cancelled", body.id);
      return { updated: true };
    }
    throw new Problem(404, "No encontrado");
  });
}

export async function acceptInvitation(user: Actor, input: unknown) {
  const body = z
    .object({ organization: uuid, token: z.string().min(30).max(100) })
    .parse(input);
  if (!user.email_verified)
    throw new Problem(403, "Verifica tu correo antes de aceptar la invitación");
  return inOrganization(body.organization, async (db) => {
    const invitations = await db.query(
      `UPDATE invitations SET used_at=now() WHERE id=$1 AND email=$2 AND expires_at>now() AND used_at IS NULL RETURNING role`,
      [digest(body.token), user.email.toLowerCase()],
    );
    if (!invitations.rowCount)
      throw new Problem(404, "Invitación inválida o expirada");
    await db.query(
      `INSERT INTO memberships(organization_id,person_id,role) VALUES($1,$2,$3)
      ON CONFLICT(organization_id,person_id) DO UPDATE SET role=excluded.role,active=true WHERE memberships.role<>'owner'`,
      [body.organization, user.id, invitations.rows[0].role],
    );
    await audit(
      db,
      body.organization,
      user.id,
      "invitation.accepted",
      "invitation",
    );
    return { accepted: true };
  });
}
