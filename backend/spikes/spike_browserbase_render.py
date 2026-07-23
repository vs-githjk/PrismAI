"""Render spike: prove Browserbase's source render (real crisp Chrome, not XFCE)
and mint a live-view URL to eyeball the WebRTC stream.

- Captures page.screenshot() -> PNG (the browser's OWN render = the SOURCE that
  feeds the live-view; if this is a clean browser, the stream can't look like
  "old Linux").
- Writes an index.html that iframes the live-view URL into a local viewer dir,
  so a static server + browser pane can show the actual WebRTC STREAM.
- Holds the session open so both can be inspected.

Project id resolved FROM THE KEY (never asked of the user). Free-tier safe.
"""
import os, time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r"C:\Users\abhin\PrismAI\backend\.env")
from browserbase import Browserbase
from playwright.sync_api import sync_playwright

SCRATCH = Path(r"C:\Users\abhin\AppData\Local\Temp\claude\C--Users-abhin-PrismAI\1d4eaf66-d5ea-47e4-ab1d-07922f5d84d3\scratchpad")
VIEWDIR = SCRATCH / "bbview"
SRC_PNG = SCRATCH / "bb_source.png"
TARGET = "https://github.com/microsoft/playwright/pulls"
HOLD_S = 600  # free-tier session cap is 15 min; hold 10

bb = Browserbase(api_key=os.environ["BROWSERBASE_API_KEY"])
pid = list(bb.projects.list())[0].id
print(f"[spike] project={pid}", flush=True)
session = bb.sessions.create(project_id=pid)
print(f"[spike] session={session.id}", flush=True)
live_url = bb.sessions.debug(session.id).debugger_fullscreen_url

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(session.connect_url)
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_viewport_size({"width": 1280, "height": 720})  # match Recall's surface
    page.goto(TARGET, wait_until="domcontentloaded")
    time.sleep(2)
    page.screenshot(path=str(SRC_PNG))
    print(f"[spike] source screenshot -> {SRC_PNG}", flush=True)

    # iframe viewer for the live-view STREAM
    VIEWDIR.mkdir(parents=True, exist_ok=True)
    (VIEWDIR / "index.html").write_text(
        "<!doctype html><meta charset=utf-8>"
        "<style>html,body{margin:0;height:100%;background:#111}"
        "iframe{border:0;width:100vw;height:100vh}</style>"
        f'<iframe src="{live_url}" allow="clipboard-read; clipboard-write"></iframe>'
    )
    print(f"[spike] viewer written -> {VIEWDIR/'index.html'}", flush=True)
    print("=" * 70, flush=True)
    print(f"LIVE_VIEW {live_url}", flush=True)
    print("VIEWER http://127.0.0.1:8091/", flush=True)
    print("=" * 70, flush=True)

    for _ in range(HOLD_S // 4):
        try:
            page.mouse.wheel(0, 500)
        except Exception:
            pass
        time.sleep(4)
    browser.close()
print("[spike] done", flush=True)
