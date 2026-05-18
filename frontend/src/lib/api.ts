import type {
  ReferenceItem,
  LibraryItem,
  AttachResult,
  IngestResult,
} from "@/types/domain";

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${text}`);
  }
  // 204 No Content
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function listSessionReferences(
  sessionId: number,
): Promise<ReferenceItem[]> {
  return apiFetch<ReferenceItem[]>(`/papers?session_id=${sessionId}`);
}

export async function toggleReference(
  papersId: number,
  enabled: boolean,
): Promise<{ enabled: boolean }> {
  return apiFetch<{ enabled: boolean }>(`/papers/${papersId}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

export async function removeReference(papersId: number): Promise<void> {
  await apiFetch<undefined>(`/papers/${papersId}`, { method: "DELETE" });
}

export async function listLibrary(
  sessionId: number,
  q?: string,
  limit?: number,
  offset?: number,
): Promise<LibraryItem[]> {
  const params = new URLSearchParams({ session_id: String(sessionId) });
  if (q) params.set("q", q);
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  return apiFetch<LibraryItem[]>(`/papers/library?${params.toString()}`);
}

export async function attachFromLibrary(
  sessionId: number,
  paperContentId: number,
): Promise<AttachResult> {
  return apiFetch<AttachResult>("/papers/from-library", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      paper_content_id: paperContentId,
    }),
  });
}

export async function ingestPaper(
  sessionId: number,
  paperId: string,
  metadata?: {
    title: string;
    abstract: string | null;
    authors: string[];
    year: number | null;
  },
): Promise<IngestResult> {
  const body: Record<string, unknown> = {
    session_id: sessionId,
    paper_id: paperId,
  };
  if (metadata) {
    body.title = metadata.title;
    body.abstract = metadata.abstract;
    body.authors = metadata.authors;
    body.year = metadata.year;
  }
  return apiFetch<IngestResult>("/papers", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function createBackendSession(): Promise<number> {
  const data = await apiFetch<{ session_id: number }>("/sessions", {
    method: "POST",
  });
  return data.session_id;
}

/** Custom error thrown by deleteLibraryPaper when the paper is still attached
 * to one or more sessions and force=false. The UI can read `session_count` to
 * compose a confirmation prompt and retry with force=true. */
export class PaperInUseByOtherSessions extends Error {
  readonly session_count: number;
  constructor(session_count: number) {
    super(`paper is referenced by ${session_count} session(s)`);
    this.name = "PaperInUseByOtherSessions";
    this.session_count = session_count;
  }
}

/** Purge a paper from the library entirely — paper_content row + chunks +
 * Chroma vectors + on-disk cache. Destructive; test-friendly endpoint.
 *
 * @throws PaperInUseByOtherSessions on 409 (without force).
 */
export async function deleteLibraryPaper(
  paperContentId: number,
  force = false,
): Promise<void> {
  const url = `/papers/content/${paperContentId}${force ? "?force=true" : ""}`;
  const res = await fetch(`${API_BASE_URL}${url}`, { method: "DELETE" });
  if (res.status === 204) return;
  if (res.status === 409) {
    const body = (await res.json().catch(() => ({}))) as {
      detail?: { session_count?: number };
    };
    throw new PaperInUseByOtherSessions(body.detail?.session_count ?? 0);
  }
  const text = await res.text().catch(() => "");
  throw new Error(`API ${res.status}: ${text}`);
}
