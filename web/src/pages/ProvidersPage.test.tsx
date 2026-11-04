import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ProviderAvailability } from "../api/types";
import { ProvidersPage } from "./ProvidersPage";
import { providersResponse, providerStatusItem } from "../test/fixtures";
import { envelope, jsonResponse, renderWithProviders, stubFetch } from "../test/helpers";

function stubProviders(body: unknown, status = 200): void {
  stubFetch((url) => {
    if (url.includes("/api/v1/auth/me")) {
      return jsonResponse({ authenticated: false, session_id: null, expires_at: null });
    }
    if (url.includes("/api/v1/providers")) {
      return jsonResponse(body, status);
    }
    return jsonResponse(envelope("E_NOT_FOUND", "not found"), 404);
  });
}

describe("ProvidersPage", () => {
  it("renders one card per provider task with badges and reasons", async () => {
    stubProviders(providersResponse());
    renderWithProviders(<ProvidersPage />);

    expect(await screen.findByText("Invoice extraction")).toBeInTheDocument();
    expect(screen.getByText("Voice transcription")).toBeInTheDocument();
    expect(screen.getByText("Visual segmentation")).toBeInTheDocument();
    expect(screen.getByText("muse-spark-1.3")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Missing Credential")).toBeInTheDocument();
    expect(screen.getByText("Breaker Open")).toBeInTheDocument();
    expect(screen.getByText("Meta Model API configured")).toBeInTheDocument();
    expect(
      screen.getByText(/never a live paid probe/i),
    ).toBeInTheDocument();
  });

  it("renders an empty state when no providers are reported", async () => {
    stubProviders(providersResponse({ providers: [] }));
    renderWithProviders(<ProvidersPage />);

    expect(await screen.findByText("No providers configured")).toBeInTheDocument();
  });

  it("renders a retryable error state on failure", async () => {
    const fetchMock = stubFetch((url) => {
      if (url.includes("/api/v1/auth/me")) {
        return jsonResponse({ authenticated: false, session_id: null, expires_at: null });
      }
      return jsonResponse(envelope("E_API", "boom"), 500);
    });
    renderWithProviders(<ProvidersPage />);

    expect(await screen.findByText("Provider status unavailable")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    const callsBefore = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByText("Try again"));
    await screen.findByText("Provider status unavailable");
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
  });

  it("falls back to the raw availability value for unknown states", async () => {
    stubProviders(
      providersResponse({
        providers: [
          providerStatusItem({ availability: "something_new" as ProviderAvailability }),
        ],
      }),
    );
    renderWithProviders(<ProvidersPage />);

    expect(await screen.findByText("something_new")).toBeInTheDocument();
  });

  it("refetches live backend state when Refresh is clicked", async () => {
    const fetchMock = stubFetch((url) => {
      if (url.includes("/api/v1/auth/me")) {
        return jsonResponse({ authenticated: false, session_id: null, expires_at: null });
      }
      if (url.includes("/api/v1/providers")) {
        return jsonResponse(providersResponse());
      }
      return jsonResponse(envelope("E_NOT_FOUND", "not found"), 404);
    });
    renderWithProviders(<ProvidersPage />);

    expect(await screen.findByText("Invoice extraction")).toBeInTheDocument();
    const callsBefore = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByText("Refresh"));
    await screen.findByText("Invoice extraction");
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
  });

  it("shows a default note when the backend gives no reason", async () => {
    stubProviders(
      providersResponse({
        providers: [providerStatusItem({ reason: "" })],
      }),
    );
    renderWithProviders(<ProvidersPage />);

    expect(await screen.findByText("No further detail.")).toBeInTheDocument();
  });
});
