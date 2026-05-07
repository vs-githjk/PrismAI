from collections import defaultdict
from datetime import UTC, datetime
import re

try:
    from auth import supabase
except ImportError:
    supabase = None


STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "will", "into", "your",
    "their", "about", "after", "before", "need", "needs", "next", "then", "than", "just",
    "more", "less", "team", "meeting", "meetings", "owner", "owners", "task", "tasks",
    "action", "actions", "decision", "decisions", "update", "draft", "send", "review",
    "schedule", "timeline", "launch", "project", "follow", "email", "calendar", "high",
    "low", "ready", "work", "works", "done", "doing", "look", "looks", "through",
    "across", "still", "again", "there", "where", "what", "when", "been", "being",
    "they", "them", "were", "make", "made", "gets", "getting", "into", "onto", "over",
    "under", "today", "tomorrow", "yesterday", "week", "weeks", "month", "months",
}

BLOCKER_KEYWORDS = [
    "blocked", "blocker", "delay", "delayed", "risk", "risky", "concern", "concerns",
    "worried", "worry", "issue", "issues", "stuck", "slip", "slipping", "outage",
    "degraded", "preventable", "missed", "overcommit", "overcommitting", "dependency",
]


def normalize_word(word: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", (word or "").lower()).strip()


def extract_significant_terms(text: str, minimum_length: int = 4) -> list[str]:
    return [
        word
        for word in (normalize_word(token) for token in (text or "").split())
        if len(word) >= minimum_length and word not in STOP_WORDS
    ]


def looks_like_blocker(text: str) -> bool:
    value = (text or "").lower()
    return any(keyword in value for keyword in BLOCKER_KEYWORDS)


def build_blocker_snippet(text: str) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return ""
    return f"{clean[:85].rstrip()}..." if len(clean) > 88 else clean


def build_decision_key(text: str) -> str:
    return " ".join(extract_significant_terms(text, 4)[:3])


def has_meaningful_result(result: dict | None) -> bool:
    if not result or not isinstance(result, dict):
        return False
    if isinstance(result.get("summary"), str) and result["summary"].strip():
        return True
    if isinstance(result.get("action_items"), list) and len(result["action_items"]) > 0:
        return True
    if isinstance(result.get("decisions"), list) and len(result["decisions"]) > 0:
        return True
    health = result.get("health_score") or {}
    if health.get("verdict"):
        return True
    if (health.get("score") or 0) > 0:
        return True
    sentiment = result.get("sentiment") or {}
    if sentiment.get("notes"):
        return True
    follow_up = result.get("follow_up_email") or {}
    if follow_up.get("subject") or follow_up.get("body"):
        return True
    calendar = result.get("calendar_suggestion") or {}
    if calendar.get("recommended") or calendar.get("reason"):
        return True
    return False


def derive_cross_meeting_insights(history: list[dict], user_id: str | None = None) -> dict:
    meetings = sorted(
        [entry for entry in history if has_meaningful_result(entry.get("result"))],
        key=lambda entry: entry.get("date") or "",
        reverse=True,
    )

    scored_meetings = [
        entry for entry in meetings
        if entry.get("result", {}).get("health_score", {}).get("score") is not None
    ]
    latest_score = scored_meetings[0]["result"]["health_score"]["score"] if scored_meetings else None
    oldest_score = scored_meetings[-1]["result"]["health_score"]["score"] if scored_meetings else None
    avg_score = round(sum(entry["result"]["health_score"]["score"] for entry in scored_meetings) / len(scored_meetings)) if scored_meetings else None
    score_delta = (latest_score - oldest_score) if latest_score is not None and oldest_score is not None else None

    owner_counts = defaultdict(int)
    owner_meeting_ids = defaultdict(set)
    theme_counts = defaultdict(int)
    decision_theme_counts = defaultdict(int)
    decision_theme_meeting_ids = defaultdict(set)
    decision_groups = defaultdict(list)
    blocker_counts = defaultdict(int)
    blocker_meeting_ids = defaultdict(set)
    hygiene_meetings = []
    decision_memory = []
    tense_meetings = 0

    for entry in meetings:
        result = entry.get("result", {}) or {}
        items = result.get("action_items") or []
        decisions = result.get("decisions") or []
        sentiment = result.get("sentiment") or {}

        if (sentiment.get("overall") or "").lower() in {"tense", "unresolved", "conflicted"}:
            tense_meetings += 1

        for item in items:
            owner = (item.get("owner") or "").strip()
            if owner:
                owner_counts[owner] += 1
                owner_meeting_ids[owner].add(entry["id"])

            text = f'{item.get("task", "")} {item.get("owner", "")} {item.get("due", "")}'
            for word in extract_significant_terms(text):
                theme_counts[word] += 1

            if looks_like_blocker(item.get("task", "")):
                snippet = build_blocker_snippet(item.get("task", ""))
                if snippet:
                    blocker_counts[snippet] += 1
                    blocker_meeting_ids[snippet].add(entry["id"])

        missing_owner_items = [item for item in items if not (item.get("owner") or "").strip()]
        missing_due_items = [item for item in items if not (item.get("due") or "").strip()]
        if missing_owner_items or missing_due_items:
            hygiene_meetings.append({
                "meeting_id": entry["id"],
                "missing_owners": len(missing_owner_items),
                "missing_due_dates": len(missing_due_items),
            })

        for decision in decisions:
            text = decision.get("decision", "")
            decision_terms = extract_significant_terms(text)
            decision_key = build_decision_key(text)

            for word in decision_terms:
                theme_counts[word] += 1
                decision_theme_counts[word] += 1
                decision_theme_meeting_ids[word].add(entry["id"])

            decision_entry = {
                "id": f'{entry["id"]}-{text}',
                "meeting_id": entry["id"],
                "title": text or "Decision recorded",
                "owner": decision.get("owner", "") or "",
                "importance": int(decision.get("importance", 3) or 3),
                "date": entry.get("date"),
            }
            decision_memory.append(decision_entry)

            if decision_key:
                decision_groups[decision_key].append(decision_entry)

        summary_text = result.get("summary") or ""
        for word in extract_significant_terms(summary_text, 5):
            theme_counts[word] += 1

        for candidate in (summary_text, sentiment.get("notes") or ""):
            if looks_like_blocker(candidate):
                snippet = build_blocker_snippet(candidate)
                if snippet:
                    blocker_counts[snippet] += 1
                    blocker_meeting_ids[snippet].add(entry["id"])

    top_owners = [
        {"owner": owner, "count": count, "meeting_ids": sorted(owner_meeting_ids[owner], reverse=True)}
        for owner, count in sorted(owner_counts.items(), key=lambda item: item[1], reverse=True)[:3]
    ]

    ownership_drift = [
        {
            "owner": owner,
            "count": count,
            "meetings": len(owner_meeting_ids[owner]),
            "meeting_ids": sorted(owner_meeting_ids[owner], reverse=True),
        }
        for owner, count in sorted(owner_counts.items(), key=lambda item: (-item[1], -len(owner_meeting_ids[item[0]])))
        if count >= 3 or len(owner_meeting_ids[owner]) >= 2
    ][:3]

    recurring_themes = [
        {"theme": theme, "count": count}
        for theme, count in sorted(theme_counts.items(), key=lambda item: item[1], reverse=True)[:4]
    ]

    recurring_blockers = [
        {
            "snippet": snippet,
            "count": count,
            "meeting_ids": sorted(blocker_meeting_ids[snippet], reverse=True),
        }
        for snippet, count in sorted(blocker_counts.items(), key=lambda item: item[1], reverse=True)[:3]
    ]

    resurfacing_decision_themes = [
        {
            "theme": theme,
            "count": count,
            "meeting_ids": sorted(decision_theme_meeting_ids[theme], reverse=True),
        }
        for theme, count in sorted(decision_theme_counts.items(), key=lambda item: item[1], reverse=True)
        if count > 1
    ][:3]

    # Sort by importance ascending (1=Critical first), then by date descending (newest first).
    # Negate the date integer so a later date sorts earlier within the same importance tier.
    recent_decisions = sorted(
        decision_memory,
        key=lambda item: (
            item["importance"],
            -(int(re.sub(r"[^0-9]", "", item["date"] or "00000000")[:8] or "0")),
        ),
    )[:4]

    unresolved_decisions = []
    for key, group in decision_groups.items():
        meeting_ids = []
        seen = set()
        for decision in sorted(group, key=lambda item: item["date"] or "", reverse=True):
            if decision["meeting_id"] not in seen:
                meeting_ids.append(decision["meeting_id"])
                seen.add(decision["meeting_id"])
        if len(meeting_ids) > 1:
            latest = sorted(group, key=lambda item: item["date"] or "", reverse=True)[0]
            unresolved_decisions.append({
                "key": key,
                "count": len(meeting_ids),
                "latest_title": latest["title"],
                "latest_owner": latest["owner"],
                "meeting_ids": meeting_ids[:5],
            })
    unresolved_decisions.sort(key=lambda item: item["count"], reverse=True)
    unresolved_decisions = unresolved_decisions[:3]

    recurring_hygiene_issues = sorted(
        hygiene_meetings,
        key=lambda item: item["missing_owners"] + item["missing_due_dates"],
        reverse=True,
    )[:4]

    recommended_actions = []
    if recurring_blockers:
        blocker = recurring_blockers[0]
        recommended_actions.append({
            "id": "review-blockers",
            "title": "Review recurring blockers",
            "description": f'Open the meetings behind "{blocker["snippet"]}" and decide on one unblock owner.',
            "kind": "blocker",
            "meeting_ids": blocker["meeting_ids"],
        })
    if ownership_drift:
        owner = ownership_drift[0]
        recommended_actions.append({
            "id": "rebalance-ownership",
            "title": "Rebalance ownership load",
            "description": f'{owner["owner"]} is carrying {owner["count"]} action items across {owner["meetings"]} meetings.',
            "kind": "ownership",
            "meeting_ids": owner["meeting_ids"],
        })
    if recurring_hygiene_issues:
        issue = recurring_hygiene_issues[0]
        recommended_actions.append({
            "id": "tighten-action-hygiene",
            "title": "Tighten action-item hygiene",
            "description": f'Meeting {issue["meeting_id"]} has missing owners or due dates that will weaken follow-through.',
            "kind": "hygiene",
            "meeting_ids": [issue["meeting_id"]],
        })
    if unresolved_decisions:
        decision = unresolved_decisions[0]
        recommended_actions.append({
            "id": "close-decision-loop",
            "title": "Close a resurfacing decision loop",
            "description": f'"{decision["latest_title"]}" has resurfaced across {decision["count"]} meetings.',
            "kind": "decision",
            "meeting_ids": decision["meeting_ids"],
        })

    unresolved_action_refs: list[dict] = []
    if supabase and user_id:
        try:
            refs = (
                supabase.table("action_refs")
                .select("id,action_item,tool,external_id,created_at")
                .eq("user_id", user_id)
                .eq("resolved", False)
                .order("created_at", desc=True)
                .limit(10)
                .execute()
            )
            unresolved_action_refs = refs.data or []
        except Exception:
            pass

    return {
        "meeting_count": len(meetings),
        "avg_score": avg_score,
        "latest_score": latest_score,
        "score_delta": score_delta,
        "tense_meetings": tense_meetings,
        "top_owners": top_owners,
        "ownership_drift": ownership_drift,
        "recurring_themes": recurring_themes,
        "recurring_blockers": recurring_blockers,
        "recurring_hygiene_issues": recurring_hygiene_issues,
        "resurfacing_decision_themes": resurfacing_decision_themes,
        "unresolved_decisions": unresolved_decisions,
        "recent_decisions": recent_decisions,
        "recommended_actions": recommended_actions,
        "unresolved_action_refs": unresolved_action_refs,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
