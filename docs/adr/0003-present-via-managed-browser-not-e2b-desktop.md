# 3. Present via a managed cloud browser (Browserbase), not a self-run Linux desktop (E2B)

Date: 2026-07-17

## Status

Accepted — supersedes the provider choice in the Bot Screen Presentation spec
(`docs/specs/2026-07-07-bot-screen-presentation-design.md`, which selected E2B).
ADR 0002 (the owner's workspace serves the meeting) still holds, with "sandbox"
re-read as "browser Context".

## Context

Phases 1–4 of Bot Screen Presentation shipped on **E2B**: a persistent Linux
desktop (XFCE) streamed into the meeting as the bot's Recall screenshare over
**noVNC**, driven by a Claude computer-use loop. A live test surfaced three
problems the design had under-weighted:

1. **Quality.** The stream was laggy and buffered and "looked like an old Linux
   OS" — XFCE + full-desktop noVNC, worsened by a US-region sandbox for a
   Dubai user, and capped by Recall's 1280×720/15fps render surface.
2. **Onboarding.** Manual per-user GitHub login inside each sandbox doesn't
   scale to real teams.
3. **Bot-flagging.** An automated browser logging into GitHub/Figma from a US
   datacenter IP invites CAPTCHAs and account-security locks.

Every actual use case is a **web** UI (GitHub PR, dashboard, Figma) — a full
Linux desktop is overhead. Verified research (Jul 2026) compared browser-first
providers against a patched E2B-kiosk baseline.

## Decision

**Present from a managed cloud browser (Browserbase), replacing E2B for the
presentation surface.** Rationale, per problem:

- **Quality:** Browserbase streams a single real Chrome viewport over **WebRTC**
  — smooth, and it *looks like a browser*, not a desktop. (Recall's 720p/15fps
  cap still binds everyone; WebRTC-of-a-viewport spends that budget far better
  than noVNC-of-a-desktop.)
- **Onboarding:** Browserbase **Contexts** persist the logged-in profile — the
  user logs in **once**, every later meeting reuses it. Not zero logins (a real
  web session needs a one-time interactive login, which also clears 2FA), but
  once-ever instead of every-meeting.
- **Bot-flagging:** basic **stealth** + a **UAE residential egress proxy** make
  a Dubai user's logins look like the legitimate returning user, not a
  datacenter intrusion. (CAPTCHA-solving is available and deliberately NOT
  used — it gets accounts banned and is out of scope.)

Configuration: compute in **Frankfurt** (nearest region; no ME compute region
exists), egress from a **UAE residential IP** (set independently). **Cost:** the
free tier ($0) covers build + the render spike; the **$20/mo Developer tier** is
accepted as the production floor because the anti-flag + persistent-login
features live there — turned on only when real users onboard.

**Kept:** the abstract `SandboxProvider` protocol (this pivot is its payoff — a
new `browserbase_provider.py` adapter), the per-present token + wrapper-page
pattern (Phase 2, re-pointed at a WebRTC embed), the presentation manager
(Phase 3), and the members-only `/live` mirror (Phase 4) — all provider-agnostic
above the protocol.

**Kept: the vision-based drive loop** (`run_computer_use`, screenshot → click),
now driving Browserbase over CDP rather than E2B/xdotool — chosen over
DOM-level CDP/Stagehand because (a) it already works on arbitrary UIs including
**canvas apps like Figma** where there is no useful DOM, and (b) human-paced
mouse/click is *less* bot-detectable than DOM automation's `navigator.webdriver`
fingerprint — aligning with the anti-flag goal. Stagehand/DOM stays a possible
v2 speed optimization. (Still needs `ANTHROPIC_API_KEY`.)

## Consequences

- The E2B adapter becomes a fallback / removable; the built E2B path is not
  wasted — the protocol abstraction is exactly what makes the swap an adapter
  change, not a rewrite.
- The persistence model changes shape: E2B was one persistent sandbox
  (pause/resume). Browserbase is a **persistent Context (per user, holds login)
  + an ephemeral Session per present**. `user_settings.sandbox_id` becomes a
  Context id; the auth key / stream URL are minted per session. The provider
  adapter absorbs this; `pause` maps to "kill the session, keep the Context",
  which removes idle cost entirely.
- **Gate:** none of this is committed to code until a **render spike** proves
  Recall's headless Chromium renders the Browserbase WebRTC live-view acceptably
  as a screenshare — the single never-tested root risk (Recall output_media was
  never run against any live-view). Free tier suffices for the spike.
- Hyperbrowser is the documented fallback (same adapter shape) if concurrency
  scale arrives or Browserbase's render/cost disappoints.
- Hard to reverse: it re-points the core delivery mechanism, the provider
  adapter, the wrapper embed, and the onboarding flow, and commits to a vendor
  — hence this record.
