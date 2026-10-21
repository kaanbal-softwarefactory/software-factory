import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { actorForToken, sessionCookie } from "../lib/session";
import { Problem } from "../lib/policy";
import { dashboardHome, dashboardMembers, type DashboardMode } from "../lib/dashboard";
import Workspace from "./Workspace";

export default async function Dashboard({ mode }: { mode?: DashboardMode }) {
  let user;
  try {
    user = await actorForToken((await cookies()).get(sessionCookie)?.value);
  } catch (error) {
    if (error instanceof Problem && error.status === 401) redirect("/auth/login");
    throw error;
  }
  if (!mode) redirect(dashboardHome(user));
  const members = dashboardMembers(user, mode);
  if (!members.length) return (
    <main className="shell section access-card">
      <a className="brand" href="/">← Volver al sitio</a>
      <span className="eyebrow">Acceso por organización</span>
      <h1>Este espacio necesita otro acceso.</h1>
      <p>Tu cuenta no tiene una membresía activa para este panel. Si esperabas acceso, solicita una invitación al responsable.</p>
      <a className="button" href={dashboardHome(user)}>Ir a mi espacio →</a>
    </main>
  );
  // APIs revalidate membership and MFA for every read/write. No data is loaded here.
  return <Workspace mode={mode} />;
}
