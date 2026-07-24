import os
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import Request
from openai import AsyncOpenAI

DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=30.0, write=10.0, pool=3.0)

_shared_http: Optional[httpx.AsyncClient] = None
_shared_openai: Optional[AsyncOpenAI] = None
_shared_groq = None  # AsyncGroq | None — re-added Jul 2026 for the voice channel


def bind(app) -> None:
    global _shared_http, _shared_openai, _shared_groq
    _shared_http = getattr(app.state, "http", None)
    _shared_openai = getattr(app.state, "openai", None)
    _shared_groq = getattr(app.state, "groq", None)


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


def get_groq(request: Optional[Request] = None):
    """Shared AsyncGroq client for the voice channel (tool-less streaming talk brain
    — Groq's TTFT is the reason it's back). Returns None when GROQ_API_KEY is unset,
    so callers degrade to OpenAI gpt-4o-mini rather than crash. See voice_channel.py."""
    if request is not None:
        c = getattr(request.app.state, "groq", None)
        if c is not None:
            return c
    if _shared_groq is not None:
        return _shared_groq
    if not os.getenv("GROQ_API_KEY"):
        return None
    try:
        from groq import AsyncGroq
    except ImportError:
        return None
    return AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
