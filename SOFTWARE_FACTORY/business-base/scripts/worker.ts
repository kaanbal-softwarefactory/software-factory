import nodemailer from "nodemailer";
import { pool, inOrganization } from "../lib/db";
import { secret } from "../lib/config";

let stopped = false;
process.on("SIGTERM", () => {
  stopped = true;
});
process.on("SIGINT", () => {
  stopped = true;
});
const transport = process.env.SMTP_HOST
  ? nodemailer.createTransport({
      host: process.env.SMTP_HOST,
      port: Number(process.env.SMTP_PORT || 587),
      secure: process.env.SMTP_SECURE === "true",
      ...(process.env.SMTP_USER
        ? {
            auth: {
              user: process.env.SMTP_USER,
              pass: secret("SMTP_PASSWORD"),
            },
          }
        : {}),
      connectionTimeout: 5000,
      socketTimeout: 10000,
      ...(process.env.SMTP_REQUIRE_TLS === "true" ? { requireTLS: true } : {}),
    })
  : null;
while (!stopped) {
  try {
    if (transport) {
      const organizations = await pool.query("SELECT id FROM organizations");
      for (const organization of organizations.rows)
        await inOrganization(organization.id, async (db) => {
          const result = await db.query(
            "SELECT * FROM outbox WHERE sent_at IS NULL AND failed=false AND available_at<=now() ORDER BY available_at LIMIT 1 FOR UPDATE SKIP LOCKED",
          );
          if (!result.rowCount) return;
          const task = result.rows[0];
          try {
            await transport.sendMail({
              from: process.env.SMTP_FROM,
              to: task.recipient,
              subject: task.title,
              text: task.message,
              messageId: `<${task.id}@business.example.com>`,
            });
            await db.query(
              "UPDATE outbox SET sent_at=now(),attempts=attempts+1 WHERE id=$1",
              [task.id],
            );
          } catch {
            await db.query(
              "UPDATE outbox SET attempts=attempts+1,failed=(attempts>=7),available_at=now()+make_interval(secs=>LEAST(3600,30*power(2,attempts)::int)) WHERE id=$1",
              [task.id],
            );
          }
        });
    }
    await pool.query("DELETE FROM sessions WHERE expires_at<now()");
    await pool.query("DELETE FROM logout_events WHERE expires_at<now()");
    await pool.query(
      "DELETE FROM auth_flows WHERE created_at<now()-interval '10 minutes'",
    );
  } catch {
    console.error(
      "Worker dependency unavailable; retrying without logging message content or credentials.",
    );
  }
  if (!stopped) await new Promise((resolve) => setTimeout(resolve, 2000));
}
await pool.end();
