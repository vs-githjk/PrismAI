"""Notion loader using integration token (paste-based, not OAuth)."""

from clients import get_http

from .loaders_base import LoadedDoc, LoaderError

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _extract_text(rich_text: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_text)


def _block_to_text(block: dict) -> str:
    btype = block.get("type", "")
    inner = block.get(btype, {})
    rt = inner.get("rich_text", [])
    text = _extract_text(rt)
    if btype.startswith("heading_"):
        return f"\n# {text}\n"
    if btype == "to_do":
        marker = "[x]" if inner.get("checked") else "[ ]"
        return f"{marker} {text}"
    if btype in ("bulleted_list_item", "numbered_list_item"):
        return f"- {text}"
    return text


async def _fetch_blocks(page_id: str, token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    async with get_http() as client:
        resp = await client.get(f"{NOTION_API}/blocks/{page_id}/children", headers=headers, timeout=20.0)
    if resp.status_code == 401:
        raise LoaderError("Notion token is invalid or expired — please reconnect.")
    if resp.status_code != 200:
        raise LoaderError(f"Notion API error {resp.status_code}")
    return resp.json()


async def load(page_id: str, token: str) -> LoadedDoc:
    if not token:
        raise LoaderError("Notion integration token is not configured.")

    page_id = page_id.replace("-", "").strip()
    # Format as UUID if needed
    if len(page_id) == 32:
        page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"

    data = await _fetch_blocks(page_id, token)
    parts = []
    for block in data.get("results", []):
        text = _block_to_text(block).strip()
        if text:
            parts.append(text)

    if not parts:
        raise LoaderError("Notion page is empty or has no readable blocks.")

    return LoadedDoc(text="\n".join(parts), page_metadata=[{"notion_page_id": page_id}])
