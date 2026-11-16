import { describe, expect, it } from "vitest";

/**
 * Contract tests for the API client's error handling and URL construction.
 * These run without a network: fetch is stubbed.
 */

import { api } from "../api/client";

function stubFetch(makeResponse: () => Response) {
  const calls: { url: string; init: RequestInit }[] = [];
  const mock = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push({ url: String(input), init });
    // A Response body can only be read once, so build a fresh one per call.
    return makeResponse();
  };
  return { mock, calls };
}

describe("api client", () => {
  it("sends credentials and surfaces structured API errors", async () => {
    const { mock, calls } = stubFetch(
      () =>
        new Response(
          JSON.stringify({
            error: { code: "UNAUTHENTICATED", message: "Incorrect email or password", details: {} },
          }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
    );
    const original = globalThis.fetch;
    globalThis.fetch = mock as unknown as typeof fetch;
    try {
      await expect(api.me()).rejects.toMatchObject({
        code: "UNAUTHENTICATED",
        status: 401,
        message: "Incorrect email or password",
      });
      expect(calls[0].init.credentials).toBe("include");
    } finally {
      globalThis.fetch = original;
    }
  });

  it("builds catalogue queries with only provided filters", async () => {
    const { mock, calls } = stubFetch(
      () =>
        new Response(JSON.stringify({ datasets: [], total: 0, limit: 24, offset: 0 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const original = globalThis.fetch;
    globalThis.fetch = mock as unknown as typeof fetch;
    try {
      await api.datasets({ q: "iris", category: undefined, limit: 10 });
      expect(calls[0].url).toContain("q=iris");
      expect(calls[0].url).toContain("limit=10");
      expect(calls[0].url).not.toContain("category=");
    } finally {
      globalThis.fetch = original;
    }
  });

  it("treats 204 responses as empty", async () => {
    const { mock } = stubFetch(() => new Response(null, { status: 204 }));
    const original = globalThis.fetch;
    globalThis.fetch = mock as unknown as typeof fetch;
    try {
      await expect(api.deleteNotebook("abc")).resolves.toBeUndefined();
    } finally {
      globalThis.fetch = original;
    }
  });
});
