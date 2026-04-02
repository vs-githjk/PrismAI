# PrismAI — LLM Handoff Document

> Written for an LLM picking up development. Read this before touching any code.

---

## What Is PrismAI

A meeting intelligence web app. User pastes a transcript, uploads audio, records live, or connects a bot to a live Zoom/Meet/Teams call. The transcript is routed to 7 parallel AI agents (LLaMA 3.3-70b via Groq) each producing a different output card. The name "Prism" is intentional — white light (raw transcript) enters the prism (orchestrator) and splits into 7 colors (agents).

**Live URLs:**
- Frontend: GitHub Pages (`https://vs-githjk.github.io/Agentic-Meeting-Copilot/`)
- Backend: Render.com (`https://meeting-copilot-api.onrender.com`)

> Note: The Render service is named `meeting-copilot-api` — this is the real URL. The display name in the Render dashboard was changed to `agentic-meeting-copilot` but the URL did not change (Render locks URLs to creation-time name).

---

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React 18 + Vite + Tailwind CSS |
| Backend | FastAPI + uvicorn (Python 3.11) |
| AI | Groq API — LLaMA 3.3-70b (agents/chat) + Whisper large-v3 (transcription) |
| Meeting Bot | Recall.ai (joins live calls, records, returns transcript) |
| Database | Supabase (Postgres) — meetings + chats persistent storage |
| Frontend Hosting | GitHub Pages via GitHub Actions |
| Backend Hosting | Render.com free tier |

---

## File Structure

```
/
├── backend/
│   ├── main.py                    # FastAPI app — all endpoints, AGENT_MAP, DEFAULT_RESULT
│   ├── agents/
│   │   ├── orchestrator.py        # Decides which agents to run
│   │   ├── summarizer.py
│   │   ├── action_items.py
│   │   ├── decisions.py
│   │   ├── sentiment.py
│   │   ├── email_drafter.py
│   │   ├── calendar_suggester.py
│   │   └── health_score.py
│   ├── requirements.txt
│   └── .env.example               # Template: GROQ_API_KEY, RECALL_API_KEY, WEBHOOK_BASE_URL, SUPABASE_URL, SUPABASE_KEY
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # Root: layout, input, result rendering, history, speaker modal, share
│   │   ├── index.css              # Tailwind + custom animations
│   │   └── components/
│   │       ├── ChatPanel.jsx      # Chat interface + agent intent detection + chat history
│   │       ├── AgentTags.jsx      # Badges showing which agents ran
│   │       ├── HealthScoreCard.jsx
│   │       ├── SummaryCard.jsx
│   │       ├── ActionItemsCard.jsx  # Checkboxes persist to Supabase via PATCH /meetings/{id}
│   │       ├── DecisionsCard.jsx
│   │       ├── SentimentCard.jsx
│   │       ├── EmailCard.jsx
│   │       └── CalendarCard.jsx
│   └── vite.config.js             # base: '/Agentic-Meeting-Copilot/'
├── .github/workflows/deploy.yml   # Push to main → build frontend → GitHub Pages
├── render.yaml                    # Render.com backend config (service name: meeting-copilot-api)
└── PRISM_AI_CONTEXT.md            # This file
```

---

## The 7 Agents (ROYGBIV)

| Color | Agent | Runs | Output Key | Shape |
|---|---|---|---|---|
| 🔴 Red | `summarizer` | Always | `summary` | `string` |
| 🟠 Orange | `action_items` | Always | `action_items` | `[{ task, owner, due, completed }]` |
| 🟡 Yellow | `decisions` | Always | `decisions` | `[{ decision, owner, importance: 1-3 }]` |
| 🟢 Green | `sentiment` | Only if tension/conflict | `sentiment` | `{ overall, score, arc, notes, speakers:[{name,tone,score}], tension_moments:[] }` |
| 🔵 Blue | `email_drafter` | Always | `follow_up_email` | `{ subject, body }` |
| 🟣 Indigo | `calendar_suggester` | Only if follow-up discussed | `calendar_suggestion` | `{ recommended, reason, suggested_timeframe }` |
| 💜 Violet | `health_score` | Always | `health_score` | `{ score, verdict, badges:[], breakdown:{clarity,action_orientation,engagement} }` |

Note: `action_items` now includes a `completed` boolean field that persists via PATCH /meetings/{id}.

---

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe |
| POST | `/analyze` | `{ transcript, speakers? }` → full result object (non-streaming) |
| POST | `/analyze-stream` | `{ transcript, speakers? }` → SSE stream, one event per agent as it completes |
| POST | `/transcribe` | `multipart/form-data: file` → `{ transcript }` via Whisper |
| POST | `/join-meeting` | `{ meeting_url }` → `{ bot_id, status }` |
| GET | `/bot-status/{bot_id}` | Poll bot lifecycle status |
| POST | `/recall-webhook` | Recall.ai sends bot events here |
| POST | `/agent` | `{ agent, transcript, instruction }` → single agent output |
| POST | `/chat` | `{ message, transcript }` → `{ response }` |
| GET | `/meetings` | List meetings (optional `?q=` search by title) |
| POST | `/meetings` | Save/upsert a meeting |
| PATCH | `/meetings/{id}` | Update meeting result (used for action item checkbox state) |
| DELETE | `/meetings/{id}` | Delete meeting (cascades to chats in DB) |
| GET | `/share/{token}` | Public read-only meeting result by share token |
| GET | `/chats` | All chats as `{ meeting_id: messages[] }` map (bulk, avoids N+1) |
| GET | `/chats/{meeting_id}` | Single chat messages |
| POST | `/chats/{meeting_id}` | Save/upsert chat messages |
| DELETE | `/chats/{meeting_id}` | Delete chat for a meeting |

---

## Supabase Schema

```sql
create table meetings (
  id bigint primary key,           -- Date.now() from frontend
  date text not null,
  title text,
  score int,
  transcript text,
  result jsonb,
  share_token text unique,         -- 16-char hex, generated on save
  created_at timestamptz default now()
);

create table chats (
  id bigserial primary key,
  meeting_id bigint references meetings(id) on delete cascade,
  messages jsonb not null default '[]',
  updated_at timestamptz default now()
);
```

`on delete cascade` means deleting a meeting automatically deletes its chat — no extra frontend call needed.

---

## Speaker Identification

Before analysis runs, `extractSpeakers()` in App.jsx scans the transcript for `Name:` patterns and pre-fills a modal. User assigns roles (e.g. "Engineering Lead"). On Analyze, the backend prepends:

```
Meeting participants:
  - Sarah: Engineering Lead
  - Mike: Product Manager
```

...to the transcript before any agent sees it. All 7 agents benefit automatically. If no names are detected, the modal is skipped entirely.

---

## Streaming Analysis

The frontend calls `POST /analyze-stream` (not `/analyze`). The backend uses SSE + `asyncio.wait(FIRST_COMPLETED)` — each agent streams its result the moment it finishes. Frontend reads the stream chunk by chunk, calling `setResult(prev => ({ ...prev, ...chunk }))` so cards appear one by one. `saveToHistory` is called on `[DONE]`.

SSE event format:
```
data: {"agents_run": ["summarizer", "action_items", ...]}
data: {"agent": "summarizer", "summary": "..."}
data: {"agent": "action_items", "action_items": [...]}
data: [DONE]
```

---

## Shareable Links

When a meeting is saved, a `share_token` (16-char hex via `crypto.randomUUID()`) is generated and stored with the meeting. A **Share** button appears in the results header — clicking it copies:

```
https://vs-githjk.github.io/Agentic-Meeting-Copilot/#share/{token}
```

On page load, App.jsx checks `window.location.hash` for `#share/{token}`. If matched, it fetches `GET /share/{token}` and renders a read-only view with all 7 cards. No router needed — hash-based routing works on GitHub Pages.

---

## Chat System

`ChatPanel.jsx` has two modes:

1. **Regular chat** → `POST /chat` with message + transcript → LLM answers
2. **Agent intent** → detected via regex in `detectAgentIntent()`. If matched, calls `POST /agent` with the instruction appended to the transcript.

**History dropdown:** Shows past meeting chats. Clicking one enters "viewing mode" — a blue banner with "← Back to current chat". While viewing, input is enabled and uses that meeting's transcript. New messages are saved back to that session. Agent re-run intents are disabled in viewing mode (no live cards to update).

**Deleting a chat session** in the dropdown only removes the chat — the meeting is preserved.

**Chat persistence:** Messages saved to `POST /chats/{meetingId}` on every state change.

---

## Persistent State

| What | Where | Notes |
|---|---|---|
| Meeting history | Supabase `meetings` table | No cap, survives browser clears |
| Chat per meeting | Supabase `chats` table | Cascade-deleted with meeting |
| Action item completion | Inside `result` JSON in `meetings` table | Patched via PATCH /meetings/{id} |
| Bot status during call | `bot_store: dict` (in-memory) | Lost on Render restart |
| Share token | `meetings.share_token` column | Generated at save time |

On startup, App.jsx fetches `/meetings` and auto-loads the most recent meeting (transcript + result + chat).

---

## Environment Variables

| Var | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Yes | All LLM calls + Whisper transcription |
| `RECALL_API_KEY` | Yes (bot feature only) | Recall.ai meeting bot |
| `WEBHOOK_BASE_URL` | Yes (bot feature only) | Callback URL for Recall webhooks |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY` | Yes | Supabase service_role key (bypasses RLS) |
| `VITE_API_URL` | Frontend build only | Points frontend at backend (GitHub secret) |

---

## Deployment

**Frontend:** Any push to `main` triggers `.github/workflows/deploy.yml`:
- `npm ci` → `npm run build` (with `VITE_API_URL` secret) → upload to GitHub Pages

**Backend:** Render.com auto-deploys from `render.yaml` on push to `main`.
- Free tier spins down after inactivity → cold start can take 30-60s
- `SUPABASE_URL` and `SUPABASE_KEY` must be set manually in Render dashboard (not in render.yaml)

---

## Known Issues / Watch Out For

- **Render free tier sleeps** — first request after inactivity will be slow. Not a bug.
- **Bot store is in-memory** — if Render restarts mid-meeting, `bot_store` is lost. Needs persistent storage to fix properly.
- **Sentiment is conditional** — won't appear for neutral/positive meetings by design.
- **`decisions` importance ranking** — 1 = critical, 2 = significant, 3 = minor. Sorted ascending in `DecisionsCard.jsx`.
- **Share button only appears after analysis** — `shareToken` state is null until a meeting is saved. Loading from history restores the token.
- **SSE and Render free tier** — streaming works but Render free tier may buffer SSE. `X-Accel-Buffering: no` header is set to mitigate.

---

## Remaining Roadmap (in order)

### Next up
**UI polish pass** — general visual improvements, mobile responsiveness, loading states for streaming.

### Then
**6. Recurring meeting comparison** — "How does this week's standup compare to last week's?" Track health score trends per meeting series. Requires a `series` concept on meetings.

**7. Model fallback** — If Groq is rate-limited or down, fall back to a secondary provider (OpenAI or Anthropic) in each agent's `run()` function.

**8. Team dashboard** — Aggregate health scores, decision velocity, action item completion across meetings. Needs auth.

---

## Agent Code Pattern (for reference)

Every agent follows this exact structure:

```python
import json, os
from groq import AsyncGroq
from fastapi import HTTPException

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    "You are a ___. ..."
    'Return ONLY valid JSON: { "key": ... }. '
    "If the transcript contains a [User instruction: ...] line, follow it exactly."  # only if re-runnable via chat
)

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines).strip()
    return text

async def run(transcript: str) -> dict:
    for attempt in range(2):
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript:\n{transcript}"},
            ],
        )
        raw = response.choices[0].message.content
        try:
            return json.loads(_strip_fences(raw))
        except json.JSONDecodeError:
            if attempt == 1:
                raise HTTPException(status_code=500, detail="agentname: failed to parse JSON after retry")
    return {"key": default_value}
```

### Adding a New Agent — Checklist

1. Create `backend/agents/yourname.py` — follow the pattern above
2. Import it in `backend/main.py`
3. Add to `AGENT_MAP` and `AGENT_RESULT_KEY` in `main.py`
4. Add default value to `DEFAULT_RESULT` in `main.py` (and mirror in `frontend/src/App.jsx`)
5. Add to both result-builder loops in `main.py` (~lines 88 and ~294)
6. Add to `ALL_AGENTS` list in `orchestrator.py`
7. Add guardrail in `orchestrator.py` if it should always run
8. Add to `AGENTS_META` in `App.jsx` with icon + gradient
9. Add to `AGENT_CONFIG` in `AgentTags.jsx` with ROYGBIV color
10. Create `YournameCard.jsx` in `frontend/src/components/`
11. Import and place card in `App.jsx` (both desktop and mobile layouts)
