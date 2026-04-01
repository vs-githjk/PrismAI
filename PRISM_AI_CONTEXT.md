# PrismAI — LLM Handoff Document

> Written for an LLM picking up development. Read this before touching any code.

---

## What Is PrismAI

A meeting intelligence web app. User pastes a transcript, uploads audio, records live, or connects a bot to a live Zoom/Meet/Teams call. The transcript is routed to 7 parallel AI agents (LLaMA 3.3-70b via Groq) each producing a different output card. The name "Prism" is intentional — white light (raw transcript) enters the prism (orchestrator) and splits into 7 colors (agents).

**Live URLs:**
- Frontend: GitHub Pages (`https://vs-githjk.github.io/Agentic-Meeting-Copilot/`)
- Backend: Render.com (`https://agentic-meeting-copilot.onrender.com`)

---

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React 18 + Vite + Tailwind CSS |
| Backend | FastAPI + uvicorn (Python 3.11) |
| AI | Groq API — LLaMA 3.3-70b (agents/chat) + Whisper large-v3 (transcription) |
| Meeting Bot | Recall.ai (joins live calls, records, returns transcript) |
| Frontend Hosting | GitHub Pages via GitHub Actions |
| Backend Hosting | Render.com free tier |
| Storage | In-memory only (no DB) + localStorage for history |

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
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # Root: layout, input, result rendering, history
│   │   ├── index.css              # Tailwind + custom animations
│   │   └── components/
│   │       ├── ChatPanel.jsx      # Chat interface + agent intent detection + chat history
│   │       ├── AgentTags.jsx      # Badges showing which agents ran
│   │       ├── HealthScoreCard.jsx
│   │       ├── SummaryCard.jsx
│   │       ├── ActionItemsCard.jsx
│   │       ├── DecisionsCard.jsx
│   │       ├── SentimentCard.jsx
│   │       ├── EmailCard.jsx
│   │       └── CalendarCard.jsx
│   └── vite.config.js             # base: '/Agentic-Meeting-Copilot/'
├── .github/workflows/deploy.yml   # Push to main → build frontend → GitHub Pages
├── render.yaml                    # Render.com backend config
└── PRISM_AI_CONTEXT.md            # This file
```

---

## The 7 Agents (ROYGBIV)

| Color | Agent | Runs | Output Key | Shape |
|---|---|---|---|---|
| 🔴 Red | `summarizer` | Always | `summary` | `string` |
| 🟠 Orange | `action_items` | Always | `action_items` | `[{ task, owner, due }]` |
| 🟡 Yellow | `decisions` | Always | `decisions` | `[{ decision, owner, importance: 1-3 }]` |
| 🟢 Green | `sentiment` | Only if tension/conflict | `sentiment` | `{ overall, score, arc, notes, speakers:[{name,tone,score}], tension_moments:[] }` |
| 🔵 Blue | `email_drafter` | Always | `follow_up_email` | `{ subject, body }` |
| 🟣 Indigo | `calendar_suggester` | Only if follow-up discussed | `calendar_suggestion` | `{ recommended, reason, suggested_timeframe }` |
| 💜 Violet | `health_score` | Always | `health_score` | `{ score, verdict, badges:[], breakdown:{clarity,action_orientation,engagement} }` |

White = orchestrator/input (before the prism splits it).

### DEFAULT_RESULT (in main.py)

```python
{
  "summary": "",
  "action_items": [],
  "decisions": [],
  "sentiment": { "overall": "neutral", "score": 50, "arc": "stable", "notes": "", "speakers": [], "tension_moments": [] },
  "follow_up_email": { "subject": "", "body": "" },
  "calendar_suggestion": { "recommended": False, "reason": "", "suggested_timeframe": "" },
  "health_score": { "score": 0, "verdict": "", "badges": [], "breakdown": { "clarity": 0, "action_orientation": 0, "engagement": 0 } },
  "agents_run": []
}
```

### Adding a New Agent — Checklist

1. Create `backend/agents/yourname.py` — follow the same `_strip_fences` + `for attempt in range(2)` retry pattern
2. Import it in `backend/main.py`
3. Add to `AGENT_MAP` in `main.py`
4. Add default value to `DEFAULT_RESULT` in `main.py`
5. Add `elif agent_name == "yourname":` to **both** result-builder loops in `main.py` (lines ~88 and ~294)
6. Add to `ALL_AGENTS` list in `orchestrator.py`
7. Add guardrail in `orchestrator.py` if it should always run
8. Add to `AGENTS_META` in `App.jsx` with icon + gradient
9. Add to `AGENT_CONFIG` in `AgentTags.jsx` with ROYGBIV color
10. Create `YournameCard.jsx` in `frontend/src/components/`
11. Import and place card in `App.jsx` (both desktop and mobile layouts)

---

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe |
| POST | `/analyze` | `{ transcript }` → full result object |
| POST | `/transcribe` | `multipart/form-data: file` → `{ transcript }` via Whisper |
| POST | `/join-meeting` | `{ meeting_url }` → `{ bot_id, status }` |
| GET | `/bot-status/{bot_id}` | Poll bot lifecycle status |
| POST | `/recall-webhook` | Recall.ai sends bot events here |
| POST | `/agent` | `{ agent, transcript, instruction }` → single agent output |
| POST | `/chat` | `{ message, transcript }` → `{ response }` |

---

## Data Flow

```
User input (transcript text / audio / live meeting)
  ↓
POST /analyze
  ↓
orchestrator.run_orchestrator(transcript)
  → LLM decides agent list (always: summarizer, action_items, decisions, email_drafter, health_score)
  ↓
asyncio.gather(*all_selected_agents) — all run IN PARALLEL
  ↓
Merge into DEFAULT_RESULT
  ↓
Return JSON to frontend
  ↓
React renders cards (each card returns null if its data is empty/missing)
  ↓
Save to localStorage as meeting history entry
```

### Bot Meeting Flow (Recall.ai)

```
POST /join-meeting → Recall.ai creates bot → returns bot_id
  ↓
Frontend polls GET /bot-status/{bot_id} every 4s
  ↓
Recall.ai sends webhook events → /recall-webhook updates bot_store
  ↓
On call_ended: _process_bot_transcript fires
  → waits 5s, retries up to 5 times with backoff (Recall needs time to finish)
  → fetches [{ speaker, words:[{text}] }], formats as "Speaker: text\n..."
  → runs full agent pipeline
  ↓
Frontend detects status="done", loads result, clears transcript input
```

---

## Chat & Agent Re-running

`ChatPanel.jsx` has two modes:

1. **Regular chat** → `POST /chat` with message + transcript → LLM answers
2. **Agent intent** → detected via regex in `detectAgentIntent()`. If matched, calls `POST /agent` with the instruction appended to the transcript as `[User instruction: ...]`. The agent's system prompt tells it to honour this instruction.

Agents that honour user instructions: `email_drafter`, `calendar_suggester` (others can be triggered but ignore tone/style changes unless their system prompt says otherwise).

Covered agents in intent detection:
- "redraft/rewrite email" → `email_drafter`
- "redo action items" → `action_items`
- "rewrite summary" → `summarizer`
- "change calendar/date" → `calendar_suggester`
- "redo decisions" → `decisions`
- "reanalyze sentiment/tone" → `sentiment`
- "rerun health score" → `health_score`

---

## Persistent State

| What | Where | Limit |
|---|---|---|
| Meeting history | `localStorage['meeting-history']` | 8 entries |
| Chat per meeting | `localStorage['chat-{meetingId}']` | Unbounded |
| Bot status during call | `bot_store: dict` (in-memory, lost on restart) | N/A |

---

## Environment Variables

| Var | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Yes | All LLM calls + Whisper transcription |
| `RECALL_API_KEY` | Yes (bot feature only) | Recall.ai meeting bot |
| `WEBHOOK_BASE_URL` | Yes (bot feature only) | Callback URL for Recall webhooks |
| `VITE_API_URL` | Frontend build only | Points frontend at backend (set as GitHub secret) |

---

## Deployment

**Frontend:** Any push to `main` triggers `.github/workflows/deploy.yml`:
- `npm ci` → `npm run build` (with `VITE_API_URL` secret) → upload to GitHub Pages

**Backend:** Render.com auto-deploys from `render.yaml` on push to `main`.
- Free tier spins down after inactivity → cold start can take 30-60s
- Known issue: first deploy attempt sometimes gets a port scan timeout (Render race condition) — a second push usually resolves it

---

## UI Patterns

- **Empty state:** Grid of 7 agent cards. Tap any card to reveal a description of what that agent does.
- **Loading state:** `AgentPipelineLoader` — orchestrator icon (white) → "dispatching 7 agents" → animated 4-col agent grid
- **Results:** Right panel. Desktop: cards in a 2-col grid. Mobile: stacked below input.
- **Chat history:** Button in ChatPanel header. Dropdown shows past chats with meeting title, first message preview, date.
- **New Meeting:** Clears transcript, result, and resets chat (via `sessionId` key on ChatPanel → remount)
- All result cards guard with `if (!data || !data.length) return null` — safe to render even with DEFAULT_RESULT

---

## Known Issues / Watch Out For

- **Render free tier sleeps** — first request after inactivity will be slow. Not a bug.
- **Bot store is in-memory** — if Render restarts mid-meeting, `bot_store` is lost and the bot result won't be retrievable. Needs persistent storage to fix properly.
- **Sentiment is conditional** — it won't appear for neutral/positive meetings by design. Don't treat its absence as a bug.
- **`decisions` importance ranking** — importance 1 = critical, 2 = significant, 3 = minor. Sorted ascending (most important first) in `DecisionsCard.jsx`.
- **VS Code shows red squiggles on `groq`/`fastapi` imports** — virtualenv not configured in VS Code. Works fine on Render. Safe to ignore.

---

## Future Plans (Prioritised)

### High Value / Relatively Quick

**1. Speaker identification**
Before analysis, prompt "who was in this meeting?" Map names to roles. Feed the mapping to all agents so output says "Engineering Lead" not just "Mike". Improves every card's output quality.

**2. Persistent history with search**
localStorage caps at 8 entries and gets wiped on browser clear. Move meeting history + chat history to the backend (even a JSON file or SQLite on Render). Add a search endpoint so users can find past meetings by topic, speaker, or date.

**3. Shareable results link**
Generate a read-only URL (`/share/{token}`) for a meeting analysis. Anyone with the link can view the cards but not edit. Huge for async teams — send the link instead of forwarding the email.

### Differentiation Features

**4. Recurring meeting comparison**
"How does this week's standup compare to last week's?" Track health score trends over time per meeting series. Requires persistent storage + a meeting series concept.

**5. Team dashboard**
Aggregate health scores, decision velocity, action item completion rate across all meetings. Turns PrismAI from a per-meeting tool into an org intelligence layer. Needs auth + persistent storage.

**6. Action item tracking**
Action items are currently displayed and forgotten. Add: mark complete (already has checkboxes), persist state, send reminder email via `/agent email_drafter` with due date context.

### Technical

**7. Streaming analysis**
Show result cards one-by-one as each agent finishes rather than all at once. Uses SSE or WebSocket. Makes the wait feel much shorter and makes the prism/parallel-agents metaphor more visual — you'd see each color appear.

**8. Model fallback**
If Groq is rate-limited or down, the whole app fails. Add a secondary provider (OpenAI, Anthropic) as fallback in each agent's `run()` function.

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
