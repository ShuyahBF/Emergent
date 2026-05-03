"""Session-scoped event loop shared across all SAWALI test modules.

Motor (the async MongoDB driver) binds itself to the first asyncio loop it
sees. When tests use both `asyncio.run(...)` and `event_loop.run_until_complete(...)`
across files, motor refuses to reuse a fresh loop. By exposing a single
session-scoped `event_loop` here, all tests share the same loop, keeping
motor bound consistently.
"""
from __future__ import annotations

import asyncio
import pytest


@pytest.fixture(scope="session")
def event_loop():
    """One shared asyncio loop for the whole test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
