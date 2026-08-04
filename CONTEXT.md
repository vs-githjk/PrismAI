# PrismAI — Context Glossary

The shared language of the PrismAI dashboard. Terms here are canonical; code and
conversation should use them consistently. This file is a glossary, not a spec —
no implementation details.

## Terms

### Workspace
A shared collaboration scope. The user is always in exactly one scope at a time:
either **Personal** (their own meetings) or a named **Workspace** (meetings shared
with teammates). The active scope determines which meetings, history, and insights
are visible. Switched via the **Workspace switcher**.

### Workspace switcher
The control at the **top of the sidebar** that selects the active scope
(Personal or a named workspace) and exposes per-workspace settings (invite link,
members, delete/leave).

### Home
A pinned sidebar page, always present, that is the default landing surface.
Scope-aware and **state-aware**: a one-line greeting stays as the brand moment,
and beneath it the **Meeting hero** — the single most time-sensitive meeting
(live → starting soon → next upcoming), with countdown and Join / View context /
Send Stand-in actions; when nothing is scheduled it collapses to a compact
status row (never a large empty card). Below the hero: the **Needs-attention
feed** (a bounded slice of the Task hub) and a capped recent-meetings list.
Home is *not* a meeting and never hosts the full task list.

### Meeting page
Each saved meeting is a page listed in the sidebar below Home, in the spirit of
a Notion page. Selecting one brings that meeting **into focus** and opens its
**Current-meeting intelligence** view.

### In focus
A single meeting is "in focus" when its meeting page is the open surface.
Intelligence views and the meeting/intelligence switch are only meaningful while
a meeting is in focus.

### Current-meeting intelligence
The detailed analysis of the single meeting currently in focus (summary,
decisions, action items, sentiment, etc.). Not a sidebar item — reached by
opening a meeting page.

### Cross-meeting intelligence
Aggregate analysis spanning meetings in the active scope (trends, decision
memory, owner load, etc.). Not a sidebar item — reached via the **intelligence
switch** while a meeting is in focus.

### Intelligence switch
The control in the **center of the topbar** that toggles the focused meeting
between its **Current-meeting intelligence** and **Cross-meeting intelligence**
views. Disabled (grayed) whenever no meeting is in focus.

### Trend
A pinned sidebar page showing **Cross-meeting intelligence** for the active
scope. (Supersedes the original design where cross-meeting views were reachable
only via the topbar intelligence switch — see ADR 0002.)

### Task hub
The canonical, central list of open action items across the active scope. Lives
on the **Trend** page, co-headline with the health graph (no tabs, no separate
page). Every other task surface (Home, meeting pages) is a preview or slice
that leads here.

### Task priority
ONE ranking, used identically by every task surface (Home's Needs-attention
feed and the Trend Task hub): live due urgency first (**overdue**, then **due
soon**), then ownership tiers among the equally urgent (**yours → unowned →
teammates'**), then **recency** of the source meeting (newest first). The hub's
Yours | All | Unassigned chips are filters layered on top of this order. A
stale deadline (>14 days past) is history, not urgency. (Amended Aug 2026 —
ownership was briefly filter-only; the state-aware Home redesign restored it
as a tier below urgency.)

### New meeting
The action that starts a new analysis (paste / upload / record / bot).

### Chat
The assistant panel docked at the bottom-right, for asking questions about
meetings and triggering agent/global actions.

### Present / Presentation (live bot)
The live meeting bot screensharing its owner's **AI workspace** into the call
while narrating and driving it. Presenting is asked for in workspace meetings by
any workspace member, in personal meetings by the owner only; **anyone** in the
call can stop it. One presentation per bot at a time.

### AI workspace
A user's persistent cloud **browser** (a managed Browserbase session), logged
into their own web apps (GitHub, Figma, dashboards), that the bot presents from
and drives. Owned by exactly one user — teammates share the *content* (a common
repo), never the workspace or its logins. Split into two parts:
- a **Context** — the durable, per-user profile (cookies, logins) that persists
  across meetings; the user logs in once via "Set up my AI workspace";
- a **Session** — an ephemeral browser instance bound to the Context, created
  per presentation and torn down after (so there's no idle cost between meetings).
_Avoid_: "sandbox" / "desktop" — the earlier E2B Linux-desktop design was
replaced by a browser-first one (see ADR 0003).

## Flagged ambiguities
- "Sandbox" originally meant an E2B Linux desktop (persistent, pause/resume).
  The AI workspace is now a **browser** (Browserbase Context + ephemeral
  Session). Use "AI workspace", "Context", or "Session" — not "sandbox".

## Design language

Canonical visual identity (do not drift):

- **Accent:** cyan / sky — `#22d3ee`, `#67e8f9`, Tailwind `sky-*` / `cyan-*`.
- **Type:** Inter (body/UI default), Poppins (landing hero/H2 only),
  Satoshi (logo wordmark only). No other font families.
- **Surfaces:** shadcn / radix-style product surfaces on the dark base.
  Glass treatment is an *accent only* (CTAs, focused highlights, special
  moments) — never the default surface language for dashboard chrome.
