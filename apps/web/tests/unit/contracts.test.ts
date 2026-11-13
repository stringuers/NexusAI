import { describe, expect, it } from "vitest";
import {
  briefSchema,
  controlPathAllowed,
  sameOrigin,
} from "../../lib/contracts";
describe("submission and proxy boundaries", () => {
  it("normalizes a valid task and rejects invalid budgets", () => {
    expect(
      briefSchema.parse({
        instruction: "  Build a restaurant website  ",
        budget: "5.00",
      }).instruction,
    ).toBe("Build a restaurant website");
    for (const budget of ["0", "0.49", "100.01", "Infinity", "-1", "1e2"])
      expect(
        briefSchema.safeParse({ instruction: "Build a website", budget })
          .success,
      ).toBe(false);
  });
  it("rejects empty briefs and proxy path escapes", () => {
    expect(
      briefSchema.safeParse({ instruction: "   ", budget: "5" }).success,
    ).toBe(false);
    expect(controlPathAllowed(["runs", "valid-id", "events"])).toBe(true);
    for (const path of [
      [],
      ["webhooks", "n8n"],
      ["runs", ".."],
      ["runs", "%2e%2e"],
      ["https:", "evil"],
      ["runs", "a/b"],
    ])
      expect(controlPathAllowed(path)).toBe(false);
  });
});

it("binds CSRF checks to the browser host rather than the internal Next.js URL", () => {
  expect(sameOrigin("http://127.0.0.1:3101", "127.0.0.1:3101")).toBe(true);
  expect(sameOrigin("https://untrusted.example", "127.0.0.1:3101")).toBe(false);
  expect(sameOrigin("null", "127.0.0.1:3101")).toBe(false);
  expect(sameOrigin(null, "127.0.0.1:3101")).toBe(false);
  expect(
    sameOrigin(
      "https://console.example",
      "internal:3000",
      "https://console.example",
    ),
  ).toBe(true);
});
