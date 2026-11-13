import { z } from "zod";
export const briefSchema = z.object({
  instruction: z
    .string()
    .trim()
    .min(10, "Describe the task in at least 10 characters")
    .max(20000),
  budget: z
    .string()
    .regex(/^\d+(\.\d{1,2})?$/, "Use a dollar amount")
    .refine(
      (v) => Number(v) >= 0.5 && Number(v) <= 100,
      "Budget must be between $0.50 and $100",
    ),
});
export function controlPathAllowed(path: string[]): boolean {
  return (
    path.length > 0 &&
    [
      "projects",
      "tasks",
      "runs",
      "agents",
      "approvals",
      "usage",
      "artifacts",
    ].includes(path[0]) &&
    path.every((p) => /^[a-zA-Z0-9_-]+$/.test(p))
  );
}

export function sameOrigin(
  origin: string | null,
  host: string | null,
  expected?: string,
): boolean {
  if (!origin || !host) return false;
  try {
    const parsed = new URL(origin);
    if (
      !["http:", "https:"].includes(parsed.protocol) ||
      parsed.origin !== origin
    )
      return false;
    return expected
      ? parsed.origin === expected
      : parsed.host === host.toLowerCase();
  } catch {
    return false;
  }
}
