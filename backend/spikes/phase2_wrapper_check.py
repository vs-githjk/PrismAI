"""Phase 2 live server-plumbing check — the acceptance gate for present_routes.

Spec: docs/specs/2026-07-07-bot-screen-presentation-design.md (Wrapper page).

Default mode (assertions, costs one short-lived real sandbox):
    cd backend && python spikes/phase2_wrapper_check.py

  1. provider.ensure_sandbox(None)                 # a real E2B sandbox
  2. mint a view_only present token
  3. mount ONLY present_routes on a bare FastAPI() and drive it with TestClient
  4. assert:
       - GET /present/{token}       -> 200 + HTML containing the token
       - GET /present/{token}/vnc   -> 200 + JSON, url is 200-reachable, resumed is a bool
       - GET /present/{bogus}       -> 410 on both routes
       - pause the sandbox, then GET /vnc -> resumed:true + a 200-reachable url
  5. kill the sandbox. Print PASS/FAIL with timings.

Serve mode (for the orchestrator's real-browser frame check — keeps the sandbox
alive and a live server up until Ctrl-C):
    cd backend && python spikes/phase2_wrapper_check.py --serve
"""

import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))  # flat imports (present_routes, sandbox, ...)

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")

import httpx  # noqa: E402  (repo dependency)
from fastapi import FastAPI  # noqa: E402

from present_routes import router as present_router  # noqa: E402
from present_tokens import mint_present_token  # noqa: E402
from sandbox import get_provider  # noqa: E402


def _app() -> FastAPI:
    app = FastAPI(title="phase2-present-check")
    app.include_router(present_router)
    return app


def _kill(ref) -> None:
    try:
        from e2b_desktop import Sandbox as DesktopSandbox

        killed = DesktopSandbox.kill(ref.sandbox_id)
        print(f"[check] killed {ref.sandbox_id} -> {killed}")
    except Exception as e:  # noqa: BLE001
        print(
            f"[check] cleanup failed for {ref.sandbox_id}: {e} — kill it at "
            f"https://e2b.dev/dashboard (auto-expires after idle timeout)"
        )


def run_assertions() -> int:
    provider = get_provider()
    ref = None
    failures = []

    def check(label, cond):
        print(f"[check] {'PASS' if cond else 'FAIL'}  {label}")
        if not cond:
            failures.append(label)

    try:
        t0 = time.perf_counter()
        ref = provider.ensure_sandbox(None)
        print(f"[check] ensure_sandbox -> {ref.sandbox_id} in {time.perf_counter()-t0:.2f}s")

        token = mint_present_token(ref, view_only=True, ttl_s=3600, bot_id="phase2-check")
        bogus = "definitely-not-a-real-token"

        from fastapi.testclient import TestClient

        with TestClient(_app()) as client:
            # --- wrapper page --------------------------------------------------
            r = client.get(f"/present/{token}")
            check("GET /present/{token} -> 200", r.status_code == 200)
            check("wrapper HTML contains the token", token in r.text)
            check("wrapper HTML is a document", "<iframe" in r.text.lower())

            # --- vnc (fresh, running) -----------------------------------------
            t0 = time.perf_counter()
            r = client.get(f"/present/{token}/vnc")
            dt = time.perf_counter() - t0
            check(f"GET /present/{{token}}/vnc -> 200 ({dt:.2f}s)", r.status_code == 200)
            data = r.json() if r.status_code == 200 else {}
            check("vnc JSON has a url", isinstance(data.get("url"), str) and bool(data.get("url")))
            check("vnc JSON resumed is a bool", isinstance(data.get("resumed"), bool))
            print(f"[check]   resumed (fresh) = {data.get('resumed')}")
            if data.get("url"):
                st = httpx.get(data["url"], timeout=10.0, follow_redirects=True).status_code
                check(f"vnc url is 200-reachable (got {st})", st == 200)

            # --- bogus token ---------------------------------------------------
            check("GET /present/{bogus} -> 410", client.get(f"/present/{bogus}").status_code == 410)
            check("GET /present/{bogus}/vnc -> 410", client.get(f"/present/{bogus}/vnc").status_code == 410)

            # --- resume-on-serve: pause then hit /vnc --------------------------
            t0 = time.perf_counter()
            provider.pause(ref)
            print(f"[check] paused {ref.sandbox_id} in {time.perf_counter()-t0:.2f}s")
            # Ground-truth probe: what does is_alive report for a PAUSED sandbox?
            try:
                print(f"[check]   is_alive(paused) = {provider.is_alive(ref)}")
            except Exception as e:  # noqa: BLE001
                print(f"[check]   is_alive(paused) raised: {e}")

            t0 = time.perf_counter()
            r = client.get(f"/present/{token}/vnc")
            dt = time.perf_counter() - t0
            check(f"post-pause /vnc -> 200 ({dt:.2f}s)", r.status_code == 200)
            data = r.json() if r.status_code == 200 else {}
            print(f"[check]   resumed (post-pause) = {data.get('resumed')}")
            check("post-pause /vnc resumed:true", data.get("resumed") is True)
            if data.get("url"):
                st = httpx.get(data["url"], timeout=10.0, follow_redirects=True).status_code
                check(f"post-pause vnc url is 200-reachable (got {st})", st == 200)

        ok = not failures
        print("\n[check] " + ("PASS — all plumbing checks green" if ok else f"FAIL — {failures}"))
        return 0 if ok else 1
    finally:
        if ref is not None:
            _kill(ref)


def run_serve() -> int:
    import uvicorn

    provider = get_provider()
    ref = provider.ensure_sandbox(None)
    token = mint_present_token(ref, view_only=True, ttl_s=7200, bot_id="phase2-serve")
    port = 8077
    print("\n" + "=" * 68)
    print("  Phase 2 wrapper is live — open this in a real browser:")
    print(f"    http://127.0.0.1:{port}/present/{token}")
    print(f"  sandbox: {ref.sandbox_id}   (Ctrl-C to stop + kill the sandbox)")
    print("=" * 68 + "\n")
    try:
        uvicorn.run(_app(), host="127.0.0.1", port=port, log_level="warning")
        return 0
    finally:
        _kill(ref)


def main() -> int:
    import os

    if not os.environ.get("E2B_API_KEY"):
        print("ERROR: E2B_API_KEY is not set — add it to backend/.env", file=sys.stderr)
        return 2
    if "--serve" in sys.argv:
        return run_serve()
    return run_assertions()


if __name__ == "__main__":
    sys.exit(main())
