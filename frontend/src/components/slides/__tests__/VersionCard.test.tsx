import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VersionCard } from "@/components/slides/VersionCard";


const baseVersion = {
  version_id: "version_20260601_130000_000000",
  timestamp: "20260601_130000",
  description: "F4.5 sl_emit snapshot",
  page_count: 9,
  is_active: true,
};


describe("VersionCard", () => {
  it("active variant renders 'Open Slide' button (mirrors active deck card)", () => {
    render(
      <VersionCard
        version={baseVersion}
        onSwitch={vi.fn()}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /open slide/i })).toBeInTheDocument();
    // Not the switch button — active version is already active.
    expect(screen.queryByRole("button", { name: /switch to this version/i })).not.toBeInTheDocument();
  });

  it("older variant renders 'Switch to this version' button", () => {
    const older = { ...baseVersion, is_active: false };
    render(
      <VersionCard
        version={older}
        onSwitch={vi.fn()}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /switch to this version/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open slide/i })).not.toBeInTheDocument();
  });

  it("clicking switch fires onSwitch with version_id", () => {
    const onSwitch = vi.fn();
    const older = { ...baseVersion, is_active: false };
    render(<VersionCard version={older} onSwitch={onSwitch} onOpen={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /switch to this version/i }));
    expect(onSwitch).toHaveBeenCalledWith("version_20260601_130000_000000");
  });

  it("renders page count + description + readable timestamp", () => {
    render(<VersionCard version={baseVersion} onSwitch={vi.fn()} onOpen={vi.fn()} />);
    expect(screen.getByText(/9 pages/i)).toBeInTheDocument();
    expect(screen.getByText(/F4\.5 sl_emit snapshot/i)).toBeInTheDocument();
    // The timestamp parser should render some human-readable date.
    expect(screen.getByText(/2026/)).toBeInTheDocument();
  });
});
