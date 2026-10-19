import { NextResponse } from "next/server";

import { createNote, listNotes } from "@/lib/notes";

export const dynamic = "force-dynamic";

export async function GET() {
  const page = await listNotes();
  return NextResponse.json(page);
}

export async function POST(request: Request) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "El cuerpo debe ser JSON" }, { status: 400 });
  }

  const { title, body } = (payload ?? {}) as { title?: unknown; body?: unknown };
  const cleanTitle = typeof title === "string" ? title.trim() : "";
  const cleanBody = typeof body === "string" ? body.trim() : "";

  if (!cleanTitle) {
    return NextResponse.json({ error: "El título es obligatorio" }, { status: 400 });
  }
  if (cleanTitle.length > 120 || cleanBody.length > 2000) {
    return NextResponse.json({ error: "El título o el texto son demasiado largos" }, { status: 400 });
  }

  const note = await createNote(cleanTitle, cleanBody);
  return NextResponse.json(note, { status: 201 });
}
