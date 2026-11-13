import { controlPathAllowed, sameOrigin } from "@/lib/contracts";
import { cookies } from "next/headers";
import { NextRequest } from "next/server";
export const dynamic = "force-dynamic";
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  if (
    request.method !== "GET" &&
    !sameOrigin(
      request.headers.get("origin"),
      request.headers.get("host"),
      process.env.NEXUS_WEB_ORIGIN,
    )
  ) {
    return Response.json({ detail: "Invalid origin" }, { status: 403 });
  }
  const token = (await cookies()).get("nexus_session")?.value;
  if (!token)
    return Response.json(
      { detail: "Sign in to your workspace" },
      { status: 401 },
    );
  const { path } = await context.params;
  if (!controlPathAllowed(path)) {
    return Response.json({ detail: "Unknown resource" }, { status: 404 });
  }
  const headers = new Headers({ Authorization: `Bearer ${token}` });
  for (const name of ["content-type", "idempotency-key", "last-event-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const upstream = await fetch(
      `${process.env.NEXUS_API_URL ?? "http://127.0.0.1:8000"}/api/v1/${path.join("/")}${request.nextUrl.search}`,
      {
        method: request.method,
        headers,
        body: request.method === "GET" ? undefined : await request.text(),
        cache: "no-store",
        signal: request.signal,
      },
    );
    const responseHeaders = new Headers({ "Cache-Control": "no-store" });
    for (const name of [
      "content-type",
      "content-disposition",
      "x-content-type-options",
    ]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    return Response.json(
      { detail: "Control plane connection failed" },
      { status: 502 },
    );
  }
}
export { proxy as GET, proxy as POST, proxy as PATCH };
