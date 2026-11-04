import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../App";
import { dashboardSummary } from "../test/fixtures";
import { envelope, jsonResponse, renderAppAt, stubFetch } from "../test/helpers";

function bootAnon(extra?: Record<string, (url: string, init?: RequestInit) => Response>) {
  stubFetch((url, init) => {
    if (url.endsWith("/api/v1/auth/me")) {
      return jsonResponse({ authenticated: false, session_id: null, expires_at: null }, 401);
    }
    const handler = extra?.[url];
    if (handler) return handler(url, init);
    return jsonResponse(envelope("E_INTERNAL", "unexpected call"), 500);
  });
}

describe("LoginPage", () => {
  it("toggles PIN visibility without submitting", async () => {
    bootAnon();
    const user = userEvent.setup();
    renderAppAt(App, "/login");
    const pin = (await screen.findByLabelText("Owner PIN")) as HTMLInputElement;
    expect(pin.type).toBe("password");
    await user.click(screen.getByRole("button", { name: "Show PIN" }));
    expect(pin.type).toBe("text");
  });

  it("shows an invalid-PIN error and clears the field", async () => {
    bootAnon({
      "/api/v1/auth/login": () => jsonResponse(envelope("E_AUTH", "Invalid credentials"), 401),
    });
    const user = userEvent.setup();
    renderAppAt(App, "/login");
    const pin = (await screen.findByLabelText("Owner PIN")) as HTMLInputElement;
    await user.type(pin, "0000");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/Invalid PIN/)).toBeInTheDocument();
    await waitFor(() => expect(pin.value).toBe(""));
  });

  it("authenticates and lands on the overview", async () => {
    const calls: string[] = [];
    stubFetch((url, init) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/api/v1/auth/me")) {
        return jsonResponse({ authenticated: false, session_id: null, expires_at: null }, 401);
      }
      if (url.endsWith("/api/v1/auth/login")) {
        const body = JSON.parse(String(init?.body)) as { pin: string };
        expect(body.pin).toBe("1234");
        return jsonResponse({ session_id: "sess_1", csrf_token: "csrf_1", expires_at: null });
      }
      if (url.endsWith("/api/v1/dashboard/summary")) {
        return jsonResponse(dashboardSummary());
      }
      return jsonResponse(envelope("E_INTERNAL", "unexpected call"), 500);
    });
    const user = userEvent.setup();
    renderAppAt(App, "/login");
    await user.type(await screen.findByLabelText("Owner PIN"), "1234");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(calls).toContain("POST /api/v1/auth/login");
  });

  it("explains an expired session", async () => {
    bootAnon();
    renderAppAt(App, "/login?expired=1");
    expect(await screen.findByText(/session expired/i)).toBeInTheDocument();
  });
});
