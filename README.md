# PrismAI — Frontend

React + Vite single-page app. Talks to the PrismAI backend over HTTP (base URL
set via `VITE_API_URL`).

## Setup

```bash
npm install
cp .env.example .env   # then fill in the values
npm run dev            # http://localhost:5173
```

## Build

```bash
npm run build          # outputs to dist/
npm run preview        # serve the production build locally
```

## Environment

See `.env.example`. All vars are `VITE_`-prefixed and public (shipped to the
browser) — never put server secrets here. `VITE_API_URL` must point at a
running backend.
