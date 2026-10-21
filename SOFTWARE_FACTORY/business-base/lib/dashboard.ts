import type { Actor } from "./session";

export type DashboardMode = "admin" | "client";
export function dashboardMembers(user: Actor, mode: DashboardMode) {
  return user.memberships.filter((m) =>
    mode === "client" ? m.role === "customer" : ["owner", "admin", "staff"].includes(m.role),
  );
}
export function dashboardHome(user: Actor) {
  return dashboardMembers(user, "admin").length ? "/admin" : "/client";
}
