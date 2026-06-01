import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { VersionList } from "@/components/slides/VersionList";
import { useVersionsStore } from "@/state/versions";


const server = setupServer(
  http.get("*/sessions/:sid/deck/versions", () =>
    HttpResponse.json([
      {
        version_id: "v_new",
        timestamp: "20260601_130000",
        description: "latest",
        page_count: 9,
        is_active: true,
      },
      {
        version_id: "v_old",
        timestamp: "20260601_120000",
        description: "first",
        page_count: 8,
        is_active: false,
      },
    ]),
  ),
  http.post("*/sessions/:sid/deck/versions/:vid/restore", ({ params }) =>
    HttpResponse.json({
      ok: true,
      current_version_id: params.vid,
      session_id: Number(params.sid),
    }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  // Reset Zustand store between tests so a previous render's fetched versions
  // don't leak into the next case (notably the empty-state test).
  useVersionsStore.setState({ bySession: {} });
});
afterAll(() => server.close());


describe("VersionList", () => {
  it("renders one card per version with active card first", async () => {
    render(<VersionList sessionId={7} onOpen={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByTestId("version-card-v_new")).toBeInTheDocument();
      expect(screen.getByTestId("version-card-v_old")).toBeInTheDocument();
    });
    expect(screen.getByTestId("version-card-v_new")).toHaveAttribute("data-active", "true");
    expect(screen.getByTestId("version-card-v_old")).toHaveAttribute("data-active", "false");
  });

  it("calls onOpen when the active card's Open button is clicked", async () => {
    const onOpen = vi.fn();
    render(<VersionList sessionId={7} onOpen={onOpen} />);
    await waitFor(() => screen.getByTestId("version-card-v_new"));
    const button = screen.getByRole("button", { name: /open slide/i });
    fireEvent.click(button);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("renders empty state when no versions exist", async () => {
    server.use(
      http.get("*/sessions/:sid/deck/versions", () => HttpResponse.json([])),
    );
    render(<VersionList sessionId={8} onOpen={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getByText(/no version history yet/i)).toBeInTheDocument(),
    );
  });
});
