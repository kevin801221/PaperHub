import { renderHook, act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { useChatStream } from "@/hooks/useChatStream";
import { useChatStore } from "@/store/chat";
import { API_BASE_URL } from "@/lib/api";
import { chitchatHappyPath } from "../stubs/sse";

const server = setupServer(chitchatHappyPath);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  server.resetHandlers(chitchatHappyPath);
  useChatStore.getState().reset();
});

const enc = new TextEncoder();
function chunk(event: string, data: unknown): Uint8Array {
  return enc.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

const midStreamFailure = http.post(`${API_BASE_URL}/chat`, () => {
  const stream = new ReadableStream({
    start(controller) {
      // Enqueue the two pre-error events synchronously so the reader can pull them.
      controller.enqueue(
        chunk("tool_step", {
          record: {
            run_id: 7, branch: "", step_index: 0, agent: "router",
            tool: "classify", model: "x", latency_ms: 12, status: "ok",
            parent_step: null, args_redacted_json: null,
            result_summary_json: null, token_in: null, token_out: null,
            error: null,
          },
        }),
      );
      controller.enqueue(
        chunk("routing_decision", {
          run_id: 7, branch: "",
          decision: {
            intent: "chitchat", model_tier: "small",
            confidence: 0.9, reasoning: "x",
          },
        }),
      );
      // Defer the error so the reader processes the queued chunks first,
      // then sees the stream abort mid-flight (simulating a network blip).
      setTimeout(() => controller.error(new Error("network blip")), 10);
    },
  });
  return new HttpResponse(stream, {
    headers: { "Content-Type": "text/event-stream" },
  });
});

describe("useChatStream", () => {
  it("runs a chitchat round-trip and updates the store", async () => {
    const sessionId = useChatStore.getState().newSession();
    const { result } = renderHook(() => useChatStream());

    await act(async () => {
      await result.current.send(sessionId, "hello");
    });

    await waitFor(() => {
      const session = useChatStore.getState().sessions.find((s) => s.id === sessionId);
      expect(session).toBeDefined();
      const assistant = session!.messages.find((m) => m.role === "assistant");
      expect(assistant).toBeDefined();
      expect(assistant!.status).toBe("ok");
      expect(assistant!.content).toBe("Hi there!");
      expect(assistant!.routing_decision?.intent).toBe("chitchat");
      expect(assistant!.trace).toHaveLength(1);
    });
  });

  it("flips the streaming placeholder to error when SSE fails before any event", async () => {
    server.resetHandlers(
      http.post(`${API_BASE_URL}/chat`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const sessionId = useChatStore.getState().newSession();
    const { result } = renderHook(() => useChatStream());

    let threw = false;
    await act(async () => {
      try {
        await result.current.send(sessionId, "hello");
      } catch {
        threw = true;
      }
    });

    expect(threw).toBe(true); // pre-event failures DO propagate to caller (→ toast)

    await waitFor(() => {
      const session = useChatStore.getState().sessions.find((s) => s.id === sessionId);
      const assistant = session!.messages.find((m) => m.role === "assistant")!;
      expect(assistant.status).toBe("error");
      expect(assistant.error).toBeTruthy();
    });
  });

  it("mid-stream failure: inline error only, no re-throw", async () => {
    server.resetHandlers(midStreamFailure);
    const sessionId = useChatStore.getState().newSession();
    const { result } = renderHook(() => useChatStream());

    let threw = false;
    await act(async () => {
      try {
        await result.current.send(sessionId, "hello");
      } catch {
        threw = true;
      }
    });

    expect(threw).toBe(false); // mid-stream errors must NOT propagate

    await waitFor(() => {
      const session = useChatStore.getState().sessions.find((s) => s.id === sessionId);
      const assistant = session!.messages.find((m) => m.role === "assistant")!;
      expect(assistant.status).toBe("error");
      expect(assistant.error).toBeTruthy();
      // The run_id was patched from the tool_step before the failure
      expect(assistant.run_id).toBe(7);
    });
  });
});
