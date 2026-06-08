import { describe, expect, it, beforeEach } from "vitest";
import { useSlidesStore } from "./slides";

describe("slideAttached", () => {
  beforeEach(() => {
    useSlidesStore.setState({ slideAttachedBySession: {} });
  });

  it("defaults to attached (undefined) and toggles sticky per session", () => {
    const { setSlideAttached } = useSlidesStore.getState();
    expect(useSlidesStore.getState().slideAttachedBySession[7]).toBeUndefined();
    setSlideAttached(7, false);
    expect(useSlidesStore.getState().slideAttachedBySession[7]).toBe(false);
    setSlideAttached(7, true);
    expect(useSlidesStore.getState().slideAttachedBySession[7]).toBe(true);
  });
});
