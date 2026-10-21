export function GET() {
  return Response.json({
    status: "alive",
    version: "0.1.0",
    stage: "prototype",
  });
}
