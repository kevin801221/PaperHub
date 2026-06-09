import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { API_BASE_URL } from "../../lib/api";
import { useSettingsStore } from "../../store/settings";
import { SettingsModal } from "./SettingsModal";

const server = setupServer(
  http.get(`${API_BASE_URL}/settings`, () =>
    HttpResponse.json({
      categories: [
        { key: "integrations", label: "Integrations",
          fields: [{ key: "PAPERHUB_SEMANTIC_SCHOLAR_API_KEY", label: "Semantic Scholar API key",
            type: "secret", secret: true, is_set: false, restart_required: false }] },
        { key: "system", label: "System",
          fields: [{ key: "PAPERHUB_LOG_LEVEL", label: "Log level", type: "enum", value: "INFO",
            choices: ["DEBUG", "INFO"], secret: false, restart_required: true, is_default: true }] },
      ],
    }),
  ),
);

describe("SettingsModal", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
  afterAll(() => server.close());
  beforeEach(() => useSettingsStore.setState({ isOpen: true, config: null, restartPending: [] }));

  it("renders categories and a masked secret field", async () => {
    render(<SettingsModal />);
    expect(await screen.findByText("Integrations")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Integrations"));
    // Secret renders as not-set with a Replace affordance, never a value.
    expect(screen.getByText(/not set/i)).toBeInTheDocument();
  });
});
