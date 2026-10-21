"use client";
import { useEffect, useState, useCallback } from "react";
import { allows, type Role } from "../lib/policy";
import { dashboardMembers, type DashboardMode } from "../lib/dashboard";
import ContactForm from "./ContactForm";
import { enabledModules, type BusinessModule } from "../lib/features";
import AppointmentCalendar from "./AppointmentCalendar";

type Member = {
  organization_id: string;
  name: string;
  slug: string;
  role: Role;
  experience?: string;
  enabled_modules?: BusinessModule[] | null;
  timezone?: string;
};
type User = {
  id: string;
  name: string;
  email: string;
  mfa: boolean;
  memberships: Member[];
};
type RecordRow = Record<string, string | number | boolean | null>;
const roleNames: Record<Role, string> = { owner: "Propietario", admin: "Administrador", staff: "Colaborador", customer: "Cliente" };
const requestStates: Record<string, string> = { new: "Nueva", assigned: "En atención", closed: "Cerrada" };
const requestState = (state: RecordRow[string]) => requestStates[String(state)] || String(state);
async function api(path: string, body?: unknown) {
  const result = await fetch(`/api/business/${path}`, {
    method: body === undefined ? "GET" : "POST",
    cache: "no-store",
    ...(body === undefined
      ? {}
      : {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
  });
  const data = await result.json();
  if (!result.ok) {
    if (result.status === 401) throw new Error("Inicia sesión para continuar");
    throw new Error(data.error || "No se pudo completar la operación");
  }
  return data;
}

export default function Workspace({ mode }: { mode: DashboardMode }) {
  const [user, setUser] = useState<User | null>(null),
    [org, setOrg] = useState(""),
    [tab, setTab] = useState("overview");
  const [rows, setRows] = useState<RecordRow[]>([]),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [loaded, setLoaded] = useState(false);
  const [catalog, setCatalog] = useState<RecordRow[]>([]),
    [resources, setResources] = useState<RecordRow[]>([]),
    [invite, setInvite] = useState("");
  const [invitation, setInvitation] = useState<{
    token: string;
    organization: string;
  } | null>(null);
  const [publicOrg, setPublicOrg] = useState("");
  const member = user?.memberships.find((m) => m.organization_id === org);
  const role = member?.role || "customer";
  const modules = enabledModules(member?.experience, member?.enabled_modules);
  const hasContact = modules.includes("contact"), hasAppointments = modules.includes("appointments"), hasCatalog = modules.includes("catalog");
  const reload = useCallback(async () => {
    if (!org) return;
    setBusy(true);
    setError("");
    try {
      const resource = tab === "overview" ? "requests" : tab;
      setRows(tab === "overview" && !hasContact ? [] : await api(`${org}/${resource}`));
      if (tab === "appointments") {
        setCatalog(await api(`${org}/catalog`));
        setResources(await api(`${org}/resources`));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [org, tab, hasContact]);
  async function loadMe() {
    const me = (await api("me")) as User;
    me.memberships = dashboardMembers({ ...me, email_verified: true }, mode);
    if (mode === "client") setPublicOrg((await api("public")).organization.id);
    setUser(me);
    setOrg((current) =>
      me.memberships.some((m) => m.organization_id === current)
        ? current
        : me.memberships[0]?.organization_id || "",
    );
  }
  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    if (params.get("invite") && params.get("organization")) {
      sessionStorage.setItem(
        "pending-invitation",
        JSON.stringify({
          token: params.get("invite"),
          organization: params.get("organization"),
        }),
      );
      history.replaceState(null, "", "/workspace");
    }
    const pending = sessionStorage.getItem("pending-invitation");
    if (pending) {
      try {
        setInvitation(JSON.parse(pending));
      } catch {
        sessionStorage.removeItem("pending-invitation");
      }
    }
    loadMe()
      .catch((e) => setError(e.message))
      .finally(() => setLoaded(true));
  }, []);
  useEffect(() => {
    setRows([]);
    setNotice("");
    setInvite("");
    void reload();
  }, [reload]);
  const links = [
    { id: "overview", name: "Resumen" },
    ...(hasContact ? [{
      id: "requests",
      name: allows(role, "inbox.read") ? "Solicitudes" : "Mis solicitudes",
    }] : []),
    ...(hasAppointments ? [{
      id: "appointments",
      name: allows(role, "appointments.manage") ? "Citas" : "Mis citas",
    }] : []),
    ...(hasCatalog ? [{ id: "catalog", name: "Catálogo" }] : []),
    ...(allows(role, "members.manage")
      ? [{ id: "members", name: "Equipo y accesos" }]
      : []),
    ...(allows(role, "audit.read") ? [{ id: "audit", name: "Auditoría" }] : []),
    ...(allows(role, "catalog.manage")
      ? [{ id: "settings", name: "Mi negocio" }]
      : []),
    { id: "notifications", name: "Notificaciones" },
  ];
  async function change(resource: string, body: unknown) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api(`${org}/${resource}`, body);
      setNotice("Cambio guardado.");
      await reload();
      return result;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!user)
    return (
      <main className="shell section">
        <a className="brand" href="/">
          ← Volver al sitio
        </a>
        <h1>Tu espacio de trabajo.</h1>
        <p>
          {loaded
            ? "Inicia sesión para consultar tus servicios y solicitudes."
            : "Preparando tu espacio…"}
        </p>
        {error && (
          <p role="alert" className="status error">
            {error}
          </p>
        )}
        <a className="button" href="/auth/login">
          Entrar con mi cuenta ↗
        </a>
      </main>
    );
  return (
    <div className={`app-shell dashboard-${mode}`}>
      <aside className="sidebar">
        <a className="brand" href="/">
          <span className="brand-mark">{member?.name?.slice(0, 1) || "k"}</span>{member?.name || "Mi espacio"}
        </a>
        <div>
          <span className="eyebrow">{mode === "admin" ? "Administración" : "Portal de clientes"}</span>
          <nav>
            {links.map((link) => (
              <button
                key={link.id}
                className={tab === link.id ? "active" : ""}
                onClick={() => setTab(link.id)}
              >
                {link.name}
              </button>
            ))}
          </nav>
        </div>
        <div className="sidebar-bottom">
          <p className="muted">
            Un buen sistema deja
            <br />
            espacio para crecer.
          </p>
          <a href="/">Ver sitio público ↗</a>
        </div>
      </aside>
      <main className="workspace">
        <header className="workspace-top">
          <div>
            <small>Hola, {user.name}</small>
            <div className="row">
              <strong>{member?.name || "Sin organización"}</strong>
              <span className="tag">{roleNames[role]}</span>
            </div>
          </div>
          <div className="row">
            <select
              aria-label="Organización"
              value={org}
              onChange={(e) => {
                setOrg(e.target.value);
                setTab("overview");
              }}
            >
              {user.memberships.map((m) => (
                <option key={m.organization_id} value={m.organization_id}>
                  {m.name}
                </option>
              ))}
            </select>
            <button
              className="secondary small"
              onClick={async () => {
                try {
                  const response = await fetch("/auth/logout", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: "{}",
                  });
                  if (!response.ok) throw new Error();
                  window.location.href = (await response.json()).redirect;
                } catch {
                  setError("No se pudo cerrar la sesión");
                }
              }}
            >
              Salir
            </button>
          </div>
        </header>
        <span className="eyebrow">{mode === "admin" ? "Panel administrativo" : "Mi espacio de cliente"}</span>
        <h1>{links.find((l) => l.id === tab)?.name}</h1>
        <p className="muted">
          {tab === "overview"
            ? (mode === "admin" ? "Tu operación, en perspectiva. Lo importante empieza aquí." : "Tus solicitudes y novedades, en un solo lugar.")
            : (mode === "admin" ? "Gestiona la información de tu organización." : "Consulta el seguimiento de tu cuenta.")}
        </p>
        {!user.mfa && ["owner", "admin"].includes(role) && (
          <section className="status">
            <p>Tu administración requiere una sesión con MFA verificado.</p>
            <div className="row">
              <a className="button secondary" href="/auth/login?setup_mfa=1">
                Configurar autenticador
              </a>
              <a className="button" href="/auth/login?fresh=1">
                Verificar MFA
              </a>
            </div>
          </section>
        )}
        {error && (
          <p role="alert" className="status error">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="status">
            {notice}
          </p>
        )}
        {invitation && (
          <section className="card">
            <h3>Tienes una invitación pendiente</h3>
            <p>
              Comprueba que estás usando el correo al que se envió la
              invitación.
            </p>
            <button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api("accept-invitation", invitation);
                  sessionStorage.removeItem("pending-invitation");
                  setInvitation(null);
                  await loadMe();
                  setNotice("Invitación aceptada.");
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Aceptar invitación
            </button>
          </section>
        )}
        {!org && (
          <p className="empty">
            Tu cuenta está lista. Necesitas una invitación o una membresía para
            acceder a una organización.
          </p>
        )}
        {org && tab === "overview" && (
          <>
            {hasContact && <div className="metrics">
              <div className="card metric">
                <small>Solicitudes visibles</small>
                <strong>{rows.length}</strong>
              </div>
              <div className="card metric">
                <small>Pendientes</small>
                <strong>
                  {rows.filter((r) => r.state !== "closed").length}
                </strong>
              </div>
              <div className="card metric">
                <small>Tu acceso</small>
                <strong style={{ fontSize: "1.5rem" }}>{roleNames[role]}</strong>
              </div>
            </div>}
            <section className="card">
              <span className="eyebrow">El siguiente paso</span>
              <h2>{hasContact ? (mode === "admin" ? "Dale seguimiento a cada conversación." : "Estamos para acompañarte.") : "Tu espacio está listo para crecer."}</h2>
              <p className="muted">
                {hasContact ? (mode === "admin" ? "Consulta las solicitudes del equipo y mantén la atención al día." : "Envía una solicitud desde tu cuenta y consulta aquí su avance.") : "Accede a las funciones disponibles desde el menú de tu cuenta."}
              </p>
              <div className="row">
                {hasContact && <button onClick={() => setTab("requests")}>
                  Ver solicitudes →
                </button>}
                {hasAppointments && <button
                  className="secondary"
                  onClick={() => setTab("appointments")}
                >
                  Consultar citas
                </button>}
              </div>
            </section>
            {hasContact && <section className="recent-panel">
              <div className="section-head"><h2>Actividad reciente</h2><button className="secondary small" onClick={() => setTab("requests")}>Ver solicitudes →</button></div>
              {busy ? <p role="status">Cargando actividad…</p> : rows.length ? rows.slice(0, 4).map((row) => (
                <article className="activity-row" key={String(row.id)}><span className="activity-dot" /><div><strong>{row.name}</strong><p>{String(row.message).slice(0, 100)}</p></div><span className="tag">{requestState(row.state)}</span></article>
              )) : <p className="empty">Todavía no hay solicitudes. Las nuevas conversaciones aparecerán aquí.</p>}
            </section>}
          </>
        )}
        {org && hasContact && tab === "requests" && (
          <div className="list">
            {mode === "client" && org === publicOrg && <section className="card"><h2>Crear una solicitud</h2><p className="muted">Tu mensaje quedará vinculado a esta cuenta.</p><ContactForm onSent={() => void reload()} /></section>}
            {rows.map((row) => (
              <article className="item" key={String(row.id)}>
                <div className="item-head">
                  <strong>{row.name}</strong>
                  <span className="tag">{requestState(row.state)}</span>
                </div>
                <small>
                  {row.email} ·{" "}
                  {new Date(String(row.created_at)).toLocaleString("es-MX")}
                </small>
                <p>{row.message}</p>
                {allows(role, "inbox.manage") && (
                  <div className="row">
                    <button
                      className="secondary small"
                      disabled={busy}
                      onClick={() =>
                        change("requests", { id: row.id, state: "assigned" })
                      }
                    >
                      Asignarme
                    </button>
                    <button
                      className="secondary small"
                      disabled={busy}
                      onClick={() =>
                        change("requests", {
                          id: row.id,
                          state: row.state === "closed" ? "new" : "closed",
                        })
                      }
                    >
                      {row.state === "closed" ? "Reabrir" : "Cerrar"}
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
        {org && hasCatalog && tab === "catalog" && (
          <div className="two-col">
            <div className="list">
              {rows.map((row) => (
                <article className="item" key={String(row.id)}>
                  <h3>{row.name}</h3>
                  <p>{row.description}</p>
                  <span className="tag">
                    {Number(row.price_cents) / 100} MXN · {row.duration_minutes}{" "}
                    min
                  </span>
                </article>
              ))}
            </div>
            {allows(role, "catalog.manage") && (
              <form
                className="card"
                onSubmit={(event) => {
                  event.preventDefault();
                  const form = event.currentTarget,
                    body = Object.fromEntries(new FormData(form));
                  void change("catalog", {
                    ...body,
                    price_cents: Math.round(Number(body.price) * 100),
                    duration_minutes: Number(body.duration_minutes),
                  }).then((result) => {
                    if (result) form.reset();
                  });
                }}
              >
                <h3>Agregar servicio</h3>
                <label>
                  Nombre
                  <input name="name" required minLength={2} maxLength={120} />
                </label>
                <label>
                  Descripción
                  <textarea name="description" maxLength={1000} />
                </label>
                <div className="form-grid">
                  <label>
                    Precio MXN
                    <input
                      name="price"
                      type="number"
                      required
                      min="0"
                      step="0.01"
                    />
                  </label>
                  <label>
                    Duración (min)
                    <input
                      name="duration_minutes"
                      type="number"
                      min="5"
                      max="480"
                      defaultValue="30"
                      required
                    />
                  </label>
                </div>
                <button disabled={busy}>Guardar servicio</button>
              </form>
            )}
          </div>
        )}
        {org && hasAppointments && tab === "appointments" && (
          <>
          {allows(role, "appointments.manage") && <AppointmentCalendar key={org} organization={org} timezone={member?.timezone || "UTC"} revision={rows} />}
          {rows.length >= 1000 && <p className="status">La lista muestra hasta 1,000 citas. Consulta el calendario para buscar por semana.</p>}
          <div className="two-col">
            <div className="list">
              {rows.map((row) => (
                <article className="item" key={String(row.id)}>
                  <div className="item-head">
                    <strong>{row.service}</strong>
                    <span className="tag">{row.state}</span>
                  </div>
                  <p>
                    {new Date(String(row.starts_at)).toLocaleString("es-MX")} ·{" "}
                    {row.resource}
                  </p>
                  {row.state === "confirmed" && (
                    <button
                      className="secondary small"
                      disabled={busy}
                      onClick={() =>
                        change("cancel-appointment", { id: row.id })
                      }
                    >
                      Cancelar cita
                    </button>
                  )}
                </article>
              ))}
            </div>
            <form
              className="card"
              onSubmit={(event) => {
                event.preventDefault();
                const body = Object.fromEntries(
                  new FormData(event.currentTarget),
                );
                void change("appointments", {
                  ...body,
                  starts_at: new Date(String(body.starts_at)).toISOString(),
                });
              }}
            >
              <h3>Reservar un servicio</h3>
              <p className="muted">
                Horario piloto: lunes a viernes, 09:00–18:00 en la zona del
                negocio. La fecha se introduce en la zona de tu dispositivo.
              </p>
              <label>
                Servicio
                <select name="service_id" required>
                  {catalog
                    .filter((c) => c.active)
                    .map((c) => (
                      <option key={String(c.id)} value={String(c.id)}>
                        {c.name}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Profesional
                <select name="resource_id" required>
                  {resources.map((r) => (
                    <option key={String(r.id)} value={String(r.id)}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Fecha y hora
                <input type="datetime-local" name="starts_at" required />
              </label>
              <button disabled={busy || !catalog.length || !resources.length}>
                Confirmar reserva
              </button>
            </form>
          </div>
          </>
        )}
        {org && tab === "members" && (
          <div className="two-col">
            <div className="list">
              {rows.map((row) => (
                <article className="item" key={String(row.person_id)}>
                  <div className="item-head">
                    <strong>{row.name}</strong>
                    <span className="tag">{row.role}</span>
                  </div>
                  <p>
                    {row.email} · {row.active ? "Activo" : "Suspendido"}
                  </p>
                  {row.role !== "owner" && (
                    <button
                      className="secondary small"
                      disabled={busy}
                      onClick={() =>
                        change("members", {
                          person_id: row.person_id,
                          role: row.role,
                          active: !row.active,
                        })
                      }
                    >
                      {row.active ? "Suspender acceso" : "Reactivar acceso"}
                    </button>
                  )}
                </article>
              ))}
            </div>
            <form
              className="card"
              onSubmit={async (event) => {
                event.preventDefault();
                const result = await change(
                  "invitations",
                  Object.fromEntries(new FormData(event.currentTarget)),
                );
                if (result)
                  setInvite(
                    `${window.location.origin}/workspace#organization=${org}&invite=${result.token}`,
                  );
              }}
            >
              <h3>Invitar al equipo</h3>
              <label>
                Correo electrónico
                <input name="email" type="email" required />
              </label>
              <label>
                Rol
                <select name="role">
                  <option value="staff">Colaborador</option>
                  <option value="admin">Administrador</option>
                  <option value="customer">Cliente</option>
                </select>
              </label>
              <button disabled={busy}>Crear invitación</button>
              {invite && (
                <label>
                  Enlace privado · vence en 48 horas
                  <textarea
                    readOnly
                    value={invite}
                    onFocus={(e) => e.target.select()}
                  />
                  <small>
                    Compártelo únicamente con la persona invitada. Debe
                    verificar ese correo.
                  </small>
                </label>
              )}
            </form>
          </div>
        )}
        {org && tab === "audit" && (
          <div className="list">
            {rows.map((row, index) => (
              <article className="item" key={index}>
                <strong>{row.action}</strong>
                <p>{row.resource}</p>
                <small>
                  {new Date(String(row.created_at)).toLocaleString("es-MX")}
                </small>
              </article>
            ))}
          </div>
        )}
        {org && tab === "settings" && rows[0] && (
          <form
            className="card"
            style={{ maxWidth: 700, marginTop: "2rem" }}
            onSubmit={async (event) => {
              event.preventDefault();
              const result = await change(
                "settings",
                Object.fromEntries(new FormData(event.currentTarget)),
              );
              if (result) await loadMe();
            }}
          >
            <h3>Información de tu negocio</h3>
            <p className="muted">
              Los cambios aparecen en tu sitio público. {hasAppointments ? "La zona horaria define el horario de las reservas." : "Personaliza la presentación de tu marca."}
            </p>
            <label>
              Nombre
              <input
                name="name"
                required
                minLength={2}
                maxLength={100}
                defaultValue={String(rows[0].name)}
              />
            </label>
            <label>
              Presentación
              <textarea
                name="description"
                maxLength={2000}
                defaultValue={String(rows[0].description)}
              />
            </label>
            <label>
              WhatsApp (con código de país)
              <input
                name="whatsapp"
                maxLength={30}
                defaultValue={String(rows[0].whatsapp)}
              />
            </label>
            <label>
              Zona horaria IANA
              <input
                name="timezone"
                required
                maxLength={80}
                defaultValue={String(rows[0].timezone)}
              />
            </label>
            <button disabled={busy}>Guardar información</button>
          </form>
        )}
        {org && tab === "notifications" && (
          <div className="list">
            {rows.map((row, index) => (
              <article className="item" key={index}>
                <strong>{row.title}</strong>
                <p>
                  {new Date(String(row.created_at)).toLocaleString("es-MX")}
                </p>
              </article>
            ))}
          </div>
        )}
        {org && !rows.length && tab !== "overview" && !busy && (
          <p className="empty">
            Todo listo. Aún no hay registros en esta sección.
          </p>
        )}
        <footer className="footer">
          <span>{member?.name}</span>
          <a href="/">Ver sitio público ↗</a>
        </footer>
      </main>
    </div>
  );
}
