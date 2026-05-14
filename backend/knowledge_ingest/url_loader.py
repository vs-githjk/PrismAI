"""URL loader using Tavily Extract with Jina Reader fallback."""

import os

from clients import get_http

from .loaders_base import LoadedDoc, LoaderError

TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


async def _try_tavily(url: str) -> str:
    tavily_key = os.getenv("TAVILY_API_KEY", "")
    if not tavily_key:
        return ""
    async with get_http() as client:
        resp = await client.post(
            TAVILY_EXTRACT_URL,
            json={"urls": [url], "api_key": tavily_key},
            timeout=30.0,
        )
    if resp.status_code != 200:
        return ""
    data = resp.json()
    results = data.get("results") or []
    if not results:
        return ""
    return (results[0].get("raw_content") or "").strip()


async def _try_jina(url: str) -> str:
    async with get_http() as client:
        resp = await client.get(f"https://r.jina.ai/{url}", timeout=30.0)
    if resp.status_code != 200:
        return ""
    return (resp.text or "").strip()


async def load(url: str) -> LoadedDoc:
    text = await _try_tavily(url)
    if not text:
        text = await _try_jina(url)
    if not text:
        raise LoaderError(
            "Couldn't extract content from this URL. It may require login or "
            "render content with JavaScript. Try exporting the page as a PDF and uploading that instead."
        )
    return LoadedDoc(text=text, page_metadata=[{"source_url": url}])
