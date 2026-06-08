// frontend/src/lib/settingsApi.test.ts
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { API_BASE_URL, getSettings, patchSettings } from "./api";

const server = setupServer(
  http.get(`${API_BASE_URL}/settings`, () =>
    HttpResponse.json({
      categories: [
        { key: "logging", label: "Logging", free_form: false, suggestions: [],
          fields: [{ key: "PAPERHUB_LOG_LEVEL", label: "Log level", type: "enum",
            value: "INFO", choices: ["DEBUG", "INFO"], secret: false,
            restart_required: true, read_only: false, is_default: true }] },
      ],
    }),
  ),
  http.patch(`${API_BASE_URL}/settings`, () =>
    HttpResponse.json({ updated: ["PAPERHUB_LOG_LEVEL"], cleared: [], restart_required: ["PAPERHUB_LOG_LEVEL"] }),
  ),
);

describe("settings api", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
  afterAll(() => server.close());

  it("getSettings returns categories", async () => {
    const cfg = await getSettings();
    expect(cfg.categories[0]!.key).toBe("logging");
  });

  it("patchSettings returns restart_required", async () => {
    const res = await patchSettings({ PAPERHUB_LOG_LEVEL: "DEBUG" });
    expect(res.restart_required).toContain("PAPERHUB_LOG_LEVEL");
  });
});
