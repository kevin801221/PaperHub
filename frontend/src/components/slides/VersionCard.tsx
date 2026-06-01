import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import type { DeckVersion } from "@/state/versions";


interface VersionCardProps {
  version: DeckVersion;
  /** Restore an older version. Called with the version's id. */
  onSwitch: (versionId: string) => void;
  /** Open the active version in the Slides panel (mirrors `DeckChip`'s Open). */
  onOpen: () => void;
}


/**
 * Parse the F4.5 backend's `YYYYMMDD_HHMMSS[_micros]` timestamp into a
 * readable string. Falls back to the raw value (or "unknown time") so a
 * malformed/null entry still renders the card.
 */
function formatTimestamp(ts: string | null): string {
  if (!ts) return "unknown time";
  const m = ts.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
  if (!m) return ts;
  const [, y, mo, d, h, mi, s] = m;
  return `${y}-${mo}-${d} ${h}:${mi}:${s}`;
}


/**
 * VersionCard — one row in the deck version history list (F4.5).
 *
 * Visual language mirrors `DeckChip` / `SearchResultList` rows: a `bg-card`
 * panel with a `border-border` outline and a small action button on the
 * right. The ACTIVE variant exposes "Open Slide" (same affordance as the
 * deck chip's Open); OLDER variants expose "Switch to this version".
 */
export function VersionCard({ version, onSwitch, onOpen }: VersionCardProps) {
  const handleSwitch = useCallback(
    () => onSwitch(version.version_id),
    [onSwitch, version.version_id],
  );

  return (
    <div
      className={`rounded-xl border bg-card px-3 py-2.5 text-sm shadow-sm transition-colors ${
        version.is_active
          ? "border-primary/60"
          : "border-border hover:border-primary/30"
      }`}
      data-testid={`version-card-${version.version_id}`}
      data-active={version.is_active}
    >
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <p className="font-medium leading-snug truncate">
            {version.is_active && (
              <span
                aria-hidden
                className="mr-1 text-primary"
              >
                ●
              </span>
            )}
            {formatTimestamp(version.timestamp)}
          </p>
          <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
            <span>
              {version.page_count} page{version.page_count !== 1 ? "s" : ""}
            </span>
          </div>
          <p
            className="mt-1 truncate text-xs text-muted-foreground"
            title={version.description}
          >
            {version.description}
          </p>
        </div>

        <div className="shrink-0">
          {version.is_active ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onOpen}
              className="h-7 px-2 text-xs"
              aria-label="Open Slide"
            >
              Open Slide
            </Button>
          ) : (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={handleSwitch}
              className="h-7 px-2 text-xs"
              aria-label="Switch to this version"
            >
              Switch to this version
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
