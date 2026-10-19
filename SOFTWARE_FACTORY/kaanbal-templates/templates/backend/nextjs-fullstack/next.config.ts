import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Kaanbal construye una imagen: 'standalone' deja un servidor Node mínimo
  // en .next/standalone, sin node_modules de desarrollo.
  output: "standalone",
  outputFileTracingIncludes: {
    "/": ["./node_modules/mongodb/**", "./node_modules/pg/**"],
  },
};

export default nextConfig;
