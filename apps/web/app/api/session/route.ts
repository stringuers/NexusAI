import { sameOrigin } from "@/lib/contracts";
import { cookies } from "next/headers";
import { NextRequest } from "next/server";

export async function POST(request: NextRequest) {
  if (
    !sameOrigin(
      request.headers.get("origin"),
      request.headers.get("host"),
      process.env.NEXUS_WEB_ORIGIN,
    )
  )
    return Response.json({ detail: "Invalid origin" }, { status: 403 });
  const body: unknown = await request.json().catch(() => null);
  const token =
    body && typeof body === "object" && "token" in body ? body.token : null;
  if (typeof token !== "string" || token.length < 32 || token.length > 512) {
    return Response.json(
      { detail: "Enter a valid workspace token" },
      { status: 400 },
    );
  }
  try {
    const response = await fetch(
      `${process.env.NEXUS_API_URL ?? "http://127.0.0.1:8000"}/api/v1/projects?limit=1`,
      {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal: AbortSignal.timeout(10000),
      },
    );
    if (!response.ok)
      return Response.json(
        {
          detail:
            response.status === 401
              ? "Invalid workspace token"
              : "Control plane unavailable",
        },
        { status: response.status === 401 ? 401 : 502 },
      );
    (await cookies()).set("nexus_session", token, {
      httpOnly: true,
      sameSite: "strict",
      secure: request.nextUrl.protocol === "https:",
      path: "/",
      maxAge: 28800,
    });
    return Response.json({ authenticated: true });
  } catch {
    return Response.json(
      { detail: "Cannot reach the control plane" },
      { status: 502 },
    );
  }
}
export async function DELETE(request: NextRequest) {
  if (
    !sameOrigin(
      request.headers.get("origin"),
      request.headers.get("host"),
      process.env.NEXUS_WEB_ORIGIN,
    )
  )
    return Response.json({ detail: "Invalid origin" }, { status: 403 });
  (await cookies()).delete("nexus_session");
  return Response.json({ authenticated: false });
}
