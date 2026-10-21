import ContactForm from "../components/ContactForm";
import { publicSite } from "../lib/business";
import StarterLanding from "../components/StarterLanding";
import { enabledModules } from "../lib/features";
export const dynamic = "force-dynamic";
export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ auth?: string }>;
}) {
  const params = await searchParams;
  let site;
  try {
    site = await publicSite();
  } catch {
    return (
      <main className="shell section">
        <h1>Estamos preparando tu espacio.</h1>
        <p>
          La aplicación está iniciando o esperando su configuración. Intenta de
          nuevo en un momento.
        </p>
      </main>
    );
  }
  const { organization, services } = site;
  const modules = enabledModules(organization.experience, organization.enabled_modules);
  if (organization.experience === "starter" || !modules.includes("catalog")) return <StarterLanding organization={organization} authFailed={params.auth === "failed"} />;
  const whatsapp = String(organization.whatsapp).replace(/[^0-9]/g, "");
  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="/">
          <span className="brand-mark">k</span>
          {organization.name}
        </a>
        <nav className="links">
          <a href="#services" className="muted">
            Servicios
          </a>
          {modules.includes("contact") && <a href="#contact" className="muted">
            Contacto
          </a>}
          <a className="button secondary" href="/auth/login">
            Mi cuenta ↗
          </a>
        </nav>
      </header>
      {params.auth === "failed" && (
        <p role="alert" className="status error">
          No se pudo completar el acceso. Inicia sesión de nuevo; si persiste,
          contacta al administrador.
        </p>
      )}
      <section className="hero">
        <div>
          <span className="eyebrow">Personas, servicios y conexiones</span>
          <h1>
            Más cerca de lo
            <br />
            que necesitas.
          </h1>
          <p>{organization.description}</p>
          <div className="row">
            <a className="button" href="#services">
              Explorar servicios ↗
            </a>
            {modules.includes("contact") && <a href="#contact">Hablemos →</a>}
          </div>
          <p>
            <small>Atención personal · Tu información en un solo lugar</small>
          </p>
        </div>
        <div className="hero-art">
          <span className="tag">Un espacio para ti</span>
          <h2>Las buenas experiencias empiezan aquí.</h2>
          <div className="mini-card">
            <span>
              ✳ &nbsp; Todo conectado.
              <br />
              <small style={{ color: "#d5e7d8" }}>
                Servicios, solicitudes y citas.
              </small>
            </span>
            <span>↗</span>
          </div>
        </div>
      </section>
      <section id="services" className="section">
        <div className="section-head">
          <div>
            <span className="eyebrow">Hecho para tu día a día</span>
            <h2>Nuestros servicios</h2>
          </div>
          <span className="muted">Encuentra tu próximo paso.</span>
        </div>
        <div className="grid">
          {services.map(
            (
              service: {
                id: string;
                name: string;
                description: string;
                duration_minutes: number;
                price_cents: number;
              },
              i: number,
            ) => (
              <article className="card" key={service.id}>
                <span className="tag">
                  0{i + 1} · {service.duration_minutes} min
                </span>
                <h3>{service.name}</h3>
                <p className="muted">{service.description}</p>
                <div className="row">
                  <strong>
                    {new Intl.NumberFormat("es-MX", {
                      style: "currency",
                      currency: "MXN",
                    }).format(service.price_cents / 100)}
                  </strong>
                  {modules.includes("appointments") && <a style={{ marginLeft: "auto" }} href="/workspace">
                    Reservar →
                  </a>}
                </div>
              </article>
            ),
          )}
        </div>
        {!services.length && (
          <p className="empty">
            Pronto publicaremos nuestros servicios. Mientras tanto, escríbenos.
          </p>
        )}
      </section>
      {modules.includes("contact") && <section id="contact" className="section">
        <div className="contact">
          <div>
            <span className="eyebrow">Una conversación lo cambia todo</span>
            <h2>
              ¿En qué podemos
              <br />
              ayudarte?
            </h2>
            <p>
              Envíanos tu solicitud. Nuestro equipo la recibe y te ayuda con el
              siguiente paso.
            </p>
            {whatsapp && (
              <a
                className="button secondary"
                href={`https://wa.me/${whatsapp}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                Escribir por WhatsApp ↗
              </a>
            )}
          </div>
          <ContactForm />
        </div>
      </section>}
      <footer className="footer">
        <span>{organization.name}</span>
        <span>Construido con Kaanbal · Base de referencia</span>
      </footer>
    </div>
  );
}
