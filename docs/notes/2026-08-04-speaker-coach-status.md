# Speaker coaching: why it "fails across many meetings" (it doesn't)

**TL;DR — working as designed.** Speaker coaching is intentionally OFF for
recordings with fewer than two human speakers. Most of our own meetings are one
person talking to the Prism bot, so most of our meetings show no coach card.
That's the feature working, not failing.

## The mechanism

- `agents/orchestrator.py` routes `speaker_coach` (and `sentiment`) only when
  `count_human_speakers(transcript) >= 2`. The bot's own lines (Prism + persona
  names) do not count as a participant.
- Why: before the gate, a solo session with the bot was coached like a team
  meeting — "you spoke 96% of the time" advice for someone giving commands to
  an assistant, and sentiment verdicts like "Prism dominates 81% of talk"
  grading the product as a coworker. That noise is what got removed (Aug 2).

## Verification (Aug 4, against production data)

Across the audited account's 32 meetings:

| Case | Count | Coach card |
|---|---|---|
| 2+ human speakers | 10 | ✅ all 10 have coach data |
| Solo / human-plus-bot | 22 | ⛔ none (by design) |

Four multi-human meetings were missing coach output (the agent returned empty
during the Aug 2 re-analysis backfill) — re-run and repaired on Aug 4. One solo
meeting carried stale pre-gate coach data — nulled for consistency.

## Caveats / follow-ups

- The Anthropic API key is **out of credits**; the Aug 4 repairs ran on the
  gpt-4o-mini fallback. Once credits are restored, new analyses return to
  claude-sonnet-5 automatically — no code change needed.
- Backlog idea (not built): a solo-session coach variant that grades how well
  you briefed the assistant (clarity of asks, follow-through) so solo
  recordings get a meaningful card instead of none.
