# 2. The bot owner's sandbox serves the workspace's meetings

Date: 2026-07-12

## Status

Accepted

## Context

The Bot Screen Presentation feature (spec:
`docs/specs/2026-07-07-bot-screen-presentation-design.md`) gives the meeting bot
a screen: a persistent cloud sandbox desktop, logged into work apps, that the
bot screenshares into the call and drives with a computer-use loop.

Workspace bot-dedup means one bot often serves many workspace members — so the
person asking the bot to present is frequently NOT the person whose bot (and
sandbox) is in the room. Three identity models were considered:

1. **Bot owner's sandbox, owner-only asks** — the confirm-tools trust line.
2. **Asker-resolved sandbox** — map speaker → workspace member → their sandbox.
3. **Workspace-shared sandbox** — one team desktop with shared logins.

PrismAI's thesis is workspace collaboration: teammates share the content being
presented (a common GitHub repo, team Figma, staging dashboards) even though
each has their own accounts. A shared repo is not a shared login — but it means
the *content* shown from any member's account is usually content every member
could see anyway.

Option 2 founders on trust: speaker identity is diarization name-matching, so
"resolve the asker's sandbox" hands control of a member's logged-in desktop to
anyone who renames themselves in the meeting roster. Option 3 founders on
credentials: shared logins are a compliance and audit nightmare.

## Decision

- **The sandbox is always the bot owner's.** `user_settings.sandbox_id` is
  per-user; the sandbox that presents is the one belonging to the owner of the
  bot in the room. No workspace-shared sandboxes.
- **Any workspace member may ask the bot to present** in workspace-scope
  meetings. In personal-scope meetings, only the owner may.
- **Anyone in the call may stop a presentation.** The kill-phrase is a safety
  valve, not an authority check.
- **The guard moves from who-asks to what's-askable:** the computer-use system
  prompt is pinned to the stated goal and refuses personal surfaces (email,
  DMs, account settings, auth flows). A per-workspace domain allowlist checked
  deterministically before navigation actions is the planned hardening; prompt
  refusal alone is understood to be a soft wall.

## Consequences

- The person whose accounts are exposed is the person who chose to send the bot
  and to log work apps into a sandbox whose stated purpose is presenting to
  their team — consent is structural, not per-ask.
- Teammates get the collaboration behavior the product promises: anyone in the
  standup can say "pull up the PR" without caring whose bot is recording.
- A teammate CAN steer the owner's logged-in desktop toward non-shared content;
  the mitigations are the goal-pinned prompt, the anyone-can-stop kill-phrase,
  the owner's presence in the room, and (later) the domain allowlist. Accepted
  as "embarrassing, not breached" residual risk.
- Asker-resolved sandboxes (option 2) remain possible later only with a
  stronger-than-name-match confirmation (e.g. the asker approves from their own
  authenticated dashboard).
- Hard to reverse: the sandbox lookup key, the ask-gate, and the privacy story
  all encode this choice — hence this record.
