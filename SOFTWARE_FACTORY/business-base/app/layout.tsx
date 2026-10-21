import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Kaanbal · Business Base",
  description: "Tu negocio, conectado.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
