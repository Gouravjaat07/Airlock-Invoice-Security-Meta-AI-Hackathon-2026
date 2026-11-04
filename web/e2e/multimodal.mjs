/**
 * Real-browser multimodal E2E: login, 3-file intake (invoice + delivery
 * photo + voice note), process, per-artifact evidence statuses, audit
 * lane records, providers. Works in fixture mode (registered synthetic
 * fixture) and live mode (synthetic assets + live providers): the
 * verdict is REPORTED, not asserted, because live evidence may
 * legitimately conflict (ESCALATE) or fail closed.
 *
 * Prereqs: same backend as smoke.mjs (isolated temp DB), plus the three
 * asset paths below. Fixture mode additionally needs the custom
 * fixture registered (see custom-fixture.mjs header) with transcript
 * and sam count; live mode needs the multimodal dev launcher
 * (scripts/run_airlock_multimodal_dev.ps1).
 *   Terminal B (web/): npm run dev -- --host 127.0.0.1
 * Then: $env:AIRLOCK_E2E_PIN='<pin>'
 *   $env:AIRLOCK_E2E_INVOICE='<invoice>'; $env:AIRLOCK_E2E_DELIVERY='<image>'
 *   $env:AIRLOCK_E2E_VOICE='<wav>'; npm run e2e:multimodal
 * Synthetic assets only. Exits nonzero on the first failed step.
 */
import { chromium } from "playwright";

const BASE = process.env.AIRLOCK_E2E_BASE ?? "http://127.0.0.1:5173";
const PIN = process.env.AIRLOCK_E2E_PIN;
const INVOICE = process.env.AIRLOCK_E2E_INVOICE;
const DELIVERY = process.env.AIRLOCK_E2E_DELIVERY;
const VOICE = process.env.AIRLOCK_E2E_VOICE;
for (const [name, value] of [["AIRLOCK_E2E_PIN", PIN], ["AIRLOCK_E2E_INVOICE", INVOICE],
  ["AIRLOCK_E2E_DELIVERY", DELIVERY], ["AIRLOCK_E2E_VOICE", VOICE]]) {
  if (!value) {
    console.error(`E2E-FAIL: ${name} is required`);
    process.exit(1);
  }
}

const browser = await chromium.launch();
const page = await browser.newPage();
let steps = 0;
async function step(name, fn) {
  await fn();
  steps += 1;
  console.log(`E2E-PASS:${name}`);
}

try {
  await step("login", async () => {
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
    await page.getByLabel("Owner PIN").fill(PIN);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByRole("heading", { name: "Overview" }).waitFor({ timeout: 15000 });
  });
  let caseId = "";
  await step("intake-3-files", async () => {
    await page.goto(`${BASE}/cases/new`);
    await page.setInputFiles("#slot-invoice", INVOICE);
    await page.setInputFiles("#slot-delivery", DELIVERY);
    await page.setInputFiles("#slot-voice", VOICE);
    await page.getByRole("button", { name: /Submit 3 files/ }).click();
    await page.waitForURL(/\/(?!new(?:[?#]|$)).+/, { timeout: 60000 });
  });
  await step("process", async () => {
    await page.getByRole("button", { name: "Process case" }).click();
    await page.getByText("Processing finished", { exact: false }).waitFor({ timeout: 300000 });
    caseId = page.url().split("/cases/")[1].split(/[?#]/)[0];
    if (!caseId || caseId === "new") throw new Error("no case id in URL");
  });
  await step("evidence-statuses", async () => {
    await page.getByRole("tab", { name: /Evidence/ }).click();
    await page.getByRole("heading", { name: /^Delivery evidence$/i }).waitFor({ timeout: 30000 });
await page.getByRole("heading", { name: /^Voice evidence$/i }).waitFor({ timeout: 30000 });
    // Every lane reports a distinct processing status (never silent).
    const data = await page.evaluate(async (id) => {
      const res = await fetch(`/api/v1/audit/${encodeURIComponent(id)}`);
      if (!res.ok) throw new Error(`audit fetch ${res.status}`);
      const body = await res.json();
      const byType = {};
      for (const e of body.events ?? []) {
        (byType[e.event_type] ??= []).push(e.payload ?? {});
      }
      return {
        state: (await (await fetch(`/api/v1/cases/${encodeURIComponent(id)}`)).json()).case?.state,
        voice: (byType["voice.transcript"] ?? []).map((p) => p.status ?? "legacy"),
        sam: (byType["sam.evidence"] ?? []).map((p) => p.status ?? "legacy"),
        reader: Object.keys(byType).filter((t) => t.startsWith("reader.") || t.startsWith("extraction.")),
      };
    }, caseId);
    console.log(`E2E-EVIDENCE:${JSON.stringify(data)}`);
    if (data.state === "ERROR") throw new Error("case ended in ERROR");
    if (data.voice.length === 0) throw new Error("no voice.transcript record");
    if (data.sam.length === 0) throw new Error("no sam.evidence record");
  });
  await step("policy-tab", async () => {
    await page.getByRole("tab", { name: "Policy" }).click();
    await page.getByText(/Allow proposal|Escalate|Deny/).first().waitFor({ timeout: 30000 });
  });
  await step("providers", async () => {
    await page.goto(`${BASE}/providers`);
    await page.getByText("Invoice extraction").waitFor();
    await page.getByText("Voice transcription").waitFor();
    await page.getByText("Visual segmentation").waitFor();
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
