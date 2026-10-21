import ContactForm from "./ContactForm";

export default function StarterLanding({ organization, authFailed }: {
  organization: { name: string; description: string }; authFailed: boolean;
}) {
  return <div className="starter-site">
    <a className="skip-link" href="#main">Saltar al contenido</a>
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="/"><span className="brand-mark">{organization.name.slice(0, 1)}</span>{organization.name}</a>
        <nav className="links" aria-label="Navegación principal"><a className="muted" href="#experience">Cómo funciona</a><a className="muted" href="#contact">Contacto</a><a className="button secondary" href="/client">Mi cuenta ↗</a></nav>
      </header>
      {authFailed && <p role="alert" className="status error">No se pudo completar el acceso. Intenta iniciar sesión de nuevo.</p>}
      <main id="main">
        <section className="starter-hero">
          <div className="starter-copy"><span className="pill"><span className="live-dot" />Un equipo. Un espacio. Más posibilidades.</span>
            <h1>Lo que sigue,<br />lo construimos<br /><span>contigo.</span></h1>
            <p>{organization.description}</p>
            <div className="row"><a className="button" href="#contact">Empecemos una conversación ↗</a><a className="text-link" href="/client">Entrar a mi espacio →</a></div>
            <div className="hero-note"><span className="note-symbol">✳</span><span>Atención cercana.<br /><strong>Seguimiento desde tu cuenta.</strong></span></div>
          </div>
          <div className="starter-art" aria-hidden="true">
            <div className="art-grid" /><span className="art-label">CADA CONEXIÓN ES UN COMIENZO</span>
            <div className="orb orb-one" /><div className="orb orb-two" /><div className="orb orb-three" />
            <div className="art-message"><span className="art-icon">↗</span><div>Las ideas crecen<br /><strong>cuando conectamos.</strong></div></div>
            <span className="art-caption">Un espacio para avanzar, a tu ritmo.</span>
          </div>
        </section>
        <section id="experience" className="starter-features">
          <div className="section-head"><div><span className="eyebrow">Simple, de principio a fin</span><h2>Menos vueltas.<br />Más claridad.</h2></div><p className="muted">Una experiencia pensada para que<br />siempre sepas cuál es el siguiente paso.</p></div>
          <div className="grid">
            {[
              ["01", "Conversemos", "Cuéntanos qué necesitas. Nuestro equipo recibe tu mensaje y te ayuda a encontrar el siguiente paso."],
              ["02", "Tu propio espacio", "Accede a tu cuenta para enviar solicitudes y consultar su estado, sin perder el hilo."],
              ["03", "Siempre en contacto", "Consulta las novedades de tu cuenta y continúa la conversación cuando lo necesites."],
            ].map(([number, title, description]) => <article className="feature" key={number}><span className="feature-number">{number} <span>↗</span></span><h3>{title}</h3><p>{description}</p></article>)}
          </div>
        </section>
        <section id="contact" className="section"><div className="contact starter-contact"><div><span className="eyebrow">El primer paso es una conversación</span><h2>Nos gustaría<br />saber de ti.</h2><p>Deja un mensaje y nuestro equipo le dará seguimiento.</p><a className="text-link" href="/client">¿Ya tienes cuenta? Entra a tu portal →</a></div><ContactForm /></div></section>
      </main>
      <footer className="footer"><a className="brand" href="/">{organization.name}</a><div className="row"><a href="/client">Portal de clientes</a><a href="/admin">Administración ↗</a></div></footer>
    </div>
  </div>;
}
