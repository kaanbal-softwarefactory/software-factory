import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  realpathSync,
} from "node:fs";
import { resolve, relative, sep, join } from "node:path";
import { fileURLToPath } from "node:url";
const source = realpathSync(fileURLToPath(new URL("..", import.meta.url))),
  args = process.argv.slice(2);
const option = (key, fallback) => {
  const i = args.indexOf(key);
  return i < 0 ? fallback : args[i + 1];
};
const name = option("--name", "business-copy"),
  preset = option("--preset", "services"),
  destination = option("--output", "");
if (
  !destination ||
  !/^[a-z][a-z0-9-]{2,45}$/.test(name) ||
  !["services", "barber"].includes(preset)
)
  throw new Error("Use --output PATH --name slug --preset services|barber");
const target = resolve(destination);
if (
  existsSync(target) ||
  target.toLowerCase() === source.toLowerCase() ||
  target.toLowerCase().startsWith((source + sep).toLowerCase())
)
  throw new Error(
    "Destination must be a new directory outside the source base",
  );
mkdirSync(target, { recursive: true });
const excluded = new Set(["node_modules", ".next", ".git", "coverage", "dist"]);
cpSync(source, target, {
  recursive: true,
  filter: (path) => {
    const pieces = relative(source, path).split(sep);
    return !pieces.some(
      (piece) =>
        excluded.has(piece) ||
        piece.startsWith(".env") ||
        piece.endsWith(".tsbuildinfo") ||
        piece.endsWith(".log") ||
        piece.endsWith(".tmp"),
    );
  },
});
const config = {
  name,
  title: option("--title", "Mi negocio"),
  preset,
  port: Number(option("--port", "3200")),
  identityPort: Number(option("--identity-port", "8280")),
  mailPort: Number(option("--mail-port", "8225")),
};
writeFileSync(
  join(target, "business.config.json"),
  JSON.stringify(config, null, 2) + "\n",
);
const manifest = JSON.parse(
  readFileSync(join(target, "business.manifest.json"), "utf8"),
);
writeFileSync(
  join(target, "business.manifest.json"),
  JSON.stringify(
    {
      ...manifest,
      instance: name,
      generated_from: "kaanbal-business-base@0.1.0",
    },
    null,
    2,
  ) + "\n",
);
console.log(
  `Copy created at ${target}. The reference source and all running data are unchanged.\nNext: npm ci, then npm run local:up inside the copy.`,
);
