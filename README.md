ww# Agentic Meeting Copilot

Multi-agent AI that transforms meeting transcripts into summaries, action items, sentiment analysis, follow-up emails, and calendar suggestions — powered by Groq + Llama 3.3 70B.

**[Live Demo](https://vs-githjk.github.io/Agentic-Meeting-Copilot/)**

---

## How it works

Paste a meeting transcript and a team of specialized AI agents runs in parallel to produce:

- **Summary** — concise recap of what was discussed
- **Action Items** — who owns what, with clear ownership
- **Sentiment Analysis** — overall tone and engagement score
- **Follow-up Email** — ready-to-send draft based on outcomes
- **Calendar Suggestion** — recommends a follow-up meeting if needed
- **Chat** — ask questions about the meeting in natural language

An orchestrator agent decides which agents to run based on the transcript content.

## Stack

| Layer | Tech |
|---|---|
| Frontend | React + Vite + Tailwind CSS |
| Backend | FastAPI (Python) |
| AI | Groq API — Llama 3.3 70B |
| Hosting | GitHub Pages + Render |

## Run locally

```bash
# Backend
cp backend/.env.example backend/.env   # add your GROQ_API_KEY
cd backend && pip install -r requirements.txt && uvicorn main:app --reload

# Frontend (new terminal)
cd frontend && npm install && npm run dev
```

Get a free Groq API key at https://console.groq.com
