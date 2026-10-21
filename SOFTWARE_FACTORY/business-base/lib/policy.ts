export type Role = "owner" | "admin" | "staff" | "customer";
export type Action =
  | "inbox.read"
  | "inbox.manage"
  | "catalog.manage"
  | "members.manage"
  | "audit.read"
  | "appointments.manage";
const permissions: Record<Role, readonly Action[]> = {
  owner: [
    "inbox.read",
    "inbox.manage",
    "catalog.manage",
    "members.manage",
    "audit.read",
    "appointments.manage",
  ],
  admin: [
    "inbox.read",
    "inbox.manage",
    "catalog.manage",
    "audit.read",
    "appointments.manage",
  ],
  staff: ["inbox.read", "inbox.manage", "appointments.manage"],
  customer: [],
};
export function allows(role: Role, action: Action): boolean {
  return permissions[role]?.includes(action) || false;
}
export function hasMFA(claims: { amr?: unknown; acr?: unknown }): boolean {
  const methods = Array.isArray(claims.amr) ? claims.amr : [];
  return (
    methods.includes("mfa") ||
    (methods.includes("pwd") && methods.includes("otp")) ||
    Boolean(
      process.env.OIDC_ADMIN_ACR && claims.acr === process.env.OIDC_ADMIN_ACR,
    )
  );
}
export class Problem extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export function authorize(role: Role, action: Action) {
  if (!allows(role, action))
    throw new Problem(403, "No tienes permiso para esta operación");
}
export function ownOrManage(
  role: Role,
  actor: string,
  owner: string | null,
  action: Action,
) {
  if (!allows(role, action) && owner !== actor)
    throw new Problem(404, "Recurso no encontrado");
}
