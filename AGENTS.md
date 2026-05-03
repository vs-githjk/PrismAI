# Repository Guidelines

## Project Structure & Module Organization
`frontend/` contains the Vite React app. Main entry points live in `frontend/src/`, reusable UI is in `frontend/src/components/`, shared helpers are in `frontend/src/lib/`, and static files are in `frontend/public/`. `backend/` contains the FastAPI service: `main.py` wires routes, `*_routes.py` exposes endpoints, `agents/` holds analysis workers, and `tools/` contains external-service integrations. Backend tests live in `backend/tests/`. Database and integration SQL lives in `supabase/`. Design assets and reference imagery are in `assets/`.

## Build, Test, and Development Commands
Frontend:
- `cd frontend && npm ci` installs pinned dependencies.
- `cd frontend && npm run dev` starts the local Vite app.
- `cd frontend && npm run build` creates the production bundle in `frontend/dist`.

Backend:
- `cd backend && pip install -r requirements.txt` installs FastAPI and AI dependencies.
- `cd backend && uvicorn main:app --reload` runs the API locally on port 8000.
- `cd backend && python -m unittest discover -s tests -p "test_*.py"` runs the backend test suite.

## Coding Style & Naming Conventions
Follow existing style instead of reformatting unrelated files. Use 2-space indentation in the React app and 4-space indentation in Python. React components use `PascalCase` filenames such as `ActionItemsCard.jsx`; utilities and route modules use `camelCase` or descriptive snake_case by language, such as `api.js` and `analysis_routes.py`. Keep Tailwind-heavy UI code close to the component that owns it. No formatter or linter is currently enforced in repo scripts, so keep changes small and consistent.

## Testing Guidelines
Backend coverage is based on `unittest` with files named `test_*.py` under `backend/tests/`. Add or update tests whenever route behavior, auth, or agent orchestration changes. Prefer isolated tests with mocked Groq, Supabase, and network calls, matching the current suite. The frontend has no automated test harness yet; for UI changes, at minimum verify `npm run build` succeeds.

## Commit & Pull Request Guidelines
Recent history uses short imperative commit subjects such as `Add Pricing & Team sections...` and `Polish HowItWorks...`. Keep commits focused and descriptive. PRs should include a clear summary, note any env var or API changes, link the relevant issue if one exists, and attach screenshots or short clips for frontend updates. Call out any manual verification performed.

## Security & Configuration Tips
Keep secrets in local env files, not in source control. Backend expects `GROQ_API_KEY`; frontend commonly uses `VITE_API_URL`, `VITE_SUPABASE_URL`, and `VITE_SUPABASE_ANON_KEY`.
