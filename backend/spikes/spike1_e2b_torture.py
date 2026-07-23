"""SPIKE 1 — E2B desktop-sandbox pause/resume TORTURE TEST.

Decides the sandbox-provider choice for persistent per-user desktops
(docs/specs/2026-06-14-ambient-desktop-capture-design.md lineage: each user gets
a persistent E2B desktop whose noVNC stream URL is screenshared into meetings;
between meetings the sandbox is PAUSED via memory snapshot).

Load-bearing UNVERIFIED claims this script tests:
  (a) pause/resume preserves memory + running processes on the DESKTOP template
      specifically (E2B docs only document persistence for generic sandboxes).
  (b) the noVNC stream URL keeps working after resume — docs say clients get
      disconnected and must reconnect, but to the SAME URL. The URL is
      https://6080-{sandbox_id}.{domain}/vnc.html (verified in SDK source:
      e2b_desktop/main.py _VNCServer.__init__ + e2b/connection_config.py
      get_host => f"{port}-{sandbox_id}.{sandbox_domain}"), so it is stable
      as long as sandbox_id survives pause/resume.
  (c) ~1s resume latency holds for a RAM-heavy desktop template (Xvfb + xfce4 +
      x11vnc + noVNC proxy + a browser are all resident).
  (d) multi-cycle fidelity — GitHub e2b-dev/E2B #884 reported FILE LOSS after
      the 2nd resume (closed), #1031 reports process-bookkeeping drift (open).
      Hence N=20 cycles with per-cycle breadcrumb files and a process-table
      bookkeeping probe.

Verified SDK facts (read from installed source, e2b==2.31.0, e2b-desktop==2.4.1):
  - e2b_desktop.Sandbox.create(template=None, resolution=None, dpi=None,
    display=None, timeout=None, ...) — classmethod; default_template="desktop".
    It boots Xvfb + xfce4 itself via commands.  [e2b_desktop/main.py:204-279]
  - desktop.stream -> _VNCServer with .start(require_auth=False, ...),
    .get_url(auto_connect=True, view_only=False, resize="scale", auth_key=None),
    .get_auth_key(), .stop()               [e2b_desktop/main.py:84-201,314-316]
  - sandbox.pause(keep_memory=True) / Sandbox.pause(sandbox_id) — returns True
    if paused, False if already paused. keep_memory=True = full memory snapshot.
    (beta_pause is deprecated.)            [e2b/sandbox_sync/main.py:614-692]
  - Sandbox.connect(sandbox_id, timeout=None) — classmethod; "If the sandbox is
    paused, it will be automatically resumed." There is NO separate resume().
    Returns a NEW instance via cls(...) — on e2b_desktop.Sandbox the returned
    object LACKS _display and the __vnc_server (only create() sets those), so
    .stream / desktop-only helpers must not be used on a reconnected handle;
    commands/files work fine (DISPLAY is a sandbox-level env set at create).
                                           [e2b/sandbox_sync/main.py:241-335,857-905]
  - sandbox.commands.run(cmd, background=False, envs=None, user=None, cwd=None,
    timeout=60, ...) -> CommandResult(stdout, stderr, exit_code, error) or
    CommandHandle(pid, kill(), disconnect()) when background=True.
                                           [e2b/sandbox_sync/commands/command.py:203-305]
  - sandbox.files.write(path, data) / files.read(path, format="text")
                                           [e2b/sandbox_sync/filesystem/filesystem.py:129-318]
  - sandbox.get_host(port) -> f"{port}-{sandbox_id}.{sandbox_domain}"
                                           [e2b/sandbox/main.py:208, e2b/connection_config.py:208-222]
  - sandbox.kill() / Sandbox.kill(sandbox_id), sandbox.is_running(),
    sandbox.set_timeout(seconds)           [e2b/sandbox_sync/main.py:343-443]
  - API key: E2B_API_KEY env var           [e2b/connection_config.py:87-88]

State markers planted (all under /home/user/spike1/):
  (i)   marker.txt — static file written once; must read back identically after
        every resume. PLUS a breadcrumb file per cycle (cycle_{n}.txt) and after
        every resume ALL previous breadcrumbs are re-verified (the #884 shape).
  (ii)  counter.py — a detached (nohup+setsid) python loop holding an IN-MEMORY
        run_id (uuid, generated in-process) + an in-memory list it appends to,
        writing {pid, run_id, counter, mem_len} to counter.json every second.
        After resume: same run_id + same pid + counter ADVANCED + still
        advancing  => process MEMORY SURVIVED.  Different run_id/pid => process
        was RESTARTED (memory lost).  Frozen counter => process DEAD.
  (iii) a browser opened via xdg-open (whatever the desktop template ships —
        detected via pgrep). Browser-process-alive with the SAME pids after
        resume is the marker (cookie planting skipped as not-cheap here).

Per cycle: pause -> timed | dwell | resume via Sandbox.connect -> timed
  time_to_usable   = resume start -> first successful `echo ok` command
  stream HTTP GET  = the noVNC URL must answer 200 again (frame-level check is
                     manual: the URL is printed EVERY cycle for eyeballing)

Gates (printed as verdict lines in the final JSON report):
  GATE_FIDELITY : PASS = every marker intact on all N cycles
  GATE_LATENCY  : PASS = p95(time_to_usable) <= 3.0 s

Usage:
  python backend/spikes/spike1_e2b_torture.py                 # 20 cycles
  python backend/spikes/spike1_e2b_torture.py --cycles 5 --keep
  python backend/spikes/spike1_e2b_torture.py --report-file spike1_report.json

Requires E2B_API_KEY in backend/.env (or the environment). e2b + e2b-desktop
are spike-only deps (NOT in backend/requirements.txt):
  pip install e2b e2b-desktop
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------- env loading

def load_backend_env() -> None:
    """Load backend/.env (relative to this file: ../.env) without importing app
    code. Tries python-dotenv (a repo dependency) and falls back to a manual
    KEY=VALUE parse."""
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


# ------------------------------------------------------------------- helpers

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def pct(values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile (no numpy dep)."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return round(s[int(k)], 3)
    return round(s[f] + (s[c] - s[f]) * (k - f), 3)


def http_get_status(url: str, timeout_s: float = 10.0) -> tuple[int | None, str]:
    """GET the stream URL; returns (status_code, note). Uses httpx if present
    (repo dependency), else stdlib urllib. noVNC serves vnc.html statically, so
    200 here proves the port-forward endpoint is reachable/reconnectable —
    actual FRAME delivery over the websocket is verified by human eyeball."""
    try:
        import httpx
        try:
            r = httpx.get(url, timeout=timeout_s, follow_redirects=True)
            return r.status_code, ""
        except Exception as e:  # noqa: BLE001 — spike: any failure is a data point
            return None, f"{type(e).__name__}: {e}"
    except ImportError:
        pass
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


# --------------------------------------------------- in-sandbox marker assets

SPIKE_DIR = "/home/user/spike1"
MARKER_FILE = f"{SPIKE_DIR}/marker.txt"
COUNTER_SCRIPT = f"{SPIKE_DIR}/counter.py"
COUNTER_JSON = f"{SPIKE_DIR}/counter.json"

# Marker (ii): run_id is generated IN-PROCESS — if the process is ever
# restarted (rather than resumed with memory intact) the run_id changes.
# The `mem` list is genuine in-RSS state so the memory snapshot has to carry it.
COUNTER_PY = """\
import json, os, time, uuid

run_id = uuid.uuid4().hex[:12]   # in-memory identity: survives ONLY a true resume
pid = os.getpid()
mem = []                          # in-memory state that must survive the snapshot
i = 0
while True:
    i += 1
    mem.append(i)
    if len(mem) > 200000:         # keep RSS bounded on long runs
        mem = mem[-1000:]
    tmp = "%(json)s.tmp"
    with open(tmp, "w") as f:
        json.dump({"pid": pid, "run_id": run_id, "counter": i,
                   "mem_len": len(mem), "ts": time.time()}, f)
    os.replace(tmp, "%(json)s")
    time.sleep(1)
""" % {"json": COUNTER_JSON}

# Bracket-trick first letters: envd runs every command via `/bin/bash -l -c <cmd>`,
# so a plain pattern would match its own bash wrapper (whose cmdline contains the
# literal pattern text) — a phantom, ever-changing "browser" pid that would force
# browser_available=True on browser-less templates and fail same-pids every cycle.
BROWSER_PGREP = "pgrep -f '[f]irefox|[c]hromium|[c]hrome|[e]piphany|[m]idori' | sort || true"


def read_counter(sbx) -> dict | None:
    try:
        raw = sbx.files.read(COUNTER_JSON)   # format="text" default
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        log(f"    counter.json unreadable: {type(e).__name__}: {e}")
        return None


def browser_pids(sbx) -> set[str]:
    try:
        out = sbx.commands.run(BROWSER_PGREP, timeout=15).stdout
        return {p for p in out.split() if p.strip().isdigit()}
    except Exception as e:  # noqa: BLE001
        log(f"    browser pgrep failed: {type(e).__name__}: {e}")
        return set()


def process_table_len(sbx) -> int | None:
    """Informational probe for GitHub #1031: does the SDK's own process
    bookkeeping (commands.list()) still see anything after resume? Ground truth
    for survival is pgrep/counter.json, NOT this."""
    try:
        return len(sbx.commands.list())
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------- spike

def main() -> int:
    ap = argparse.ArgumentParser(description="E2B desktop pause/resume torture test")
    ap.add_argument("--cycles", type=int, default=20, help="pause/resume cycles (default 20)")
    ap.add_argument("--dwell", type=float, default=3.0, help="seconds to stay paused each cycle (default 3)")
    ap.add_argument("--timeout", type=int, default=1800, help="sandbox TTL in seconds, re-applied on every connect (default 1800)")
    ap.add_argument("--resolution", default="1280x720", help="desktop resolution WxH (default 1280x720)")
    ap.add_argument("--template", default=None, help="template name/ID (default: SDK default 'desktop')")
    ap.add_argument("--url", default="https://example.com", help="URL to open in the in-desktop browser marker")
    ap.add_argument("--keep", action="store_true", help="do NOT kill the sandbox at the end")
    ap.add_argument("--report-file", default=None, help="also write the final JSON report to this path")
    args = ap.parse_args()

    if not os.environ.get("E2B_API_KEY"):
        print(
            "\nERROR: E2B_API_KEY is not set.\n"
            "  Add E2B_API_KEY=e2b_... to backend/.env (get one at https://e2b.dev/dashboard)\n"
            "  or set it in the environment before running this spike.\n",
            file=sys.stderr,
        )
        return 2

    try:
        from e2b import AuthenticationException
        from e2b_desktop import Sandbox as DesktopSandbox
    except ImportError:
        print(
            "\nERROR: e2b-desktop is not installed (spike-only dependency, deliberately\n"
            "not in backend/requirements.txt). Run:\n"
            "  pip install e2b e2b-desktop\n",
            file=sys.stderr,
        )
        return 2

    try:
        width, height = (int(x) for x in args.resolution.lower().split("x"))
    except ValueError:
        print(f"ERROR: bad --resolution {args.resolution!r}, expected WxH like 1280x720", file=sys.stderr)
        return 2

    cycles: list[dict] = []
    sandbox_id: str | None = None
    report: dict = {}
    browser_available = False

    try:
        # ------------------------------------------------------------ create
        log(f"Creating desktop sandbox (template={args.template or 'desktop (SDK default)'}, "
            f"{width}x{height}, timeout={args.timeout}s)...")
        t0 = time.perf_counter()
        desktop = DesktopSandbox.create(
            template=args.template,
            resolution=(width, height),
            timeout=args.timeout,
        )
        create_s = round(time.perf_counter() - t0, 3)
        sandbox_id = desktop.sandbox_id
        log(f"Created sandbox {sandbox_id} in {create_s}s")

        # ------------------------------------------------------------ stream
        log("Starting noVNC stream (require_auth=True)...")
        desktop.stream.start(require_auth=True)
        auth_key = desktop.stream.get_auth_key()
        stream_url = desktop.stream.get_url(auth_key=auth_key)
        base_stream_host = desktop.get_host(6080)  # 6080 = _VNCServer default noVNC port
        print("\n" + "=" * 78)
        print(f"  STREAM URL : {stream_url}")
        print(f"  AUTH KEY   : {auth_key}")
        print("  Open this in a browser NOW and keep it open — after each resume,")
        print("  reconnect the same tab to eyeball that frames flow again.")
        print("=" * 78 + "\n")

        status, note = http_get_status(stream_url)
        log(f"Baseline stream GET -> {status} {note}")
        if status != 200:
            log("WARNING: stream URL did not answer 200 at baseline — cycle checks will show the same.")

        # ----------------------------------------------------- plant markers
        marker_token = f"spike1-{datetime.now().isoformat()}-{os.getpid()}"
        desktop.files.write(MARKER_FILE, marker_token)
        log(f"Marker (i) file planted: {MARKER_FILE} = {marker_token!r}")

        desktop.files.write(COUNTER_SCRIPT, COUNTER_PY)
        # nohup+setsid detaches from the envd command session so the loop is not
        # tied to this client connection. (The desktop SDK keeps Xvfb/xfce4 alive
        # differently — background=True + handle.disconnect() — but a fully
        # detached session is the stronger guarantee for a must-outlive-us probe.)
        desktop.commands.run(
            f"nohup setsid python3 {COUNTER_SCRIPT} >{SPIKE_DIR}/counter.log 2>&1 &",
            timeout=15,
        )
        time.sleep(2.5)
        baseline_counter = read_counter(desktop)
        if not baseline_counter:
            raise RuntimeError("Marker (ii) counter process failed to start — check counter.log in the sandbox")
        log(f"Marker (ii) counter running: pid={baseline_counter['pid']} "
            f"run_id={baseline_counter['run_id']} counter={baseline_counter['counter']}")

        log(f"Marker (iii) opening browser at {args.url} (xdg-open)...")
        desktop.open(args.url)
        time.sleep(8)  # browsers are slow to fork their process tree
        baseline_browser = browser_pids(desktop)
        browser_available = bool(baseline_browser)
        if browser_available:
            log(f"Marker (iii) browser processes: {sorted(baseline_browser)}")
        else:
            log("WARNING: no browser process detected after xdg-open — marker (iii) is "
                "EXCLUDED from the gate (template may lack a browser). Verdict will say so.")

        baseline_proc_table = process_table_len(desktop)
        log(f"SDK commands.list() sees {baseline_proc_table} processes (bookkeeping probe, #1031)")

        # ------------------------------------------------------- torture loop
        sbx = desktop  # current live handle; replaced by Sandbox.connect() each cycle
        prev_counter = baseline_counter

        for n in range(1, args.cycles + 1):
            log(f"--- CYCLE {n}/{args.cycles} " + "-" * 40)
            row: dict = {"cycle": n}

            # breadcrumb for the #884 file-loss-after-2nd-resume shape
            sbx.files.write(f"{SPIKE_DIR}/cycle_{n}.txt", f"breadcrumb {n} {marker_token}")

            pre = read_counter(sbx) or prev_counter

            # PAUSE (instance method; keep_memory=True default = memory snapshot)
            t0 = time.perf_counter()
            paused = sbx.pause()
            row["pause_s"] = round(time.perf_counter() - t0, 3)
            row["pause_returned"] = paused  # False would mean "was already paused"
            log(f"  paused in {row['pause_s']}s (returned {paused})")

            time.sleep(args.dwell)

            # RESUME — production shape: a FRESH handle from a (possibly different)
            # process resumes by id. connect() auto-resumes paused sandboxes.
            t0 = time.perf_counter()
            sbx = DesktopSandbox.connect(sandbox_id, timeout=args.timeout)
            row["resume_connect_s"] = round(time.perf_counter() - t0, 3)

            # time-to-usable: first successful command after resume start
            usable_err = ""
            deadline = time.time() + 60
            while True:
                try:
                    r = sbx.commands.run("echo ok", timeout=10)
                    if r.exit_code == 0:
                        break
                except Exception as e:  # noqa: BLE001
                    usable_err = f"{type(e).__name__}: {e}"
                if time.time() > deadline:
                    break
                time.sleep(0.25)
            row["time_to_usable_s"] = round(time.perf_counter() - t0, 3)
            row["usable_last_error"] = usable_err
            log(f"  resume: connect={row['resume_connect_s']}s, "
                f"time_to_usable={row['time_to_usable_s']}s")

            # (b) stream URL stability + reconnectability
            row["host_stable"] = (sbx.get_host(6080) == base_stream_host)
            t0 = time.perf_counter()
            status, note = http_get_status(stream_url)
            row["stream_http_s"] = round(time.perf_counter() - t0, 3)
            row["stream_status"] = status
            row["stream_ok"] = status == 200
            log(f"  stream GET -> {status} in {row['stream_http_s']}s "
                f"(host_stable={row['host_stable']}) {note}")
            log(f"  EYEBALL NOW -> {stream_url}")

            # (i) file marker + all breadcrumbs so far (#884)
            try:
                row["file_ok"] = sbx.files.read(MARKER_FILE) == marker_token
            except Exception as e:  # noqa: BLE001
                row["file_ok"] = False
                log(f"  marker file read FAILED: {type(e).__name__}: {e}")
            missing = []
            for k in range(1, n + 1):
                try:
                    if f"breadcrumb {k} " not in sbx.files.read(f"{SPIKE_DIR}/cycle_{k}.txt"):
                        missing.append(k)
                except Exception:  # noqa: BLE001
                    missing.append(k)
            row["breadcrumbs_ok"] = not missing
            row["breadcrumbs_missing"] = missing
            log(f"  file marker ok={row['file_ok']}, breadcrumbs ok={row['breadcrumbs_ok']}"
                + (f" MISSING={missing}" if missing else ""))

            # (ii) memory/process survival: survived vs restarted vs dead
            time.sleep(2.5)  # give the loop time to tick post-resume
            c1 = read_counter(sbx)
            time.sleep(2.5)
            c2 = read_counter(sbx)
            if not c1 or not c2:
                row["mem_verdict"] = "DEAD (counter.json unreadable)"
                row["mem_ok"] = False
            else:
                same_identity = (c1["run_id"] == baseline_counter["run_id"]
                                 and c1["pid"] == baseline_counter["pid"])
                advanced = c1["counter"] > pre["counter"]
                advancing = c2["counter"] > c1["counter"]
                row["counter_pre_pause"] = pre["counter"]
                row["counter_post_resume"] = c2["counter"]
                if same_identity and advanced and advancing:
                    row["mem_verdict"] = "SURVIVED (same run_id+pid, counter advanced)"
                    row["mem_ok"] = True
                elif not same_identity:
                    row["mem_verdict"] = (f"RESTARTED (run_id {baseline_counter['run_id']}"
                                          f"->{c1['run_id']}, pid {baseline_counter['pid']}"
                                          f"->{c1['pid']}) — memory LOST")
                    row["mem_ok"] = False
                elif not advancing:
                    row["mem_verdict"] = f"FROZEN/DEAD (counter stuck at {c1['counter']})"
                    row["mem_ok"] = False
                else:
                    row["mem_verdict"] = "AMBIGUOUS (same identity but counter did not advance past pre-pause)"
                    row["mem_ok"] = False
            log(f"  memory marker: {row['mem_verdict']}")
            prev_counter = c2 or prev_counter

            # (iii) browser process
            if browser_available:
                now_pids = browser_pids(sbx)
                row["browser_alive"] = bool(now_pids)
                row["browser_same_pids"] = now_pids == baseline_browser
                row["browser_ok"] = row["browser_alive"] and row["browser_same_pids"]
                log(f"  browser: alive={row['browser_alive']} same_pids={row['browser_same_pids']}")
            else:
                row["browser_ok"] = None  # excluded from gate

            row["sdk_process_table_len"] = process_table_len(sbx)  # #1031 probe

            row["all_ok"] = all([
                row["file_ok"], row["breadcrumbs_ok"], row["mem_ok"],
                row["stream_ok"], row["host_stable"],
                (row["browser_ok"] if browser_available else True),
            ])
            log(f"  CYCLE {n} => {'OK' if row['all_ok'] else 'FAILED'}")
            cycles.append(row)

        # ------------------------------------------------------------- report
        connect_times = [c["resume_connect_s"] for c in cycles]
        usable_times = [c["time_to_usable_s"] for c in cycles]
        n_ok = sum(1 for c in cycles if c["all_ok"])
        marker_failures = {
            "file": [c["cycle"] for c in cycles if not c["file_ok"]],
            "breadcrumbs_884": [c["cycle"] for c in cycles if not c["breadcrumbs_ok"]],
            "memory_process": [c["cycle"] for c in cycles if not c["mem_ok"]],
            "browser": [c["cycle"] for c in cycles if browser_available and not c["browser_ok"]],
            "stream_http": [c["cycle"] for c in cycles if not c["stream_ok"]],
            "host_stability": [c["cycle"] for c in cycles if not c["host_stable"]],
        }
        p95_usable = pct(usable_times, 95)
        gate_fidelity = n_ok == args.cycles and args.cycles > 0
        gate_latency = p95_usable is not None and p95_usable <= 3.0

        report = {
            "spike": "spike1_e2b_torture",
            "ran_at": datetime.now().isoformat(),
            "sandbox_id": sandbox_id,
            "template": args.template or "desktop (SDK default)",
            "sdk_versions": {"e2b": _dist_version("e2b"), "e2b_desktop": _dist_version("e2b-desktop")},
            "cycles_requested": args.cycles,
            "cycles_all_ok": n_ok,
            "resume_connect_s": {"p50": pct(connect_times, 50), "p95": pct(connect_times, 95),
                                 "min": min(connect_times, default=None), "max": max(connect_times, default=None)},
            "time_to_usable_s": {"p50": pct(usable_times, 50), "p95": p95_usable,
                                 "min": min(usable_times, default=None), "max": max(usable_times, default=None)},
            "marker_failures_by_cycle": marker_failures,
            "browser_marker_in_gate": browser_available,
            "stream_url": stream_url,
            "gates": {
                "GATE_FIDELITY (all markers intact every cycle)": "PASS" if gate_fidelity else "FAIL",
                "GATE_LATENCY (p95 time_to_usable <= 3s)": "PASS" if gate_latency else "FAIL",
            },
            "claim_verdicts": {
                "(a) desktop pause/resume preserves memory+processes":
                    "PASS" if not marker_failures["memory_process"] else
                    f"FAIL on cycles {marker_failures['memory_process']}",
                "(b) stream URL survives resume (same URL, serves again)":
                    "PASS" if not marker_failures["stream_http"] and not marker_failures["host_stability"] else
                    f"FAIL (http fails {marker_failures['stream_http']}, host drift {marker_failures['host_stability']})"
                    + " — NOTE frame-level delivery was eyeball-verified only",
                "(c) resume latency on RAM-heavy desktop":
                    f"p95 time_to_usable={p95_usable}s (gate 3s): " + ("PASS" if gate_latency else "FAIL"),
                "(d) multi-cycle fidelity (#884 file loss / #1031 bookkeeping)":
                    ("PASS" if not marker_failures["breadcrumbs_884"] and not marker_failures["file"] else
                     f"FAIL (file loss on cycles {marker_failures['breadcrumbs_884'] or marker_failures['file']})")
                    + f"; sdk process-table lens per cycle: {[c['sdk_process_table_len'] for c in cycles]}",
            },
            "per_cycle": cycles,
        }

        print("\n" + "=" * 78)
        print("FINAL REPORT (JSON)")
        print("=" * 78)
        print(json.dumps(report, indent=2))
        if args.report_file:
            Path(args.report_file).write_text(json.dumps(report, indent=2), encoding="utf-8")
            log(f"Report written to {args.report_file}")

        return 0 if (gate_fidelity and gate_latency) else 1

    except AuthenticationException as e:
        print(
            f"\nERROR: E2B rejected the API key ({e}).\n"
            "  Check E2B_API_KEY in backend/.env — get a valid key at https://e2b.dev/dashboard\n",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        log("Interrupted.")
        return 130
    finally:
        if sandbox_id and not args.keep:
            try:
                from e2b_desktop import Sandbox as DesktopSandbox
                # static kill by id works whether the sandbox is running or paused
                killed = DesktopSandbox.kill(sandbox_id)
                log(f"Cleanup: killed sandbox {sandbox_id} -> {killed}")
            except Exception as e:  # noqa: BLE001
                log(f"Cleanup FAILED for sandbox {sandbox_id}: {type(e).__name__}: {e} "
                    f"— kill it manually at https://e2b.dev/dashboard (it will also "
                    f"auto-expire after its timeout)")
        elif sandbox_id:
            log(f"--keep set: sandbox {sandbox_id} left alive (expires after --timeout, "
                f"or pause it yourself to keep state)")


def _dist_version(name: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:  # noqa: BLE001
        return None


if __name__ == "__main__":
    sys.exit(main())
