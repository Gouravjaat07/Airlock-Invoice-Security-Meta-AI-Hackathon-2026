/**
 * Real-browser custom-fixture E2E: login, intake of an owner-registered
 * custom fixture, process, extraction + provenance, R1-R10 policy, audit,
 * proposal. Proves the offline fixture workflow through the real UI for
 * newly registered (non-canonical) synthetic bytes.
 *
 * Prereqs: same backend as smoke.mjs (isolated temp DB), PLUS:
 *   $env:AIRLOCK_CUSTOM_FIXTURES_DIR='<temp>/fixtures-custom' on the backend,
 *   then: python -m app.cli fixtures register --name <n> --invoice <pdf>
 *     --extraction <json> --expected-verdict ALLOW_PROPOSAL --dir <temp>/fixtures-custom
 *   Terminal B (web/): npm run dev -- --host 127.0.0.1
 * Then: $env:AIRLOCK_E2E_PIN='<pin>'; $env:AIRLOCK_E2E_INVOICE='<same pdf>'; npm run e2e:custom
 * Synthetic fixtures only. Exits nonzero on the first failed step.
 */
import { chromium } from "playwright";

const BASE = process.env.AIRLOCK_E2E_BASE ?? "http://127.0.0.1:5173";
const PIN = process.env.AIRLOCK_E2E_PIN;
const INVOICE = process.env.AIRLOCK_E2E_INVOICE;
if (!PIN) {
  console.error("E2E-FAIL: AIRLOCK_E2E_PIN is required");
  process.exit(1);
}
if (!INVOICE) {
  console.error("E2E-FAIL: AIRLOCK_E2E_INVOICE is required");
  process.exit(1);
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
  await step("intake-custom", async () => {
    await page.goto(`${BASE}/cases/new`);
    await page.setInputFiles("#slot-invoice", INVOICE);
    await page.getByRole("button", { name: /Submit 1 file/ }).click();
    await page.waitForURL(/\/cases\/(?!new(?:[?#]|$)).+/, { timeout: 60000 });
  });
  await step("process", async () => {
    await page.getByRole("button", { name: "Process case" }).click();
    await page.getByText("Processing finished", { exact: false }).waitFor({ timeout: 180000 });
    caseId = page.url().split("/cases/")[1].split(/[?#]/)[0];
    if (!caseId || caseId === "new") throw new Error("no case id in URL");
  });
  await step("evidence", async () => {
    const data = await page.evaluate(async (id) => {
      const res = await fetch(`/api/v1/cases/${encodeURIComponent(id)}`);
      if (!res.ok) throw new Error(`case fetch ${res.status}`);
      const body = await res.json();
      const facts = {};
      for (const f of body.facts ?? []) facts[f.field] = f.value;
      const producers = [...new Set((body.facts ?? []).map((f) => f.producer?.adapter))];
      const taints = [...new Set((body.facts ?? []).map((f) => f.taint_class))];
      const verify = await (await fetch(`/api/v1/audit/${encodeURIComponent(id)}`)).json();
      return {
        state: body.case?.state,
        verdict: body.verdict?.verdict,
        rules: (body.verdict?.rule_details_json ? JSON.parse(body.verdict.rule_details_json) : [])
          .map((r) => `${r.rule_id}:${r.passed ? "pass" : "FAIL:" + r.reason_code}`),
        facts,
        producers,
        taints,
        proposal: body.proposal ? body.proposal.status : null,
        payments: (body.payments ?? []).length,
        auditEvents: (verify.events ?? verify.audit ?? []).length
          ?? (Array.isArray(verify) ? verify.length : "?"),
      };
    }, caseId);
    console.log(`E2E-EVIDENCE:${JSON.stringify(data)}`);
    if (data.state !== "PROPOSED") throw new Error(`state is ${data.state}`);
    if (data.verdict !== "ALLOW_PROPOSAL") throw new Error(`verdict is ${data.verdict}`);
    if (!data.rules.every((r) => r.endsWith(":pass"))) throw new Error(`rules: ${data.rules}`);
    if (data.producers.join(",") !== "fixture-reader") throw new Error(`producers: ${data.producers}`);
    if (data.taints.join(",") !== "T2") throw new Error(`taints: ${data.taints}`);
    if (data.proposal !== "PENDING") throw new Error(`proposal: ${data.proposal}`);
    if (data.payments !== 0) throw new Error(`payments: ${data.payments}`);
  });
  await step("policy-tab", async () => {
    await page.getByRole("tab", { name: "Policy" }).click();
    await page.getByText("Allow proposal").first().waitFor();
  });
  await step("audit-tab", async () => {
    await page.getByRole("tab", { name: /Audit/ }).click();
    await page.getByText("reader.completed", { exact: false }).first().waitFor({ timeout: 30000 });
  });
  await step("proposal-link", async () => {
    await page.getByRole("tab", { name: "Overview" }).click();
    await page.getByRole("link", { name: "View proposal" }).waitFor();
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
