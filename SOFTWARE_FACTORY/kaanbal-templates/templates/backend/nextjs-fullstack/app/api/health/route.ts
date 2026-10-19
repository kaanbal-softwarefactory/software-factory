import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Salud del proceso, no de la base. Kaanbal reinicia el pod si esto falla; una
 * base caída no debe tumbar la app, solo mostrarse como tal en la página.
 */
export async function GET() {
  return NextResponse.json({
    status: "ok",
    app: process.env.APP_NAME ?? "placeholder-app",
    environment: process.env.APP_ENV ?? "production",
    time: new Date().toISOString(),
  });
}
