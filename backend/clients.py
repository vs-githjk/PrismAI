import os
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import Request
from groq import AsyncGroq

DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=30.0, write=10.0, pool=3.0)

_shared_http: Optional[httpx.AsyncClient] = None
_shared_groq: Optional[AsyncGroq] = None


def bind(app) -> None:
    global _shared_http, _shared_groq
    _shared_http = getattr(app.state, "http", None)
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


def get_groq(request: Optional[Request] = None) -> AsyncGroq:
    if request is not None:
        c = getattr(request.app.state, "groq", None)
        if c is not None:
            return c
    if _shared_groq is not None:
        return _shared_groq
    print("WARNING [clients] shared groq client missing; fell back to transient")
    return AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
