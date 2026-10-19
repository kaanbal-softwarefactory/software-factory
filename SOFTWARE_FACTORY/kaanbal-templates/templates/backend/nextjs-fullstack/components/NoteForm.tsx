"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function NoteForm() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");

    try {
      const response = await fetch("/api/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, body }),
      });

      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { error?: string };
        setError(payload.error ?? "No se pudo guardar la nota");
        return;
      }

      setTitle("");
      setBody("");
      router.refresh();
    } catch {
      setError("No se pudo contactar al servidor");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder="Título"
        maxLength={120}
        required
      />
      <textarea
        value={body}
        onChange={(event) => setBody(event.target.value)}
        placeholder="Texto (opcional)"
        maxLength={2000}
        rows={3}
      />
      <button type="submit" disabled={saving}>
        {saving ? "Guardando…" : "Guardar"}
      </button>
      {error ? <p className="muted">{error}</p> : null}
    </form>
  );
}
