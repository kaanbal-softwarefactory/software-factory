"use client";
import { useState } from "react";
export default function ContactForm({ onSent }: { onSent?: () => void } = {}) {
  const [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [failed, setFailed] = useState(false);
  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        setMessage("");
        const body = Object.fromEntries(new FormData(event.currentTarget));
        try {
          const result = await fetch("/api/business/contact", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          const data = await result.json();
          setFailed(!result.ok);
          if (result.ok) onSent?.();
          setMessage(
            result.ok
              ? "Recibimos tu solicitud. Nuestro equipo le dará seguimiento."
              : data.error,
          );
        } catch {
          setFailed(true);
          setMessage("No pudimos enviar tu mensaje. Intenta de nuevo.");
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="form-grid">
        <label>
          Tu nombre
          <input
            name="name"
            required
            minLength={2}
            maxLength={120}
            autoComplete="name"
          />
        </label>
        <label>
          Correo electrónico
          <input
            name="email"
            type="email"
            required
            maxLength={254}
            autoComplete="email"
          />
        </label>
      </div>
      <label>
        Cuéntanos qué necesitas
        <textarea name="message" required minLength={5} maxLength={4000} />
      </label>
      <div className="honeypot" aria-hidden="true">
        <label>
          Deja este campo vacío
          <input name="website" tabIndex={-1} autoComplete="off" />
        </label>
      </div>
      <button disabled={busy}>
        {busy ? "Enviando…" : "Enviar solicitud ↗"}
      </button>
      {message && (
        <p role="status" className={`status ${failed ? "error" : ""}`}>
          {message}
        </p>
      )}
    </form>
  );
}
