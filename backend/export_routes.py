import re

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(tags=["export"])


def _safe_json(response):
    try:
        return response.json()
    except ValueError:
        return {}


class NotionExportRequest(BaseModel):
    token: str
    parent_page_id: str
    title: str
    result: dict


class SlackExportRequest(BaseModel):
    webhook_url: str
    title: str
    result: dict


def _notion_rich_text(content: str) -> list:
    chunks = []
    for i in range(0, len(content), 2000):
        chunks.append({"type": "text", "text": {"content": content[i:i+2000]}})
    return chunks or [{"type": "text", "text": {"content": ""}}]


def _h2(text: str) -> dict:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _notion_rich_text(text)}}


def _para(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _notion_rich_text(text)}}


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _todo(text: str, checked: bool = False) -> dict:
    return {"object": "block", "type": "to_do", "to_do": {"rich_text": _notion_rich_text(text), "checked": checked}}


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _notion_rich_text(text)}}


def _build_notion_blocks(result: dict) -> list:
    blocks = []
    health = result.get("health_score") or {}
    if health.get("score") is not None:
        blocks.append(_h2(f"Meeting Health: {health['score']}/100"))
        if health.get("verdict"):
            blocks.append(_para(health["verdict"]))
        if health.get("badges"):
            blocks.append(_para("Badges: " + ", ".join(health["badges"])))
        blocks.append(_divider())

    if result.get("summary"):
        blocks.append(_h2("Summary"))
        blocks.append(_para(result["summary"]))
        blocks.append(_divider())

    items = result.get("action_items") or []
    if items:
        blocks.append(_h2(f"Action Items ({len(items)})"))
        for item in items:
            label = item.get("task", "")
            if item.get("owner") and item["owner"] != "Unassigned":
                label += f" — {item['owner']}"
            if item.get("due") and item["due"] != "TBD":
                label += f" (due {item['due']})"
            blocks.append(_todo(label, checked=bool(item.get("completed"))))
        blocks.append(_divider())

    decisions = result.get("decisions") or []
    if decisions:
        blocks.append(_h2("Decisions"))
        importance_map = {1: "Critical", 2: "Significant", 3: "Minor"}
        for decision in sorted(decisions, key=lambda value: value.get("importance", 3)):
            label = decision.get("decision", "")
            importance = importance_map.get(decision.get("importance"), "")
            if importance:
                label += f" [{importance}]"
            if decision.get("owner"):
                label += f" — {decision['owner']}"
            blocks.append(_bullet(label))
        blocks.append(_divider())

    email = result.get("follow_up_email") or {}
    if email.get("subject") or email.get("body"):
        blocks.append(_h2("Follow-up Email"))
        if email.get("subject"):
            blocks.append(_para(f"Subject: {email['subject']}"))
        if email.get("body"):
            blocks.append(_para(email["body"]))
        blocks.append(_divider())

    calendar = result.get("calendar_suggestion") or {}
    if calendar.get("reason"):
        blocks.append(_h2("Calendar Suggestion"))
        blocks.append(_para(calendar["reason"]))
        if calendar.get("suggested_timeframe"):
            blocks.append(_para(f"Suggested timeframe: {calendar['suggested_timeframe']}"))
        if calendar.get("resolved_day") or calendar.get("resolved_date"):
            resolved = ", ".join(value for value in [calendar.get("resolved_day"), calendar.get("resolved_date")] if value)
            blocks.append(_para(f"Resolved follow-up date: {resolved}"))

    return blocks


@router.post("/export/notion")
async def export_to_notion(req: NotionExportRequest):
    parent_id = req.parent_page_id.strip()
    match = re.search(r"([0-9a-f]{32})(?:[?#]|$)", parent_id.replace("-", ""), re.IGNORECASE)
    if not match:
        raise HTTPException(status_code=400, detail="Could not extract a valid Notion page ID from the URL")
    raw = match.group(1)
    parent_id = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"

    payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": req.title or "Meeting Analysis"}}]}
        },
        "children": _build_notion_blocks(req.result)[:100],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.notion.com/v1/pages",
            headers={
                "Authorization": f"Bearer {req.token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20.0,
        )

    if resp.status_code not in (200, 201):
        detail = _safe_json(resp).get("message", "Notion API error") if resp.content else "Notion API error"
        raise HTTPException(status_code=resp.status_code, detail=detail)

    page = _safe_json(resp)
    return {"url": page.get("url", ""), "page_id": page.get("id", "")}


@router.post("/export/slack")
async def export_to_slack(req: SlackExportRequest):
    result = req.result
    health = result.get("health_score") or {}
    items = result.get("action_items") or []
    decisions = result.get("decisions") or []

    score_str = f"{health['score']}/100" if health.get("score") is not None else "N/A"
    verdict = health.get("verdict", "")

    lines = [f"*{req.title}* — PrismAI Analysis"]
    lines.append(f"*Health Score:* {score_str}{(' — ' + verdict) if verdict else ''}")

    if result.get("summary"):
        lines.append(f"\n*Summary*\n{result['summary']}")

    if items:
        lines.append(f"\n*Action Items ({len(items)})*")
        for item in items[:8]:
            owner = f" ({item['owner']})" if item.get("owner") and item["owner"] != "Unassigned" else ""
            due = f" — due {item['due']}" if item.get("due") and item["due"] != "TBD" else ""
            lines.append(f"• {item.get('task', '')}{owner}{due}")

    if decisions:
        lines.append("\n*Key Decisions*")
        for decision in decisions[:5]:
            lines.append(f"• {decision.get('decision', '')}")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            req.webhook_url,
            json={"text": "\n".join(lines)},
            timeout=10.0,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Slack webhook failed")

    return {"ok": True}
