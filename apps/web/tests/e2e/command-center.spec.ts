import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
const config = readFileSync(
  resolve(process.cwd(), "../../.env.nexus.local"),
  "utf8",
);
const token =
  process.env.NEXUS_E2E_TOKEN ??
  config.match(/^NEXUS_API_TOKEN=(.+)$/m)?.[1] ??
  "";
test("authenticate, create project, submit and cancel a real durable task", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Workspace access token").fill(token);
  const sessionResponse = page.waitForResponse(
    (r) => r.url().endsWith("/api/session") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Connect workspace" }).click();
  const session = await sessionResponse;
  expect(await session.json()).toEqual({ authenticated: true });
  await expect(
    page.getByRole("heading", { name: "Mission control." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New project" }).click();
  const name = `Browser mission ${Date.now()}`;
  await page.locator("#project-name").fill(name);
  await page
    .getByRole("button", { name: "Create project", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: new RegExp(name) }),
  ).toBeVisible();
  await page
    .getByLabel("Requirements and source notes")
    .fill("French language. Preserve accessible keyboard navigation.");
  await page.getByRole("button", { name: "Save requirements version" }).click();
  await expect(page.getByText("New requirements version saved")).toBeVisible();
  await page.getByRole("button", { name: "Save project details" }).click();
  await expect(page.getByText("Project details saved")).toBeVisible();
  await page
    .getByLabel("Project brief")
    .fill("Build a responsive restaurant website with accessible navigation.");
  await page.getByRole("button", { name: "Start workflow" }).click();
  await expect(
    page.getByText("Task queued. The worker will begin when available."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel run" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel run" }).click();
  await expect(page.getByText("Run cancelled", { exact: true })).toBeVisible();
  await expect(page.locator(".run-strip")).toContainText("cancelled");
  await page.getByRole("button", { name: "Agent control" }).click();
  await expect(
    page.getByRole("heading", { name: "Claude Developer" }),
  ).toBeVisible();
  await expect(
    page.getByText("not configured", { exact: true }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Mission control" }).click();
  await page.screenshot({
    path: "../../.data/screenshots/mission-control-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../../.data/screenshots/mission-control-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Workspace access token")).toBeVisible();
});

test("rejects cross-origin session changes", async ({ request }) => {
  const response = await request.post("/api/session", {
    headers: { Origin: "https://untrusted.example" },
    data: { token },
  });
  expect(response.status()).toBe(403);
});
