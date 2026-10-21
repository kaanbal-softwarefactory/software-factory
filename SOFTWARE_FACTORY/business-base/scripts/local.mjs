import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
const config = existsSync("business.config.json")
  ? JSON.parse(readFileSync("business.config.json", "utf8"))
  : {};
const [action, ...args] = process.argv.slice(2);
function option(name, fallback) {
  const i = args.indexOf(name);
  return i < 0 ? fallback : args[i + 1];
}
const name = option("--name", config.name || "business-reference"),
  port = Number(option("--port", config.port || "3100")),
  identity = Number(option("--identity-port", config.identityPort || "8180")),
  mail = Number(option("--mail-port", config.mailPort || "8125"));
if (
  !/^[a-z][a-z0-9-]{2,45}$/.test(name) ||
  [port, identity, mail].some(
    (n) => !Number.isInteger(n) || n < 1024 || n > 65535,
  ) ||
  new Set([port, identity, mail]).size !== 3
)
  throw new Error("Invalid project name or distinct local ports");
const env = {
  ...process.env,
  APP_PORT: String(port),
  IDENTITY_PORT: String(identity),
  MAIL_PORT: String(mail),
  BUSINESS_PRESET: option("--preset", config.preset || "services"),
  BUSINESS_NAME: option("--title", config.title || "Estudio Demo"),
};
if (!["starter", "services", "barber"].includes(env.BUSINESS_PRESET)) throw new Error("Preset must be starter, services or barber");
const base = ["compose", "--project-name", name];
let command;
if (action === "up")
  command = [
    ...base,
    "up",
    "--build",
    "--detach",
    "--wait",
    "--wait-timeout",
    "240",
  ];
else if (action === "stop") command = [...base, "stop"];
else if (action === "access")
  command = [
    ...base,
    "run",
    "--rm",
    "--no-deps",
    "--entrypoint",
    "node",
    "bootstrap",
    "-e",
    `const fs=require('fs'); for(const [user,file] of [['owner','owner-password'],['customer','customer-password'],['local-admin','admin-password']])console.log(user+': '+fs.readFileSync('/bootstrap/'+file,'utf8')); console.log('Owner requires MFA enrollment. These credentials are only for this local project.')`,
  ];
else
  throw new Error(
    "Use up, stop or access. No delete operation is performed by this tool.",
  );
const result = spawnSync("docker", command, { env, stdio: "inherit" });
if (result.error) throw result.error;
if (result.status) process.exit(result.status);
if (action === "up")
  console.log(
    `App: http://localhost:${port}\nIdentity: http://localhost:${identity}\nLocal mail: http://localhost:${mail}\nProject: ${name}\nRun local:access in your own terminal to view credentials. Copies require a new name and distinct ports.`,
  );
