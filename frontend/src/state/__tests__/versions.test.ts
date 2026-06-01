import { act, renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { useVersions } from "@/state/versions";

const server = setupServer(
  http.get("*/sessions/:sid/deck/versions", () => {
    return HttpResponse.json([
      {
        version_id: "version_20260601_130000_000000",
        timestamp: "20260601_130000",
        description: "F4.5 sl_emit snapshot",
        page_count: 9,
        is_active: true,
      },
      {
        version_id: "version_20260601_120000_000000",
        timestamp: "20260601_120000",
        description: "earlier draft",
        page_count: 8,
        is_active: false,
      },
    ]);
  }),
  http.post(
    "*/sessions/:sid/deck/versions/:vid/restore",
    ({ params }) => {
      return HttpResponse.json({
        ok: true,
        current_version_id: params.vid,
        session_id: Number(params.sid),
      });
    },
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("useVersions", () => {
  it("loads versions for a session", async () => {
    const { result } = renderHook(() => useVersions(7));
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.versions).toHaveLength(2);
    expect(result.current.activeVersionId).toBe(
      "version_20260601_130000_000000",
    );
  });

  it("calls restore endpoint and updates active version", async () => {
    const { result } = renderHook(() => useVersions(7));
    await act(async () => {
      await result.current.refresh();
    });
    await act(async () => {
      await result.current.restore("version_20260601_120000_000000");
    });
    expect(result.current.activeVersionId).toBe(
      "version_20260601_120000_000000",
    );
  });
});
