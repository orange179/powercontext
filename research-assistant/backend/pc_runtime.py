"""Embedded PowerContext runtime for the Research Assistant.

Starts PowerContext fully in-process (SQLite persistence, ASGI transport) so the
application genuinely saves and recalls memory without any external server.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime.config import ExternalSkillsConfig, InferenceConfig, RuntimeConfig
from powercontext.client import PowerContextClient
from powercontext.server.factory import create_server_app
from powercontext.server.settings import (
    AccessControlConfig,
    BearerAuthConfig,
    HttpConfig,
    McpConfig,
    MetricsConfig,
    ServerSettings,
    TracingConfig,
)


def build_server(workspace: Path):
    workspace.mkdir(parents=True, exist_ok=True)
    settings = ServerSettings(
        workspace=workspace,
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{workspace / 'powercontext.db'}"),
        http=HttpConfig(host="127.0.0.1"),
        auth=BearerAuthConfig(enabled=False),
        access=AccessControlConfig(mode="disabled"),
        inference=InferenceConfig(),
        runtime=RuntimeConfig(schedule_seconds=None, experience_schedule_seconds=None),
        external_skills=ExternalSkillsConfig(),
        mcp=McpConfig(enabled=False),
        metrics=MetricsConfig(enabled=False),
        tracing=TracingConfig(enabled=False),
    )
    return create_server_app(settings=settings, scheduler_path=workspace / "scheduler.db")


@asynccontextmanager
async def embedded_powercontext(workspace: Path) -> AsyncIterator[PowerContextClient]:
    """Yield a real PowerContextClient backed by an in-process ASGI app."""
    app = build_server(workspace)
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://powercontext.local", timeout=60)
    client = PowerContextClient(
        "http://powercontext.local",
        http_client=http_client,
        trust_transport_security=True,
        timeout=60,
    )
    # ASGITransport does not run lifespan events; drive the server's lifespan manually
    # so the runtime becomes ready before the first request.
    async with app.router.lifespan_context(app):
        try:
            yield client
        finally:
            await client.aclose()
