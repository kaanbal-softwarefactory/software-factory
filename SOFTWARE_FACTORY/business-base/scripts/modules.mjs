// Shared by local copies and the managed bootstrap. This value contains no credentials.
export function parseModules(value) {
  if (value === undefined || value === null || value === "null") return null;
  const modules = typeof value === "string" ? JSON.parse(value) : value;
  const available = ["contact", "catalog", "appointments"];
  if (!Array.isArray(modules) || modules.some((item) => !available.includes(item)))
    throw new Error("Modules must contain only contact, catalog or appointments");
  const selected = new Set(modules);
  if (selected.has("appointments")) selected.add("catalog");
  return available.filter((item) => selected.has(item));
}

export function modulesOption(value, fallback) {
  return value === undefined ? parseModules(fallback) : parseModules(value === "none" ? [] : value.split(","));
}
