/**
 * Capa de datos del ejemplo.
 *
 * Kaanbal publica la conexión de una base vinculada con los nombres
 * convencionales de su motor (MONGODB_URI, POSTGRES_URL, DATABASE_URL…), así
 * que aquí no se configura nada: se mira qué llegó y se usa. Sin base
 * vinculada la app sigue arrancando con datos en memoria y lo dice en pantalla,
 * para que una demo nunca muera en CrashLoopBackOff.
 */

export type Note = {
  id: string;
  title: string;
  body: string;
  createdAt: string;
};

export type Backend = {
  kind: "mongodb" | "postgres" | "memory";
  detail: string;
};

export type NotesPage = {
  notes: Note[];
  backend: Backend;
};

const SEED: Array<Pick<Note, "title" | "body">> = [
  { title: "Primera nota", body: "Este registro vino con la plantilla. Edítalo o bórralo." },
  { title: "Cómo conectar tu base", body: "Vincula una base desde la consola o con el MCP; la app la detecta sola." },
];

const MONGO_VARS = ["MONGODB_URI", "MONGO_URI", "MONGODB_URL", "MONGO_URL"];
const POSTGRES_VARS = ["POSTGRES_URI", "POSTGRES_URL"];

function firstValue(names: string[]): string | undefined {
  for (const name of names) {
    const value = process.env[name];
    if (value && value.trim()) return value.trim();
  }
  return undefined;
}

function scheme(uri: string): string {
  return uri.split("://", 1)[0].toLowerCase();
}

export function mongoUri(): string | undefined {
  const direct = firstValue(MONGO_VARS);
  if (direct) return direct;
  const generic = firstValue(["DATABASE_URL"]);
  if (generic && scheme(generic).startsWith("mongodb")) return generic;
  return undefined;
}

export function postgresUri(): string | undefined {
  const direct = firstValue(POSTGRES_VARS);
  if (direct) return direct;
  const generic = firstValue(["DATABASE_URL"]);
  if (generic && ["postgres", "postgresql"].includes(scheme(generic))) return generic;

  // libpq: con PGHOST y compañía, el driver arma la conexión por su cuenta.
  const host = firstValue(["POSTGRES_HOST", "PGHOST"]);
  const user = firstValue(["POSTGRES_USER", "PGUSER"]);
  const password = firstValue(["POSTGRES_PASSWORD", "PGPASSWORD"]);
  const database = firstValue(["POSTGRES_DB", "PGDATABASE"]);
  if (host && user && password && database) {
    const port = firstValue(["POSTGRES_PORT", "PGPORT"]) ?? "5432";
    const credentials = `${encodeURIComponent(user)}:${encodeURIComponent(password)}`;
    return `postgresql://${credentials}@${host}:${port}/${database}`;
  }
  return undefined;
}

function mongoDatabase(uri: string): string {
  const explicit = firstValue(["MONGO_DATABASE", "MONGODB_DATABASE", "MONGO_DB"]);
  if (explicit) return explicit;
  const path = uri.split("://")[1]?.split("/")[1]?.split("?")[0];
  return path && path.length ? path : "app";
}

function newId(): string {
  return Math.random().toString(36).slice(2, 10);
}

// ── Memoria ────────────────────────────────────────────────────────────────
// Un módulo se recarga en desarrollo; globalThis sobrevive a esa recarga.
const memory: Note[] = ((globalThis as Record<string, unknown>).__kaanbalNotes as Note[]) ?? [];
(globalThis as Record<string, unknown>).__kaanbalNotes = memory;

if (memory.length === 0) {
  for (const seed of SEED) {
    memory.push({ ...seed, id: newId(), createdAt: new Date().toISOString() });
  }
}

// ── MongoDB ────────────────────────────────────────────────────────────────
async function mongoCollection(uri: string) {
  const { MongoClient } = await import("mongodb");
  const cache = globalThis as Record<string, unknown>;
  if (!cache.__kaanbalMongo) {
    cache.__kaanbalMongo = new MongoClient(uri).connect();
  }
  const client = (await cache.__kaanbalMongo) as import("mongodb").MongoClient;
  return client.db(mongoDatabase(uri)).collection("notes");
}

async function mongoList(uri: string): Promise<Note[]> {
  const collection = await mongoCollection(uri);
  if ((await collection.estimatedDocumentCount()) === 0) {
    await collection.insertMany(
      SEED.map((seed) => ({ ...seed, id: newId(), createdAt: new Date().toISOString() })),
    );
  }
  const documents = await collection.find({}, { projection: { _id: 0 } }).sort({ createdAt: -1 }).limit(50).toArray();
  return documents as unknown as Note[];
}

// ── PostgreSQL ─────────────────────────────────────────────────────────────
async function postgresPool(uri: string) {
  const { Pool } = await import("pg");
  const cache = globalThis as Record<string, unknown>;
  if (!cache.__kaanbalPg) {
    cache.__kaanbalPg = new Pool({ connectionString: uri, max: 4 });
  }
  const pool = cache.__kaanbalPg as import("pg").Pool;
  await pool.query(
    "CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
  );
  return pool;
}

async function postgresList(uri: string): Promise<Note[]> {
  const pool = await postgresPool(uri);
  const count = await pool.query<{ total: string }>("SELECT count(*)::text AS total FROM notes");
  if (count.rows[0]?.total === "0") {
    for (const seed of SEED) {
      await pool.query("INSERT INTO notes (id, title, body) VALUES ($1, $2, $3)", [newId(), seed.title, seed.body]);
    }
  }
  const rows = await pool.query<{ id: string; title: string; body: string; created_at: Date }>(
    "SELECT id, title, body, created_at FROM notes ORDER BY created_at DESC LIMIT 50",
  );
  return rows.rows.map((row) => ({
    id: row.id,
    title: row.title,
    body: row.body,
    createdAt: row.created_at.toISOString(),
  }));
}

// ── API de la plantilla ────────────────────────────────────────────────────
export async function listNotes(): Promise<NotesPage> {
  const mongo = mongoUri();
  if (mongo) {
    return { notes: await mongoList(mongo), backend: { kind: "mongodb", detail: "MongoDB vinculada por Kaanbal" } };
  }
  const postgres = postgresUri();
  if (postgres) {
    return { notes: await postgresList(postgres), backend: { kind: "postgres", detail: "PostgreSQL vinculada por Kaanbal" } };
  }
  return {
    notes: [...memory].reverse(),
    backend: { kind: "memory", detail: "Sin base vinculada: los datos viven en memoria y se pierden al reiniciar" },
  };
}

export async function createNote(title: string, body: string): Promise<Note> {
  const note: Note = { id: newId(), title, body, createdAt: new Date().toISOString() };

  const mongo = mongoUri();
  if (mongo) {
    const collection = await mongoCollection(mongo);
    await collection.insertOne({ ...note });
    return note;
  }

  const postgres = postgresUri();
  if (postgres) {
    const pool = await postgresPool(postgres);
    await pool.query("INSERT INTO notes (id, title, body) VALUES ($1, $2, $3)", [note.id, note.title, note.body]);
    return note;
  }

  memory.push(note);
  return note;
}
