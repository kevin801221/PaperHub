import asyncio
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import litellm
from pydantic import BaseModel

from paperhub.llm.prompts.registry import PromptRegistry

T = TypeVar("T", bound=BaseModel)


# Connection-drop signatures we treat as recoverable in mid-stream — same
# class as the non-streaming ``litellm.num_retries`` catches, but applied
# manually because num_retries doesn't restart streaming responses.
_TRANSIENT_STREAM_SUBSTRINGS: tuple[str, ...] = (
    "Server disconnected",
    "MidStreamFallbackError",
    "APIConnectionError",
    "ServerDisconnectedError",
    "ConnectError",
    "RemoteProtocolError",
    "ReadTimeout",
    "ConnectTimeout",
    "503",
    "504",
    "502",
)


def _is_transient_stream_error(exc: BaseException) -> bool:
    """True if the exception looks like a recoverable upstream connection drop.

    Matches by class name + string content (litellm wraps provider errors in
    its own class hierarchy, so isinstance checks against httpx/openai types
    are unreliable). False positives just trigger an extra retry which is
    cheap; false negatives lose work which is expensive.
    """
    needle = type(exc).__name__ + ": " + str(exc)
    return any(s in needle for s in _TRANSIENT_STREAM_SUBSTRINGS)


class LiteLlmAdapter:
    def __init__(self, registry: PromptRegistry | None = None) -> None:
        self._registry = registry or PromptRegistry()

    def _messages(
        self,
        slot: str,
        variables: dict[str, Any],
        history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        prompt = self._registry.get(slot)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": prompt.system},
        ]
        if history:
            for h in history:
                role = h.get("role")
                content = h.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        messages.append(
            {"role": "user", "content": prompt.user_template.format(**variables)},
        )
        return messages

    async def structured(
        self,
        *,
        slot: str,
        variables: dict[str, Any],
        response_model: type[T],
        model: str,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> T:
        # Pass the Pydantic class directly so LiteLLM translates it into each
        # provider's native structured-output mode (Gemini responseSchema, OpenAI
        # json_schema, Anthropic tool-use shim). The model is then constrained
        # at the API boundary, not just by prompt phrasing.
        response = await litellm.acompletion(
            model=model,
            messages=self._messages(slot, variables, history),
            response_format=response_model,
            **kwargs,
        )
        content = response["choices"][0]["message"]["content"]
        return response_model.model_validate_json(content)

    async def stream(
        self,
        *,
        slot: str,
        variables: dict[str, Any],
        model: str,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        # Streaming + transient-error retry-from-start. ``litellm.num_retries``
        # only catches errors BEFORE the stream starts; mid-stream
        # ``MidStreamFallbackError`` / ``APIConnectionError`` / 5xx are not
        # retried by litellm itself because the partial stream can't be
        # resumed. Wrap the whole stream in a retry loop: on transient mid-
        # stream failure, discard any partial yield and restart from scratch.
        # Permanent errors (bad request, auth) propagate immediately.
        max_attempts = 3
        backoff_base = 1.0  # 1s, 2s, 4s
        last_exc: BaseException | None = None
        for attempt in range(1, max_attempts + 1):
            buffered: list[str] = []
            try:
                response = await litellm.acompletion(
                    model=model,
                    messages=self._messages(slot, variables, history),
                    stream=True,
                    **kwargs,
                )
                async for chunk in response:
                    delta = chunk["choices"][0].get("delta", {}).get("content") or ""
                    if delta:
                        buffered.append(delta)
                # Stream completed successfully; flush buffered tokens to the
                # caller in one go. (We could not yield incrementally because
                # the caller would already have consumed partial tokens if we
                # then had to retry. Buffering trades a small latency hit for
                # crash-free resilience.)
                for tok in buffered:
                    yield tok
                return
            except Exception as exc:
                last_exc = exc
                if attempt >= max_attempts or not _is_transient_stream_error(exc):
                    raise
                await asyncio.sleep(backoff_base * (2 ** (attempt - 1)))
        # Defensive — the loop above either returns or raises.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("stream retry loop fell through without yielding")
