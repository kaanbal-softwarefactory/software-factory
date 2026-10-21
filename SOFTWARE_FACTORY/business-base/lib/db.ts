import pg, { type PoolClient } from "pg";
import { secret } from "./config";

const globalDB = globalThis as unknown as { businessPool?: pg.Pool };
export const pool = (globalDB.businessPool ||= new pg.Pool({
  connectionString: process.env.DATABASE_URL,
  host: process.env.PGHOST,
  port: Number(process.env.PGPORT || 5432),
  user: process.env.PGUSER,
  password: secret("PGPASSWORD"),
  database: process.env.PGDATABASE,
  max: 8,
  connectionTimeoutMillis: 5000,
  idleTimeoutMillis: 10000,
}));

export async function transaction<T>(
  fn: (db: PoolClient) => Promise<T>,
): Promise<T> {
  const db = await pool.connect();
  try {
    await db.query("BEGIN");
    const result = await fn(db);
    await db.query("COMMIT");
    return result;
  } catch (error) {
    await db.query("ROLLBACK");
    throw error;
  } finally {
    db.release();
  }
}

export async function inOrganization<T>(
  id: string,
  fn: (db: PoolClient) => Promise<T>,
): Promise<T> {
  return transaction(async (db) => {
    await db.query("SELECT set_config('app.organization_id', $1, true)", [id]);
    return fn(db);
  });
}
