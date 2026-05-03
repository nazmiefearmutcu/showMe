import { expect, test } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

type FunctionCase = {
  code: string;
  name: string;
  category: string;
  symbol?: string;
  url: string;
};

const currentDir = dirname(fileURLToPath(import.meta.url));
const root = resolve(currentDir, "../..");
const cases = JSON.parse(
  readFileSync(resolve(root, "tests/fixtures/function-cases.json"), "utf8"),
) as FunctionCase[];
const deny = ["function did not return", "No ratios", "No rows", "undefined", "NaN", "NONE source"];
const appUrl = (process.env.SHOWME_APP_URL || "http://127.0.0.1:5173").replace(/\/$/, "");
const sidecarPort = process.env.SHOWME_PORT || process.env.SIDECAR_PORT;
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = process.env.SHOWME_E2E_OUT
  ? resolve(process.env.SHOWME_E2E_OUT)
  : resolve(root, "artifacts/showme-function-audit", stamp);
const screenshotDir = resolve(outDir, "screenshots");
const logsDir = resolve(outDir, "logs");

test.skip(!sidecarPort, "SHOWME_PORT/SIDECAR_PORT must point at the running sidecar");

mkdirSync(screenshotDir, { recursive: true });
mkdirSync(logsDir, { recursive: true });

test.describe("ShowMe all functions", () => {
  for (const c of cases) {
    test(`${c.code} ${c.name}`, async ({ page }) => {
      const consoleErrors: string[] = [];
      const networkErrors: string[] = [];

      page.on("console", (msg) => {
        if (msg.type() === "error") consoleErrors.push(msg.text());
      });
      page.on("response", (response) => {
        const url = response.url();
        if (url.includes("/api/fn/") && response.status() >= 400) {
          networkErrors.push(`${response.status()} ${url}`);
        }
      });
      await page.addInitScript((port) => {
        window.localStorage.setItem("showme.sidecarPort", String(port));
      }, sidecarPort);

      await page.goto(`${appUrl}/${c.url}`);
      const run = page.getByRole("button", { name: /^run$/i }).first();
      if (await run.isVisible().catch(() => false)) await run.click();

      const status = page.locator("[data-testid=function-status]").first();
      await expect(status).toBeVisible({ timeout: 25_000 });
      await expect(status).not.toHaveText(/loading/i);

      const body = await page.locator("body").innerText();
      for (const bad of deny) {
        expect(body, `${c.code} sentinel ${bad}`).not.toContain(bad);
      }
      expect(consoleErrors, `${c.code} console errors`).toEqual([]);
      expect(networkErrors, `${c.code} network errors`).toEqual([]);

      const statusText = (await status.innerText()).trim().toLowerCase();
      if (statusText === "ok" || statusText === "live") {
        await expect(page.locator("[data-testid=function-source]").first()).not.toHaveText(/NONE/i);
        await expect(page.locator("[data-testid=function-payload]").first()).toBeVisible();
      } else {
        await expect(page.locator("[data-testid=function-reason]").first()).toBeVisible();
        await expect(page.locator("[data-testid=function-next-action]").first()).toBeVisible();
      }

      await page.screenshot({
        path: resolve(screenshotDir, `${c.code}.png`),
        fullPage: true,
      });
      writeFileSync(resolve(logsDir, `${c.code}.console.log`), consoleErrors.join("\n"));
      writeFileSync(resolve(logsDir, `${c.code}.network.log`), networkErrors.join("\n"));
    });
  }
});
