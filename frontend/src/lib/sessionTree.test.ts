import { describe, expect, it } from "vitest";

import { groupSessionsByFork } from "@/lib/sessionTree";
import type { ChatSession } from "@/types/domain";

function sess(
  id: number,
  backend: number | null,
  forkedFrom: number | null = null,
): ChatSession {
  return {
    id,
    title: `s${id}`,
    messages: [],
    backend_session_id: backend,
    forked_from_session_id: forkedFrom,
  };
}

const ids = (rows: { session: ChatSession }[]) =>
  rows.map((r) => r.session.id);
const forks = (rows: { session: ChatSession; isFork: boolean }[]) =>
  rows.filter((r) => r.isFork).map((r) => r.session.id);

describe("groupSessionsByFork", () => {
  it("keeps a flat list when there are no forks", () => {
    const out = groupSessionsByFork([sess(1, 10), sess(2, 20)]);
    expect(ids(out)).toEqual([1, 2]);
    expect(forks(out)).toEqual([]);
  });

  it("emits a fork directly under its parent, indented", () => {
    // recency: fork(3) is newest, then parent(1), then unrelated(2)
    const out = groupSessionsByFork([
      sess(3, 30, /*forkedFrom*/ 10),
      sess(1, 10),
      sess(2, 20),
    ]);
    // Parent pulls its fork up beneath it; unrelated session stays put.
    expect(ids(out)).toEqual([1, 3, 2]);
    expect(forks(out)).toEqual([3]);
  });

  it("groups multiple forks of the same parent", () => {
    const out = groupSessionsByFork([
      sess(1, 10),
      sess(2, 20, 10),
      sess(3, 30, 10),
    ]);
    expect(ids(out)).toEqual([1, 2, 3]);
    expect(forks(out)).toEqual([2, 3]);
  });

  it("flattens a fork-of-a-fork to one indent level, DFS order", () => {
    // 1 -> 2 -> 3 (fork of a fork); 3 must render at the same indent as 2,
    // right after 2.
    const out = groupSessionsByFork([
      sess(1, 10),
      sess(2, 20, 10),
      sess(3, 30, 20),
    ]);
    expect(ids(out)).toEqual([1, 2, 3]);
    expect(forks(out)).toEqual([2, 3]); // both indented, neither is a root
  });

  it("treats an orphaned fork (missing parent) as a top-level root", () => {
    // parent 99 is not in the list (deleted/tombstoned)
    const out = groupSessionsByFork([sess(2, 20, 99), sess(1, 10)]);
    expect(ids(out)).toEqual([2, 1]);
    expect(forks(out)).toEqual([]); // orphan is NOT indented
  });

  it("emits every session exactly once even with a malformed cycle", () => {
    // 1 <-> 2 cycle (should never happen, but must not loop)
    const out = groupSessionsByFork([sess(1, 10, 20), sess(2, 20, 10)]);
    expect(out.length).toBe(2);
    expect(new Set(ids(out))).toEqual(new Set([1, 2]));
  });
});
