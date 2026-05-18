"""Process-wide MCP server registry (SRS v2.5, §III-6.1; v2.6 lazy-connect).

`MCPRegistry` is constructed once per FastAPI process. ``startup()`` loads
``mcp_servers.toml`` and **constructs** one :class:`MCPClient` per
``[[server]]`` block, but does NOT open the transport yet. Connection is
lazy on first tool use (``aggregate_tool_schemas`` or ``call``) — this
sidesteps the loopback-bootstrap race where the ``papers`` server (Task
v2.5-3) will point at the backend's own port, which is not yet accepting
connections during lifespan startup.

A server that fails to connect on its first attempt is **remembered as
failed** for the rest of the registry lifecycle — we don't want a 30-tool
palette query to hammer a permanently-dead server. Operators restart the
backend to retry.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .client import MCPClient
from .config import load_mcp_servers
from .errors import MCPUnavailableError

__all__ = ["MCPRegistry"]

_LOG = logging.getLogger(__name__)


class MCPRegistry:
    """Owns the per-process map of MCP server name → :class:`MCPClient`.

    Connection is lazy: ``startup()`` constructs clients, the first
    ``aggregate_tool_schemas()`` or ``call()`` triggers their ``connect()``.
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._connect_attempted: set[str] = set()
        self._connect_failed: set[str] = set()
        self._aggregated_schemas: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------ lifecycle

    async def startup(self, config_path: Path) -> None:
        """Load ``mcp_servers.toml`` and construct clients (no connect).

        Missing config file is non-fatal (fresh-clone-friendly): logs INFO
        and returns with an empty registry.
        """
        if not config_path.exists():  # noqa: ASYNC240
            _LOG.info(
                "mcp.registry no config at %s; starting with empty registry",
                config_path,
            )
            return

        try:
            configs = load_mcp_servers(config_path)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "mcp.registry failed to load config %s err=%s; starting empty",
                config_path,
                exc,
            )
            return

        for cfg in configs:
            self._clients[cfg.name] = MCPClient(cfg)
        _LOG.info(
            "mcp.registry loaded %d server config(s): %s",
            len(self._clients),
            sorted(self._clients),
        )

    async def shutdown(self) -> None:
        """Disconnect every client. Idempotent at the client level."""
        for name, client in self._clients.items():
            try:
                await client.disconnect()
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("mcp.registry disconnect failed server=%s err=%s", name, exc)
        self._aggregated_schemas = None

    # ------------------------------------------------------------------ public ops

    async def aggregate_tool_schemas(self) -> list[dict[str, Any]]:
        """Union of every reachable server's LiteLLM tool schemas.

        On first call, lazy-connects every configured client. Servers that
        fail to connect are logged at WARN and skipped — and **not retried**
        within this registry lifecycle. Cached after the first successful
        build; the cache is invalidated by :meth:`call` on transport failure.
        """
        if self._aggregated_schemas is not None:
            return self._aggregated_schemas

        aggregated: list[dict[str, Any]] = []
        for name, client in self._clients.items():
            if name in self._connect_failed:
                continue
            await self._ensure_connected(name, client)
            if name in self._connect_failed:
                continue
            try:
                schemas = await client.list_tools()
            except MCPUnavailableError as exc:
                _LOG.warning(
                    "mcp.registry list_tools failed server=%s err=%s; skipping",
                    name,
                    exc,
                )
                self._connect_failed.add(name)
                continue
            aggregated.extend(schemas)

        self._aggregated_schemas = aggregated
        return aggregated

    async def has_tool(self, namespaced_name: str) -> bool:
        """Convenience: is ``namespaced_name`` in the aggregated palette?"""
        schemas = await self.aggregate_tool_schemas()
        return any(s["function"]["name"] == namespaced_name for s in schemas)

    async def call(self, namespaced_name: str, args: dict[str, Any]) -> Any:
        """Dispatch ``<server>.<tool>`` to the right client.

        On :class:`MCPUnavailableError` during dispatch, invalidates the
        cached palette so the next ``aggregate_tool_schemas`` call re-checks.
        :class:`MCPToolError` is propagated without invalidating the cache
        (the connection is healthy; the upstream tool just errored).
        """
        if "." not in namespaced_name:
            raise ValueError(
                f"expected namespaced tool name '<server>.<tool>', got {namespaced_name!r}"
            )
        server_name, tool_name = namespaced_name.split(".", 1)

        client = self._clients.get(server_name)
        if client is None:
            raise MCPUnavailableError(f"no server named {server_name!r}")

        await self._ensure_connected(server_name, client)
        if server_name in self._connect_failed:
            self._aggregated_schemas = None
            raise MCPUnavailableError(
                f"MCP server {server_name!r} is unreachable; cannot dispatch "
                f"{namespaced_name!r}"
            )

        try:
            return await client.call_tool(tool_name, args)
        except MCPUnavailableError:
            self._aggregated_schemas = None
            raise

    # ------------------------------------------------------------------ internals

    async def _ensure_connected(self, name: str, client: MCPClient) -> None:
        """Lazy-connect ``client`` if we haven't tried yet this lifecycle.

        Sticky-fail: a server that failed on its first attempt is recorded
        in ``self._connect_failed`` and never retried.
        """
        if name in self._connect_attempted:
            return
        self._connect_attempted.add(name)
        try:
            await client.connect()
        except MCPUnavailableError as exc:
            _LOG.warning(
                "mcp.registry connect failed server=%s err=%s; skipping",
                name,
                exc,
            )
            self._connect_failed.add(name)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "mcp.registry unexpected connect error server=%s err=%s; skipping",
                name,
                exc,
            )
            self._connect_failed.add(name)
