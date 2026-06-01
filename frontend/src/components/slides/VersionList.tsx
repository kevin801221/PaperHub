import { useCallback } from "react";

import { VersionCard } from "./VersionCard";
import { useVersions } from "@/state/versions";


interface VersionListProps {
  sessionId: number;
  /** Called when the user clicks "Open Slide" on the active version's card. */
  onOpen: () => void;
}


/**
 * VersionList — F4.5 deck version history drawer body.
 *
 * Wraps the `useVersions(sessionId)` hook + renders one `VersionCard` per
 * snapshot returned by the backend. The active version floats to the top;
 * older versions follow in timestamp-desc order so the freshest history is
 * always near the active card. Loading / error / empty states render
 * compact muted messages (the drawer header in `SlidesPanel` carries the
 * affordance, so this body stays quiet).
 */
export function VersionList({ sessionId, onOpen }: VersionListProps) {
  const { versions, restore, loading, error } = useVersions(sessionId);

  const handleSwitch = useCallback(
    (versionId: string) => {
      // Fire-and-forget: the hook surfaces `error` if the restore call fails;
      // the local `.catch` is for unhandled-rejection hygiene. We keep the
      // callback void-returning so `VersionCard.onSwitch` (typed as `(id) =>
      // void`) doesn't trip the no-misused-promises lint rule.
      void restore(versionId).catch((e: unknown) => {
        console.error("Failed to restore version", e);
      });
    },
    [restore],
  );

  if (loading && versions.length === 0) {
    return (
      <div className="p-2 text-xs text-muted-foreground">
        Loading versions…
      </div>
    );
  }
  if (error) {
    return (
      <div className="p-2 text-xs text-destructive">
        Failed to load versions: {error}
      </div>
    );
  }
  if (versions.length === 0) {
    return (
      <div className="p-2 text-xs text-muted-foreground">
        No version history yet — generate a deck to start tracking versions.
      </div>
    );
  }

  // Order: active first, then by timestamp desc. The backend already orders
  // by timestamp desc but the active row could land anywhere, so we lift it
  // explicitly here so the drawer's top-of-list is always "what's open now".
  const ordered = [...versions].sort((a, b) => {
    if (a.is_active && !b.is_active) return -1;
    if (b.is_active && !a.is_active) return 1;
    return (b.timestamp ?? "").localeCompare(a.timestamp ?? "");
  });

  return (
    <div
      className="flex flex-col gap-2 p-2"
      aria-label="Deck version history"
    >
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Version history
      </h3>
      {ordered.map((v) => (
        <VersionCard
          key={v.version_id}
          version={v}
          onSwitch={handleSwitch}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}
