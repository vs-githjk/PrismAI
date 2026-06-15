import os
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import Request
from openai import AsyncOpenAI

DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=30.0, write=10.0, pool=3.0)

_shared_http: Optional[httpx.AsyncClient] = None
_shared_openai: Optional[AsyncOpenAI] = None


def bind(app) -> None:
    global _shared_http, _shared_openai
    _shared_http = getattr(app.state, "http", None)
    _shared_openai = getattr(app.state, "openai", None)


@asynccontextmanager
async def get_http(request: Optional[Request] = None):
    client = None
    if request is not None:
        client = getattr(request.app.state, "http", None)
    if client is None:
        client = _shared_http
    if client is not None:
        yield client
        return
    print("WARNING [clients] shared http client missing; fell back to transient")
    async with httpx.AsyncClient(http2=True, timeout=DEFAULT_TIMEOUT) as transient:
        yield transient


def get_openai(request: Optional[Request] = None) -> AsyncOpenAI:
    """Shared OpenAI client — used for the OpenAI-shaped tool-calling / streaming
    surfaces (chat + live bot) and audio transcription. (Claude handles the agent
    + RAG paths via agents.utils.llm_call.)"""
    if request is not None:
        c = getattr(request.app.state, "openai", None)
        if c is not None:
            return c
    if _shared_openai is not None:
        return _shared_openai
    print("WARNING [clients] shared openai client missing; fell back to transient")
    return AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
