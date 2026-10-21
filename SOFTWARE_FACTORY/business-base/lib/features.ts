export const businessModules = ["contact", "catalog", "appointments"] as const;
export type BusinessModule = (typeof businessModules)[number];

// null preserves the behavior of copies created before module selection existed.
export function enabledModules(experience?: string, selected?: BusinessModule[] | null): BusinessModule[] {
  const modules = new Set(selected ?? (experience === "starter" ? ["contact"] : businessModules));
  if (modules.has("appointments")) modules.add("catalog");
  return businessModules.filter((module) => modules.has(module));
}

export function resourceModule(resource: string): BusinessModule | undefined {
  if (resource === "requests") return "contact";
  if (resource === "catalog") return "catalog";
  if (["appointments", "cancel-appointment", "resources"].includes(resource)) return "appointments";
}
