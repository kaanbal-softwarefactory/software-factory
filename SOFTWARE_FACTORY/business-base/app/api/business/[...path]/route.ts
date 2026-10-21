import { NextRequest, NextResponse } from "next/server";
import { ZodError } from "zod";
import {
  acceptInvitation,
  contact,
  listResource,
  mutate,
  publicSite,
} from "../../../../lib/business";
import { actor, sameOrigin } from "../../../../lib/session";
import { Problem } from "../../../../lib/policy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
async function handle(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  try {
    const { path } = await context.params;
    if (request.method === "GET") {
      if (path.length === 1 && path[0] === "public")
        return NextResponse.json(await publicSite());
      const user = await actor(request);
      if (path.length === 1 && path[0] === "me") return NextResponse.json(user);
      if (path.length !== 2) throw new Problem(404, "No encontrado");
      return NextResponse.json(await listResource(user, path[0], path[1]));
    }
    sameOrigin(request);
    // Check actual bytes as well as Content-Length; chunked bodies cannot bypass the limit.
    const reader = request.body?.getReader(),
      chunks: Uint8Array[] = [];
    let size = 0;
    if (!reader) throw new Problem(400, "Falta el cuerpo");
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 16000) {
        await reader.cancel();
        throw new Problem(413, "Solicitud demasiado grande");
      }
      chunks.push(value);
    }
    let body: unknown;
    try {
      body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    } catch {
      throw new Problem(400, "JSON inválido");
    }
    if (path.length === 1 && path[0] === "contact") {
      let user = null;
      try {
        user = await actor(request);
      } catch (error) {
        if (!(error instanceof Problem && error.status === 401)) throw error;
      }
      return NextResponse.json(await contact(body, user), { status: 202 });
    }
    const user = await actor(request);
    if (path.length === 1 && path[0] === "accept-invitation")
      return NextResponse.json(await acceptInvitation(user, body));
    if (path.length !== 2) throw new Problem(404, "No encontrado");
    return NextResponse.json(await mutate(user, path[0], path[1], body));
  } catch (error) {
    const status =
      error instanceof Problem
        ? error.status
        : error instanceof ZodError
          ? 422
          : 503;
    return NextResponse.json(
      {
        error:
          error instanceof Problem
            ? error.message
            : status === 422
              ? "Revisa los campos del formulario"
              : "Servicio temporalmente no disponible",
      },
      { status },
    );
  }
}
export const GET = handle;
export const POST = handle;
