import * as oidc from "openid-client";
import { issuer, origin, secret } from "./config";

let configuration: Promise<oidc.Configuration> | undefined;
export function localFetch(
  input: string | URL,
  init?: {
    headers?: HeadersInit;
    method?: string;
    redirect?: RequestRedirect;
    signal?: AbortSignal | null;
    body?: unknown;
  },
) {
  let url = new URL(input);
  if (
    process.env.LOCAL_DEVELOPMENT === "true" &&
    process.env.OIDC_INTERNAL_ORIGIN &&
    url.origin === issuer().origin
  ) {
    const internal = new URL(process.env.OIDC_INTERNAL_ORIGIN);
    url = new URL(`${url.pathname}${url.search}`, internal);
  }
  return fetch(url, init as RequestInit);
}
export function oidcConfig() {
  return (configuration ||= oidc
    .discovery(
      issuer(),
      process.env.OIDC_CLIENT_ID || "business-base",
      secret("OIDC_CLIENT_SECRET"),
      undefined,
      {
        [oidc.customFetch]: localFetch,
        ...(process.env.LOCAL_DEVELOPMENT === "true"
          ? { execute: [oidc.allowInsecureRequests] }
          : {}),
      },
    )
    .catch((error) => {
      configuration = undefined;
      throw error;
    }));
}
export function callbackURL() {
  return `${origin()}/auth/callback`;
}
