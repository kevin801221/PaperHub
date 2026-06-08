import type { ChatSession } from "@/types/domain";

/** A sidebar row: the session plus whether it should render indented as a fork
 *  of a visible parent. */
export interface SessionRow {
  session: ChatSession;
  isFork: boolean;
}

/**
 * Order the flat session list for the sidebar so each fork renders directly
 * under its parent, indented (SRS v2.30 fork lineage).
 *
 * Rules:
 *  - A session is a *root* (rendered at the top level, `isFork: false`) when it
 *    has no `forked_from_session_id` OR its parent is not in the visible list
 *    (e.g. the parent was deleted/tombstoned — the orphan falls back to a
 *    top-level row, never a dangling indent).
 *  - Roots keep their incoming order (the backend's newest-first recency).
 *  - A fork is emitted immediately after its parent, `isFork: true`. Deep
 *    chains (a fork of a fork) are flattened to a SINGLE visible indent level:
 *    every descendant of a root renders at the same indent, in depth-first
 *    order so a fork's own forks sit right beneath it.
 *  - A `visited` guard makes a malformed cycle impossible to loop on.
 *
 * Every input session appears exactly once in the output.
 */
export function groupSessionsByFork(sessions: ChatSession[]): SessionRow[] {
  const byBackendId = new Map<number, ChatSession>();
  for (const s of sessions) {
    if (s.backend_session_id !== null) byBackendId.set(s.backend_session_id, s);
  }

  // parent backend id -> child sessions (only when the parent is present),
  // preserving input order.
  const childrenOf = new Map<number, ChatSession[]>();
  for (const s of sessions) {
    const parent = s.forked_from_session_id;
    if (parent != null && byBackendId.has(parent)) {
      const arr = childrenOf.get(parent) ?? [];
      arr.push(s);
      childrenOf.set(parent, arr);
    }
  }

  const isRoot = (s: ChatSession): boolean => {
    const parent = s.forked_from_session_id;
    return parent == null || !byBackendId.has(parent);
  };

  const out: SessionRow[] = [];
  const visited = new Set<number>(); // by local id (always unique, never null)

  const emitDescendants = (root: ChatSession): void => {
    // Depth-first over the subtree, but every node renders at the single
    // visible fork indent (`isFork: true`).
    const stack: ChatSession[] =
      root.backend_session_id !== null
        ? [...(childrenOf.get(root.backend_session_id) ?? [])]
        : [];
    while (stack.length > 0) {
      const child = stack.shift()!;
      if (visited.has(child.id)) continue;
      visited.add(child.id);
      out.push({ session: child, isFork: true });
      if (child.backend_session_id !== null) {
        const grandkids = childrenOf.get(child.backend_session_id) ?? [];
        stack.unshift(...grandkids); // DFS: a fork's forks come right after it
      }
    }
  };

  for (const s of sessions) {
    if (!isRoot(s) || visited.has(s.id)) continue;
    visited.add(s.id);
    out.push({ session: s, isFork: false });
    emitDescendants(s);
  }

  // Completeness sweep: any session not reachable from a root — e.g. caught in
  // a malformed forked_from cycle with no root — renders as a top-level row, so
  // every input session appears exactly once.
  for (const s of sessions) {
    if (visited.has(s.id)) continue;
    visited.add(s.id);
    out.push({ session: s, isFork: false });
    emitDescendants(s);
  }

  return out;
}
