# Consent-Based Interjection (Autonomous v2) — Design Spec

**Date:** 2026-06-07
**Branch:** `fixed-changes`
**Status:** Proposed — pending user review of spec
**Supersedes:** the always-on "answer any question" behavior of autonomous mode in
`docs/superpowers/specs/2026-06-07-ambient-response-loop-design.md` (v1). The v1
funnel, mode state machine, flags, and shadow-soak are reused; this changes what
happens **after** the decider decides there's something worth saying.

---

## Problem (from the live test)

v1 autonomous mode, run always-on (`manual_mode=autonomous` via the Join picker),
disturbed the conversation and was slow. Real failures observed in logs:

- Responded to **human-to-human** turns: answered Venu's "do you wanna check the
  vendor forecast?" (said to Abhinav) and a filler "Okay. What?" — barging into
  the conversation. The participant literally complained mid-meeting: *"I'm
  checking if it's gonna talk in between while we talk. I don't want that."*
- **Latency** was 5–10s because every response ran the full agentic tool loop
  (`knowledge_lookup` + `web_search` + multi-iteration 70B) + a TTS fallback.

Root cause: a one-shot "answer the question" reaction has **no notion of whether
the moment is right or whether the info is wanted**, and pays full tool latency on
every (often unwanted) response.

**Goal:** make the bot behave like a thoughtful colleague — interject *briefly* to
**offer** genuinely useful info, and only deliver the full answer if a human says
yes. This fixes disturbance (brief, consented) and latency (tools gated behind
consent, when a human is actually waiting).

---

## Core insight: offers are low-stakes

A wrong **offer** is cheap and self-correcting — "Actually, I have something on X—"
/ "no thanks" — unlike a wrong **answer-dump**. So the design does **not** need
perfect "when to speak" judgment. The two things it must get right are
**frequency** (don't fatigue) and **timing** (don't talk over a human). Everything
else degrades gracefully. This principle is why the rest of the design is
tolerant of an imperfect decider.

---

## The two-phase model

```
                    OFFER (Phase 1)                         DELIVER (Phase 2)
   substantive moment ───────────────► brief, no-tools ───► [wait for consent] ──► full answer
   (70B reads the room)                offer + subject       human says yes        (70B + tools)
                                       e.g. "Actually, I      │  no / ignored        spoken
                                       have some info on X.    ▼
                                       Want to hear it?"      drop, stay silent
```

**Phase 1 — Offer (fast, minimal disruption).** When the 70B offer-decider judges
the bot has genuinely useful, on-topic info, the bot speaks a short, templated
line naming the subject. **No tools, no answer content** — near-instant. Records a
*pending offer*.

**Phase 2 — Deliver (only on consent).** The bot watches the next human turn(s):
- **Affirmative** → run the full generator (tools allowed) to answer about the
  offered subject; speak it. The slow tool work happens only when a human is
  waiting for it, so the latency is expected.
- **Negative** → drop, stay silent.
- **Ignored / ambiguous** → expire silently after the consent window. Never nag.

---

## Decision pipeline (revised)

```
each completed utterance (autonomous mode, not muted, past warmup)
  │
  ▼
state == OFFER_PENDING?  ──yes──►  CONSENT CLASSIFIER (8B)
  │ no                              ├─ affirmative → DELIVER (70B + tools) → speak → record subject, set cooldown
  ▼                                 ├─ negative    → drop → IDLE
① RECALL GATE (free heuristics)     └─ unclear/expired (≥2 turns or ≥window_s) → drop → IDLE
  │ pass
  ▼
② SUBSTANCE PREFILTER (8B, cheap)   "is this a substantive moment worth a deeper look?"  ─ miss → stop
  │ pass
  ▼
③ OFFER-DECIDER (70B, reads room)   "offer here? what's the SUBJECT?" → {offer, subject, confidence}
  │  guards: cooldown clear · not mid-utterance · subject not already offered · warmup passed
  ▼ offer=yes
④ OFFER GENERATOR (templated)       "Actually, I have some information about {subject}. Want to hear it?"
  │
  ▼
⑤ STREAM TTS → speak → state = OFFER_PENDING (record subject + ts)   [yields/cancels if talked over]
```

Reused from v1: the recall gate, the 8B decider (now the **substance prefilter**),
the generator/tool loop + verb-gate (now the **delivery** generator), streaming
TTS, the barge-in/supersede session machinery, `perception_state` counters.

New: the **70B offer-decider**, the **consent classifier**, the **offer
generator** (templated), the **interjection state machine**, **mute**, **warmup**.

---

## Interjection state machine (per bot)

```
        ┌──────── MUTED ────────┐   ("prism, stay quiet" / button)
        │   no offers; explicit  │
        │   requests still answered
        └──────▲────────┬────────┘  ("prism, chime in" / button)
               │        ▼
   IDLE ──offer-decider=yes──► OFFER_PENDING ──consent: yes──► DELIVERING ──done──► IDLE
    ▲                              │                                                  │
    │      consent: no / expired / talked-over                                        │
    └──────────────────────────────┘◄─────────────────────────────────────(cooldown set)
```

- **IDLE:** listening. Runs the pipeline; will offer only if not muted, past
  warmup, cooldown clear, subject not already offered, and not mid-utterance.
- **OFFER_PENDING:** an offer is out; **new offers are suppressed**. Each new human
  turn runs the consent classifier. Expires after `OFFER_CONSENT_WINDOW_S` (~25s)
  or 2 human turns, whichever first.
- **DELIVERING:** running the full generator + tools; speaking. On completion,
  record the subject (dedup) and set the offer cooldown.
- **MUTED:** no proactive offers. Explicit "prism, …" direct requests are still
  honored (mute = no *unsolicited* talk).

---

## Locked decisions

| ID | Decision | Rationale |
|----|----------|-----------|
| C1 | **Two-phase: brief offer → consent → full delivery.** | Fixes disturbance (brief + consented) and latency (tools gated behind a waiting human). |
| C2 | **Offers are low-stakes ⇒ design tolerates an imperfect decider.** Must nail only frequency + timing. | A wrong offer self-corrects in one beat; a wrong answer-dump doesn't. |
| C3 | **Offer-decider = 70B** (reads the room: substance vs small talk, timing, subject). 8B is a cheap *substance prefilter* before it. | The hard part is social judgment; 8B is too blunt. Offers are rare (cooldown/warmup/pending-suppression), so 70B cost is fine. |
| C4 | **Consent classifier = 8B**, not regex. | "No way, tell me!" = yes; "yeah, no, we're good" = no; "okay" = usually just acknowledgment. Keyword matching fails exactly these. |
| C5 | **Offer line is templated** with the decider's `subject`. No tools, no LLM gen on the hot path. | Fast + predictable + cheap. |
| C6 | **Delivery reuses the existing agentic generator** (`_process_command`, tools, verb-gate), framed to answer the offered subject. | Reuse; write-confirm still enforced; can decline (`NO_GROUNDED_ANSWER`). |
| C7 | **Mute = voice ("prism, stay quiet" / "chime in again") + UI button** (`POST /bot/{id}/mode` extended, or a dedicated mute flag). | The ultimate per-moment safety valve; makes every edge case forgiving. |
| C8 | **Warmup: no offers until substantive content exists** (≥ N substantive signals — live_decisions/action_items/entities — or the meeting is past intros). | No interjecting during "hey how are you" openers. Mirrors the Idea Engine warmup. |
| C9 | **Frequency guards:** longer offer cooldown (~90s) + never re-offer the same subject + only the single highest-value moment. | Fatigue is the main residual risk; this is the primary control. |
| C10 | **Timing guards:** only offer at a pause (not mid-utterance); **yield (cancel TTS) if talked over.** | Never win a collision with a human. |
| C11 | **Explicit direct requests bypass the offer dance** ("prism, look up X" / clear request to the assistant). | They asked — answer directly, no offer/consent. |
| C12 | **Graceful empty payoff.** Consent → tools find little → "hmm, less than I hoped." Keep the offer bar high to make rare. | Judgment-based offers (C2) can occasionally under-deliver. |

---

## Edge-case handling

| Situation | Handling |
|-----------|----------|
| **Small talk / rapport / jokes** (named) | Substance gate (8B prefilter + 70B decider) — social filler never clears it. Plus warmup (C8). |
| **Already answered / redundant** | Offer-decider checks recent context; don't offer what the room already covered. |
| **Topic moved on** | Offers are about the *current* topic; a pending offer expires if discussion shifts. |
| **Rapid back-and-forth / heated** | Timing gate — hold for a natural pause; don't offer into a fast exchange. |
| **Offer talked over** | Yield — cancel own TTS via the existing supersede/barge-in session (C10). |
| **Humans talk *about* the bot** ("is it listening?") | Detect meta-talk → back off, don't pile on. |
| **"Yes" answering a human, not the bot** | Consent only counts right after an offer, short window; when unsure, don't deliver (C2 makes this safe). |
| **Tricky affirmatives/negatives** | 8B consent classifier, not regex (C4). |
| **Late "yes" after window** | Ignored; offer already expired. |
| **Multi-party consent** | Any participant's clear affirmative counts (shared assistant); owner can mute (C7). |
| **Consent → nothing found** | Graceful degrade (C12). |
| **Explicit direct request** | Bypass offers; answer directly (C11). |
| **Transcription mangles subject** | Offer on best understanding; a wrong guess just gets declined. Upstream limitation. |
| **Genuine sensitivity (conflict/HR)** | Best-effort via the 70B's judgment + high bar + mute. Acknowledged imperfect; not fully solvable. |

---

## Components / files

| File | Change |
|------|--------|
| `backend/ambient_loop.py` | Add the interjection state machine (`IDLE/OFFER_PENDING/DELIVERING/MUTED`), the 70B `offer_decider`, the 8B `consent_classifier`, the templated `make_offer`, warmup + mute + cooldown + subject-dedup helpers. Rework `evaluate()` around the state machine. |
| `backend/realtime_routes.py` | Mute voice-command detection; thread offered-subject into the delivery `_process_command` framing; `_ambient_run_generator` delivers about `subject`; offer TTS yields on barge-in via the existing session. |
| `backend/recall_routes.py` / mode endpoint | Extend mute control (`POST /bot/{id}/mute` or reuse the mode endpoint with a `muted` flag). |
| `backend/meeting_memory.py` | State fields: `interjection_state`, `pending_offer`, `offered_subjects`, `offer_last_ts`, `muted`. Surface `muted`/`interjection_state` in the snapshot. |
| `backend/perception_state.py` | Counters: `offers_made`, `offers_accepted`, `offers_declined`, `offers_expired`, `offers_talked_over`, `mutes`. |
| `frontend/` | Mute toggle button in the in-meeting banner (reads/sets mute via the endpoint). |
| Env | `PRISM_OFFER_DECIDER_MODEL` (default 70B), `PRISM_OFFER_COOLDOWN_S` (90), `PRISM_OFFER_CONSENT_WINDOW_S` (25), `PRISM_OFFER_WARMUP_*`. |

---

## Rollout & validation

- Same flags as v1 (`PRISM_AUTONOMOUS`, `PRISM_AUTONOMOUS_SHADOW`). In shadow, log
  the would-be offer + subject + the consent decision, never speak.
- Counters drive tuning: **offer-accept rate** (are offers wanted?),
  **offers/meeting** (fatigue), **talked-over rate** (timing).
- Independent quick wins shipped alongside: TTS `ELEVENLABS_VOICE_ID` 402 fix
  (free plan can't use library voices) and the v1 env tuning (threshold/cooldown).

---

## Out of scope (deferred)

- Robust conflict/HR-sensitivity detection (best-effort only).
- Transcription-error correction (upstream).
- Distilled offer-decider (cost optimization; only if 70B offer volume hurts).
- Urgency override of cooldown for critical corrections (possible later).

---

## Acceptance criteria

1. During small talk / intros, the bot makes **no** offers (substance gate + warmup).
2. A substantive, genuinely-useful moment yields a **brief** offer naming the
   subject — no tool latency, no answer content.
3. The full (tool-using) answer is delivered **only** after a clear human
   affirmative; negative/ignored → silent, no nag.
4. An offer that's talked over yields (cancels its TTS).
5. The same subject is never offered twice; offers respect the cooldown.
6. "Prism, stay quiet" (or the button) stops offers; "chime in again" resumes;
   explicit direct requests still work while muted.
7. Behavior is byte-identical to today when `PRISM_AUTONOMOUS` is off.
8. New unit tests cover: state-machine transitions, consent classification
   (incl. tricky yes/no), warmup suppression, subject-dedup, cooldown, mute,
   talked-over yield, and the explicit-request bypass.
