import NoteForm from "@/components/NoteForm";
import { listNotes } from "@/lib/notes";

export const dynamic = "force-dynamic";

const BACKEND_LABEL: Record<string, string> = {
  mongodb: "MongoDB",
  postgres: "PostgreSQL",
  memory: "memoria",
};

export default async function Home() {
  const { notes, backend } = await listNotes();

  return (
    <main>
      <header className="card">
        <h1>placeholder-app</h1>
        <p className="muted">
          Next.js sirviendo el frontend y el backend en la misma app. Esta página se renderiza en el
          servidor y lee los datos directamente; el formulario escribe por <code>/api/notes</code>.
        </p>
        <p>
          <span className="badge">Datos en {BACKEND_LABEL[backend.kind] ?? backend.kind}</span>
        </p>
        <p className="muted">{backend.detail}</p>
      </header>

      <section className="card">
        <h2>Agregar una nota</h2>
        <NoteForm />
      </section>

      <section>
        <ul>
          {notes.map((note) => (
            <li key={note.id} className="note">
              <strong>{note.title}</strong>
              {note.body ? <p>{note.body}</p> : null}
              <p className="muted">{new Date(note.createdAt).toLocaleString("es-MX")}</p>
            </li>
          ))}
        </ul>
      </section>

      <footer className="muted">
        Salud del proceso en <a href="/api/health">/api/health</a> · lanzado con Kaanbal
      </footer>
    </main>
  );
}
