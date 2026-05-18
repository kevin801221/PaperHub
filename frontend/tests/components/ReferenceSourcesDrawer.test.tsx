import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { ReferenceSourcesDrawer } from "@/components/references/ReferenceSourcesDrawer";
import { useChatStore } from "@/store/chat";
import { API_BASE_URL } from "@/lib/api";
import type { ReferenceItem } from "@/types/domain";

function makeRef(overrides: Partial<ReferenceItem> = {}): ReferenceItem {
  return {
    papers_id: 1,
    paper_content_id: 1,
    enabled: true,
    added_at: "2024-01-01T00:00:00",
    arxiv_id: "1706.03762",
    title: "Attention Is All You Need",
    year: 2017,
    kind: "arxiv",
    ...overrides,
  };
}

const sampleRefs = [makeRef()];

const server = setupServer(
  http.get(`${API_BASE_URL}/papers`, () =>
    HttpResponse.json(sampleRefs),
  ),
  http.patch(`${API_BASE_URL}/papers/1`, () =>
    HttpResponse.json({ enabled: false }),
  ),
  http.delete(`${API_BASE_URL}/papers/1`, () =>
    new HttpResponse(null, { status: 204 }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  server.resetHandlers(
    http.get(`${API_BASE_URL}/papers`, () => HttpResponse.json(sampleRefs)),
    http.patch(`${API_BASE_URL}/papers/1`, () =>
      HttpResponse.json({ enabled: false }),
    ),
    http.delete(`${API_BASE_URL}/papers/1`, () =>
      new HttpResponse(null, { status: 204 }),
    ),
  );
  useChatStore.getState().reset();
});

describe("ReferenceSourcesDrawer", () => {
  it("renders nothing when backendSessionId is null", () => {
    const { container } = render(
      <ReferenceSourcesDrawer backendSessionId={null} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("loads and displays references on open", async () => {
    render(<ReferenceSourcesDrawer backendSessionId={42} />);

    // Trigger button should be visible
    const triggerBtn = await screen.findByRole("button", {
      name: /references/i,
    });
    await userEvent.click(triggerBtn);

    // Panel opens and shows the reference title
    await waitFor(() => {
      expect(
        screen.getByText("Attention Is All You Need"),
      ).toBeInTheDocument();
    });
  });

  it("removes reference from local store when trash is clicked", async () => {
    // Pre-populate the store so the drawer renders refs immediately
    useChatStore.getState().setReferences(42, sampleRefs);

    render(<ReferenceSourcesDrawer backendSessionId={42} />);

    const triggerBtn = screen.getByRole("button", { name: /references/i });
    await userEvent.click(triggerBtn);

    const trashBtn = await screen.findByRole("button", {
      name: /remove attention is all you need/i,
    });
    await userEvent.click(trashBtn);

    await waitFor(() => {
      expect(
        useChatStore.getState().referencesBySession[42],
      ).toHaveLength(0);
    });
  });
});
