/**
 * Real-browser smoke: login, white theme, intake, process, policy, evidence,
 * approval, audit, providers, logout — against a live backend + Vite proxy.
 *
 * Prereqs (two terminals, isolated temp DB):
 *   Terminal A (repo root):
 *     $env:AIRLOCK_DB_PATH='<tmp>/e2e.db'; $env:AIRLOCK_BLOB_DIR='<tmp>/blobs'
 *     $env:AIRLOCK_ENV='development'; $env:AIRLOCK_ALLOW_INSECURE_COOKIES='1'
 *     $env:AIRLOCK_FIXTURE_READER='1'; <seed vendors>; <set AIRLOCK_PIN_HASH>
 *     .\.venv\Scripts\python.exe -m app.cli db upgrade   # required first;
 *     .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
 *   Terminal B (web/): npm run dev -- --host 127.0.0.1
 * Then: $env:AIRLOCK_E2E_PIN='<same pin>'; npm run e2e
 * Synthetic fixtures only. Exits nonzero on the first failed step.
 */
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const BASE = process.env.AIRLOCK_E2E_BASE ?? "http://127.0.0.1:5173";
const PIN = process.env.AIRLOCK_E2E_PIN;
if (!PIN) {
  console.error("E2E-FAIL: AIRLOCK_E2E_PIN is required");
  process.exit(1);
}
const INVOICE = fileURLToPath(new URL("../../fixtures/invoices/clean.pdf", import.meta.url));

const browser = await chromium.launch();
const page = await browser.newPage();
let steps = 0;
async function step(name, fn) {
  await fn();
  steps += 1;
  console.log(`E2E-PASS:${name}`);
}

try {
  await step("login-page", async () => {
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
    await page.getByLabel("Owner PIN").waitFor();
  });
  await step("white-theme", async () => {
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    if (bg !== "rgb(255, 255, 255)") throw new Error(`body background is ${bg}`);
  });
  await step("wrong-pin", async () => {
    await page.getByLabel("Owner PIN").fill("0000");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByText(/Invalid PIN/).waitFor();
  });
  await step("login-ok", async () => {
    await page.getByLabel("Owner PIN").fill(PIN);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByRole("heading", { name: "Overview" }).waitFor({ timeout: 15000 });
  });
  await step("intake", async () => {
    await page.goto(`${BASE}/cases/new`);
    await page.setInputFiles("#slot-invoice", INVOICE);
    await page.getByRole("button", { name: /Submit 1 file/ }).click();
    await page.waitForURL(/\/cases\/.+/, { timeout: 60000 });
  });
  await step("process", async () => {
    await page.getByRole("button", { name: "Process case" }).click();
    await page.getByText("Processing finished", { exact: false }).waitFor({ timeout: 180000 });
  });
  await step("policy", async () => {
    await page.getByRole("tab", { name: "Policy" }).click();
    await page.getByText("Allow proposal").first().waitFor();
  });
  await step("evidence", async () => {
    await page.getByRole("tab", { name: /Evidence/ }).click();
    await page.locator("iframe[title^='Artifact']").first().waitFor({ timeout: 30000 });
  });
  await step("proposal", async () => {
    await page.getByRole("link", { name: "View proposal" }).click();
    await page.waitForURL(/\/proposals\/.+/);
    await page.getByRole("button", { name: "Start approval" }).waitFor();
  });
  await step("approve", async () => {
    await page.getByRole("button", { name: "Start approval" }).click();
    await page.getByRole("button", { name: "Authorize mock payment" }).waitFor();
    const html = await page.content();
    if (html.includes("ch_")) throw new Error("challenge bearer leaked into the DOM");
    await page.getByRole("checkbox").check();
    await page.getByLabel("Owner PIN").fill(PIN);
    await page.getByRole("button", { name: "Authorize mock payment" }).click();
    await page.getByText("Mock execution confirmed").waitFor({ timeout: 30000 });
  });
  await step("audit", async () => {
    await page.goto(`${BASE}/audit`);
    await page.getByRole("button", { name: "Verify chain" }).click();
    await page.getByText(/Chain verified/).waitFor({ timeout: 30000 });
  });
  await step("providers", async () => {
    await page.goto(`${BASE}/providers`);
    await page.getByText("Invoice extraction").waitFor();
  });
  await step("logout", async () => {
    await page.getByRole("button", { name: "Log out" }).click();
    await page.getByLabel("Owner PIN").waitFor();
  });
  console.log(`E2E-OK steps=${steps}`);
} catch (error) {
  console.error(`E2E-FAIL: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
