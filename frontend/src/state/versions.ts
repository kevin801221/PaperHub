import { useCallback, useEffect, useMemo, useState } from "react";
import { create } from "zustand";

import { API_BASE_URL } from "@/lib/api";

/**
 * Frontend representation of one deck-version snapshot returned by the
 * F4.5 backend (`GET /sessions/{sid}/deck/versions`). The backend stamps
 * a snapshot on every `sl_emit` and records its id on `decks.current_version_id`.
 */
export interface DeckVersion {
  version_id: string;
  timestamp: string | null;
  description: string;
  page_count: number;
  is_active: boolean;
}

interface VersionsStore {
  bySession: Record<number, DeckVersion[]>;
  set: (sessionId: number, versions: DeckVersion[]) => void;
  markActive: (sessionId: number, versionId: string) => void;
}

/**
 * Lightweight Zustand store keyed by backend session id. Kept ephemeral
 * (no `persist`): the version history is cheap to refetch from the
 * backend and always trails the authoritative DB state, so caching
 * across reloads would risk serving a stale "active" pointer.
 */
export const useVersionsStore = create<VersionsStore>((set) => ({
  bySession: {},
  set: (sessionId, versions) =>
    set((s) => ({
      bySession: { ...s.bySession, [sessionId]: versions },
    })),
  markActive: (sessionId, versionId) =>
    set((s) => {
      const list = s.bySession[sessionId];
      if (!list) return s;
      return {
        bySession: {
          ...s.bySession,
          [sessionId]: list.map((v) => ({
            ...v,
            is_active: v.version_id === versionId,
          })),
        },
      };
    }),
}));

/**
 * React hook over `useVersionsStore` for a single session. Exposes the
 * current cached list, the active version id (derived), a `refresh()`
 * thunk that re-fetches from the backend, and a `restore(versionId)`
 * thunk that calls the restore endpoint and optimistically flips the
 * active flag on success.
 *
 * Initial fetch fires automatically on `sessionId` change.
 */
const EMPTY_VERSIONS: readonly DeckVersion[] = Object.freeze([]);

export function useVersions(sessionId: number | null) {
  // NOTE: select the raw bucket (may be undefined) so the snapshot is stable
  // — `?? []` inside the selector returns a fresh array every render and
  // makes Zustand's snapshot comparator see a change, causing an infinite
  // setState loop. We coalesce to a frozen singleton AFTER selection.
  const versionsBucket = useVersionsStore((s) =>
    sessionId != null ? s.bySession[sessionId] : undefined,
  );
  const versions: readonly DeckVersion[] = versionsBucket ?? EMPTY_VERSIONS;
  const setVersions = useVersionsStore((s) => s.set);
  const markActive = useVersionsStore((s) => s.markActive);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (sessionId == null) return;
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(
        `${API_BASE_URL}/sessions/${sessionId}/deck/versions`,
        {
          headers: { "X-Paperhub-Session-Id": String(sessionId) },
        },
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = (await r.json()) as DeckVersion[];
      setVersions(sessionId, data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [sessionId, setVersions]);

  const restore = useCallback(
    async (versionId: string) => {
      if (sessionId == null) return;
      const r = await fetch(
        `${API_BASE_URL}/sessions/${sessionId}/deck/versions/${versionId}/restore`,
        {
          method: "POST",
          headers: { "X-Paperhub-Session-Id": String(sessionId) },
        },
      );
      if (!r.ok) throw new Error(`Restore failed: HTTP ${r.status}`);
      markActive(sessionId, versionId);
    },
    [sessionId, markActive],
  );

  // Initial load on session change. We inline the fetch (rather than calling
  // `refresh()` synchronously) because lint's `react-hooks/set-state-in-effect`
  // flags any sync setState-bearing call in an effect body. The async work's
  // writes only land after `await`, but the rule is conservative — we mirror
  // the `useDeckSync` pattern (inline `.then` chain, `cancelled` flag for
  // unmount safety) instead of fighting the rule.
  useEffect(() => {
    if (sessionId == null) return;
    let cancelled = false;
    fetch(`${API_BASE_URL}/sessions/${sessionId}/deck/versions`, {
      headers: { "X-Paperhub-Session-Id": String(sessionId) },
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as DeckVersion[];
        if (cancelled) return;
        setVersions(sessionId, data);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, setVersions]);

  const activeVersionId = useMemo(
    () => versions.find((v) => v.is_active)?.version_id ?? null,
    [versions],
  );

  return { versions, activeVersionId, loading, error, refresh, restore };
}
