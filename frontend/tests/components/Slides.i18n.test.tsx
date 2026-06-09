import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import i18n from "@/lib/i18n";
import { slideStageLabel } from "@/lib/slideStage";
import { PresenterControls } from "@/components/slides/PresenterControls";

describe("slides i18n", () => {
  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("localizes the presenter cockpit chrome when the language switches", async () => {
    const base = {
      startedAt: 0,
      currentPage: 1,
      numPages: 5,
      audienceConnected: true,
      onStop: vi.fn(),
      now: () => 0,
    };

    const { rerender } = render(<PresenterControls {...base} />);
    expect(screen.getByText("audience connected")).toBeInTheDocument();
    expect(screen.getByText("Stop")).toBeInTheDocument();

    await i18n.changeLanguage("ja");
    rerender(<PresenterControls {...base} />);
    expect(screen.getByText("観客が接続しました")).toBeInTheDocument();
    expect(screen.getByText("停止")).toBeInTheDocument();
  });

  it("resolves the slide-stage label in the active language", async () => {
    const trace = [{ tool: "report:sl_compile" } as never];

    expect(slideStageLabel(trace)).toBe("Compiling the deck (LaTeX)…");

    await i18n.changeLanguage("ja");
    expect(slideStageLabel(trace)).toBe("デッキをコンパイル中（LaTeX）…");
  });
});
