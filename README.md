# PrismAI — Meeting Intelligence

One transcript. Seven AI agents. Instant clarity.

PrismAI transforms any meeting transcript into structured intelligence — summaries, action items, sentiment analysis, follow-up emails, calendar suggestions, and a meeting health score — powered by a multi-agent pipeline on Groq + LLaMA 3.3 70B.

Frontend is ready for deployment on Vercel. The backend remains on Render.

---

## How it works

An orchestrator LLM reads your transcript and dynamically routes it to the right specialized agents, all running in parallel:

| Agent | Output |
|---|---|
| Summarizer | Concise 2-3 sentence TL;DR |
| Action Items | Who owns what, with due dates |
| Decisions | What was actually agreed or resolved |
| Sentiment | Tone score + conflict detection |
| Email Drafter | Ready-to-send follow-up email |
| Calendar Suggester | Follow-up meeting recommendation |
| Health Score | 0-100 meeting quality score with breakdown |

Plus a **Chat** interface to ask questions about any meeting in natural language.

## Input methods

- **Paste** a transcript directly
- **Record** live audio via browser microphone (Web Speech API)
- **Upload** an audio file — transcribed via Groq Whisper large-v3

## Stack

| Layer | Tech |
|---|---|
| Frontend | React + Vite + Tailwind CSS |
| Backend | FastAPI (Python) |
| AI | Groq API — LLaMA 3.3 70B + Whisper large-v3 |
| Hosting | Vercel (frontend) + Render (backend) |

## Run locally

```bash
# Backend
cp backend/.env.example backend/.env   # add your GROQ_API_KEY
cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8001

# Frontend (new terminal)
cd frontend && npm install && npm run dev
```

Get a free Groq API key at https://console.groq.com

For the live meeting bot, local backend testing also needs a public HTTPS webhook URL for `POST /recall-webhook` and `POST /realtime-events`. Set `WEBHOOK_BASE_URL` in `backend/.env` to that public URL before using the bot flow.

## Deploy frontend to Vercel

1. Import this repo into Vercel.
2. Keep the project root at the repo root so `vercel.json` is used.
3. Add `VITE_API_URL` and point it at your Render backend, for example `https://meeting-copilot-api.onrender.com`.
4. Deploy.

The frontend no longer depends on a GitHub Pages base path, so it works cleanly on a root Vercel domain.
