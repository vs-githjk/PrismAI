"""SPIKE 2 — Recall.ai Output Media webpage screenshare probe.

What this proves (per docs/specs/2026-07-07-bot-screen-presentation-design.md, Step 0 #2):
  1. Ad-hoc live webpage screenshare works on an already-in-call bot:
       POST {RECALL_API_BASE}/bot/{id}/output_media/
       body: {"screenshare": {"kind": "webpage", "config": {"url": "<page>"}}}
     and stops cleanly:
       DELETE same path, body: {"screenshare": true}
     (NOT /output_screenshare/ — that endpoint is JPEG-static only.)
  2. Time-to-pixels: the script prints T_api at the POST; YOU eyeball the meeting
     and note wall-clock when pixels appear. PASS gate: <= 10 seconds.
  3. Smoothness A/B across bot variants: --variant web (default, 250 millicores,
     flagged by Recall's FAQ as often insufficient for Output Media) vs
     --variant web_4_core (the recommended upgrade, +$0.10/hr). Variant is
     CREATE-TIME-ONLY — no live upgrade — hence one bot per run, one run per variant.
  4. The failure signature when the host has locked screen-sharing (run #2, see
     instructions printed at the end) so the product code can catch it.

Conventions copied from backend/recall_routes.py (NOT imported — importing
recall_routes drags in FastAPI app wiring, supabase, realtime_routes, etc.):
  - RECALL_API_BASE  = os.getenv("RECALL_API_BASE", "https://us-west-2.recall.ai/api/v1")   [recall_routes.py:58]
  - auth header      = {"Authorization": f"Token {RECALL_API_KEY}"}                          [recall_routes.py:376]
  - bot create       = POST {base}/bot/  with meeting_url/bot_name/recording_config          [recall_routes.py:554-618, 702]
  - status poll      = GET  {base}/bot/{id}/  -> json()["status_changes"][-1]["code"]        [recall_routes.py:381-383, 1994]
  - bot removal      = POST {base}/bot/{id}/leave_call/  then DELETE {base}/bot/{id}/ as
                       fallback (DELETE only works for scheduled/unjoined bots)              [recall_routes.py:1927-1939]
The `variant` create param is NOT used anywhere in the repo yet — its per-platform
shape ({"variant": {"google_meet": "...", "zoom": "...", "microsoft_teams": "..."}})
comes from Recall's docs, and this spike is what validates it.

IMPORTANT create-payload constraint: output_media is mutually exclusive with the
automatic_video_output / automatic_audio_output create params. The production
_recall_bot_create_json attaches an automatic_video_output logo tile
(recall_routes.py:613-615) — this spike deliberately OMITS it.

Usage:
  python backend/spikes/spike2_recall_screenshare.py --meeting-url https://meet.google.com/xxx-xxxx-xxx
  python backend/spikes/spike2_recall_screenshare.py --meeting-url ... --variant web_4_core
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx  # backend/requirements.txt line 6 — already a repo dependency
except ImportError:
    print("ERROR: httpx not installed. Run:  pip install -r backend/requirements.txt")
    sys.exit(1)


# ---------------------------------------------------------------- env loading

def load_backend_env() -> None:
    """Load backend/.env (relative to this file: ../.env) without importing app code.
    Tries python-dotenv (a repo dependency) and falls back to a manual KEY=VALUE parse."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
        return
    except ImportError:
        pass
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_backend_env()

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
# Same default region host as recall_routes.py:58
RECALL_API_BASE = os.getenv("RECALL_API_BASE", "https://us-west-2.recall.ai/api/v1").rstrip("/")

HEADERS = {"Authorization": f"Token {RECALL_API_KEY}"}          # recall_routes.py:376
HEADERS_JSON = {**HEADERS, "Content-Type": "application/json"}  # recall_routes.py:703


# ------------------------------------------------------------------- helpers

def now_str() -> str:
    """Local wall-clock with millis — what the human compares against."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg: str) -> None:
    print(f"[{now_str()}] {msg}", flush=True)


def dump_response(label: str, resp: httpx.Response) -> None:
    """FULL status + body — this is how we learn catchable failure signatures."""
    print(f"----- {label}: HTTP {resp.status_code} -----")
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text or "(empty body)")
    print("-" * 45, flush=True)


def build_create_payload(meeting_url: str, variant: str) -> dict:
    """Minimal shape adapted from _recall_bot_create_json (recall_routes.py:554-618):
    keeps the recording_config core (so the bot reaches in_call_recording) but drops
    transcript provider, realtime_endpoints, webhook_url — and critically drops
    automatic_video_output (the logo tile, recall_routes.py:613-615) because it is
    mutually exclusive with output_media."""
    return {
        "meeting_url": meeting_url,
        "bot_name": f"PrismAI Spike2 ({variant})",
        "recording_config": {
            "video_mixed_layout": "speaker_view",
            "video_mixed_mp4": {},
            "audio_mixed_mp3": {},
        },
        # Per-platform variant map (Recall docs; create-time-only, not in repo yet).
        # Set on all three platforms so the spike works on whatever URL is passed.
        "variant": {
            "google_meet": variant,
            "zoom": variant,
            "microsoft_teams": variant,
        },
    }


def poll_until_in_call(client: httpx.Client, bot_id: str, timeout_s: int = 600) -> tuple[str, int]:
    """Poll GET /bot/{id}/ printing every status_changes transition with timestamps
    (both Recall's created_at and local wall clock). Returns (code we stopped on,
    count of status_changes already printed) — the caller seeds its in-hold watcher
    with that count so no transition is skipped or double-printed.
    Status-code convention from recall_routes.py:381-383 / 1994."""
    seen = 0
    deadline = time.monotonic() + timeout_s
    warned_not_recording = False
    while time.monotonic() < deadline:
        resp = client.get(f"{RECALL_API_BASE}/bot/{bot_id}/", headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            dump_response("bot status poll failed", resp)
            time.sleep(3)
            continue
        changes = resp.json().get("status_changes") or []
        for ch in changes[seen:]:
            log(f"STATUS -> {ch.get('code')}"
                f"{'  (sub_code=' + str(ch.get('sub_code')) + ')' if ch.get('sub_code') else ''}"
                f"  [recall created_at={ch.get('created_at')}]")
        seen = len(changes)
        code = changes[-1].get("code", "") if changes else ""
        if code == "in_call_recording":
            return code, seen
        if code in ("call_ended", "done", "fatal_error"):
            log(f"Bot reached terminal state '{code}' before recording — full status_changes:")
            print(json.dumps(changes, indent=2), flush=True)
            return code, seen
        if code == "in_call_not_recording" and not warned_not_recording:
            warned_not_recording = True
            log("Bot is in the call but not recording yet (normal for a few seconds; "
                "if it sticks here, check the recording_config).")
        if code in ("", "joining_call"):
            log("Waiting… if the bot is stuck in the Meet waiting room, ADMIT IT now.")
        time.sleep(2)
    return "timeout", seen


def start_screenshare(client: httpx.Client, bot_id: str, page_url: str) -> tuple[bool, str]:
    """POST /bot/{id}/output_media/ — the verified ad-hoc live-webpage endpoint.
    (Do NOT use /output_screenshare/ — that one is JPEG-static only.)
    Returns (ok, t_api string)."""
    body = {"screenshare": {"kind": "webpage", "config": {"url": page_url}}}
    t_api = now_str()
    resp = client.post(f"{RECALL_API_BASE}/bot/{bot_id}/output_media/",
                       headers=HEADERS_JSON, json=body, timeout=30)
    ok = resp.status_code in (200, 201)
    if ok:
        log(f"output_media POST accepted (HTTP {resp.status_code}).  T_api = {t_api}")
        print()
        print("  >>> PIXELS VISIBLE? note wall-clock now vs T_api=" + t_api + " <<<")
        print("  (PASS gate: pixels in the meeting <= 10s after T_api)")
        print()
    else:
        log("output_media POST REJECTED — full error follows (this is the failure "
            "signature we want to learn):")
        dump_response("output_media POST", resp)
    return ok, t_api


def stop_screenshare(client: httpx.Client, bot_id: str) -> bool:
    """DELETE /bot/{id}/output_media/ with body {"screenshare": true} stops the share.
    httpx.Client.delete() doesn't take a json body, so use .request("DELETE", ...)."""
    t = now_str()
    resp = client.request("DELETE", f"{RECALL_API_BASE}/bot/{bot_id}/output_media/",
                          headers=HEADERS_JSON, json={"screenshare": True}, timeout=30)
    ok = resp.status_code in (200, 201, 204)
    if ok:
        log(f"output_media DELETE accepted (HTTP {resp.status_code}) at {t} — "
            "note wall-clock when the share disappears from the meeting.")
    else:
        log("output_media DELETE failed — full error:")
        dump_response("output_media DELETE", resp)
    return ok


def remove_bot(client: httpx.Client, bot_id: str) -> None:
    """Repo removal convention (recall_routes.py:1927-1939): POST leave_call/ for
    in-call bots; DELETE /bot/{id}/ as fallback (works for scheduled/unjoined bots)."""
    try:
        resp = client.post(f"{RECALL_API_BASE}/bot/{bot_id}/leave_call/",
                           headers=HEADERS, timeout=15)
        log(f"leave_call -> HTTP {resp.status_code}")
        if resp.status_code not in (200, 201, 204):
            resp2 = client.delete(f"{RECALL_API_BASE}/bot/{bot_id}/", headers=HEADERS, timeout=15)
            log(f"DELETE /bot/{bot_id}/ fallback -> HTTP {resp2.status_code}")
    except Exception as exc:
        log(f"bot removal failed (clean up manually in the Recall dashboard): {exc}")


# ----------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SPIKE 2: Recall.ai Output Media webpage screenshare probe. "
                    "Create a throwaway Google Meet, run this, admit the bot, and "
                    "eyeball the share.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--meeting-url", required=True,
                        help="Throwaway meeting URL (e.g. https://meet.google.com/xxx-xxxx-xxx). "
                             "You must be IN the meeting to admit the bot and judge pixels.")
    parser.add_argument("--page-url", default="https://time.is",
                        help="Publicly reachable page to share. Default is a ticking clock "
                             "so smoothness/framerate is easy to judge by eye.")
    parser.add_argument("--variant", choices=["web", "web_4_core"], default="web",
                        help="Bot variant (CREATE-TIME-ONLY). Run once with each to A/B "
                             "Output Media smoothness. web=250 millicores (may be choppy), "
                             "web_4_core=recommended upgrade (+$0.10/hr).")
    parser.add_argument("--duration", type=int, default=60,
                        help="Seconds to hold the share while you judge smoothness.")
    args = parser.parse_args()

    if not RECALL_API_KEY:
        print("ERROR: RECALL_API_KEY is not set.")
        print("Expected in backend/.env (same var the app uses, recall_routes.py:57) "
              "or exported in your shell.")
        return 1

    marks: dict[str, str] = {}          # summary timestamps
    errors: list[str] = []
    bot_id: str | None = None
    share_active = False                # True between accepted POST and clean DELETE

    print("=" * 72)
    print("SPIKE 2 — Recall Output Media screenshare probe")
    print(f"  Recall base : {RECALL_API_BASE}")
    print(f"  meeting     : {args.meeting_url}")
    print(f"  page        : {args.page_url}")
    print(f"  variant     : {args.variant}")
    print(f"  hold        : {args.duration}s")
    print("=" * 72)

    client = httpx.Client()
    try:
        # 1. Create the bot (variant fixed here — no live upgrade exists).
        marks["create"] = now_str()
        log(f"Creating bot (variant={args.variant})…")
        resp = client.post(f"{RECALL_API_BASE}/bot/", headers=HEADERS_JSON,
                           json=build_create_payload(args.meeting_url, args.variant),
                           timeout=30)
        if resp.status_code not in (200, 201):
            dump_response("bot create FAILED", resp)
            errors.append(f"bot create -> HTTP {resp.status_code}")
            return 1
        bot_id = resp.json()["id"]
        log(f"Bot created: {bot_id}")
        log("Join the meeting yourself and ADMIT the bot when it knocks.")

        # 2. Poll until in_call_recording (prints every transition).
        code, statuses_seen = poll_until_in_call(client, bot_id)
        marks[code if code != "timeout" else "poll_timeout"] = now_str()
        if code != "in_call_recording":
            errors.append(f"never reached in_call_recording (stopped on '{code}')")
            return 1

        # 3. Start the webpage screenshare.
        ok, t_api = start_screenshare(client, bot_id, args.page_url)
        if ok:
            marks["output_media_accepted"] = t_api
            share_active = True
        else:
            errors.append("output_media POST rejected (see full body above)")
            return 1

        # 4. Hold — human judges smoothness.
        print(f"  Holding the share for {args.duration}s.")
        print(f"  WHILE WAITING: watch the shared page in the meeting — the clock "
              f"seconds should tick smoothly; if the page scrolls, scroll-watch it. "
              f"Note choppiness/frame drops for the variant summary (variant={args.variant}).")
        print("  Also watching bot status for rejection events (a host-side share "
              "block may only surface here, or as no pixels at all)…", flush=True)
        hold_deadline = time.monotonic() + args.duration
        # Seed from the join-poll's printed count so a share-rejection event that
        # fires in the first seconds after the POST is NOT silently swallowed.
        seen_extra = statuses_seen
        while time.monotonic() < hold_deadline:
            time.sleep(min(5, max(1, hold_deadline - time.monotonic())))
            try:
                st = client.get(f"{RECALL_API_BASE}/bot/{bot_id}/", headers=HEADERS, timeout=15)
                if st.status_code == 200:
                    changes = st.json().get("status_changes") or []
                    for ch in changes[seen_extra:]:
                        log(f"STATUS (during hold) -> {ch.get('code')} "
                            f"sub_code={ch.get('sub_code')} created_at={ch.get('created_at')}")
                    seen_extra = len(changes)
            except Exception as exc:
                log(f"status peek failed (non-fatal): {exc}")

        # 5. Stop the share.
        if stop_screenshare(client, bot_id):
            marks["screenshare_stopped"] = now_str()
            share_active = False
        else:
            errors.append("output_media DELETE failed (see full body above)")

    except KeyboardInterrupt:
        print()
        log("CTRL-C — cleaning up…")
        errors.append("interrupted by user")
    finally:
        # Robust cleanup: stop the share ONLY if it's still live (a redundant
        # DELETE would print a spurious error dump right where the human is told
        # to read failure signatures), then always remove the bot.
        if bot_id:
            if share_active:
                try:
                    if stop_screenshare(client, bot_id):
                        marks["screenshare_stopped"] = now_str()
                except Exception:
                    pass
            log(f"Removing bot {bot_id}…")
            remove_bot(client, bot_id)
            marks["bot_removed"] = now_str()
        client.close()

        # 6. Summary block.
        print()
        print("=" * 72)
        print("SPIKE 2 SUMMARY")
        print(f"  variant            : {args.variant}")
        print(f"  page shared        : {args.page_url}")
        for key in ("create", "joining_call", "in_call_recording", "poll_timeout",
                    "output_media_accepted", "screenshare_stopped", "bot_removed",
                    "call_ended", "done", "fatal_error"):
            if key in marks:
                print(f"  {key:<19}: {marks[key]}")
        if errors:
            print("  ERRORS:")
            for e in errors:
                print(f"    - {e}")
        else:
            print("  errors             : none")
        print()
        print("  Fill in by hand: T_pixels (wall clock when pixels appeared) minus")
        print("  output_media_accepted; smoothness verdict for this variant; wall")
        print("  clock when the share disappeared after screenshare_stopped.")
        print("-" * 72)
        print("  NEXT RUNS:")
        print("  1. Re-run with --variant web_4_core in a fresh meeting to A/B")
        print("     smoothness (variant is create-time-only, so it needs a new bot).")
        print("  2. FAILURE-MODE PROBE: create a meeting where the HOST LOCKS")
        print("     screen-sharing (Meet: Host controls -> 'Let everyone share their")
        print("     screen' OFF; run the script from a non-host account's meeting),")
        print("     then re-run. Whatever the output_media POST (or the in-hold")
        print("     status watcher) prints — full HTTP status + body above — is the")
        print("     catchable failure signature for the product fallback path")
        print("     (post the view link in chat instead).")
        print("=" * 72)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
