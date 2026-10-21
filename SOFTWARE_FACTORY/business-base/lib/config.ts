import { readFileSync } from "node:fs";

export function secret(name: string): string {
  if (process.env[`${name}_FILE`])
    return readFileSync(process.env[`${name}_FILE`]!, "utf8").trim();
  return process.env[name] || "";
}

export function origin(): string {
  const url = new URL(process.env.APP_ORIGIN || "http://localhost:3100");
  if (
    url.protocol !== "https:" &&
    !(
      process.env.LOCAL_DEVELOPMENT === "true" &&
      ["localhost", "127.0.0.1"].includes(url.hostname)
    )
  ) {
    throw new Error(
      "APP_ORIGIN must use HTTPS outside the loopback development profile",
    );
  }
  return url.origin;
}

export function issuer(): URL {
  const url = new URL(process.env.OIDC_ISSUER || "");
  if (
    url.protocol !== "https:" &&
    !(
      process.env.LOCAL_DEVELOPMENT === "true" &&
      ["localhost", "127.0.0.1"].includes(url.hostname)
    )
  ) {
    throw new Error("OIDC_ISSUER must use HTTPS");
  }
  return url;
}
