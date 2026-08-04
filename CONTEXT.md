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
Scope-aware. Answers "what's next and what happened": greeting + start/join
actions, **next meetings** (upcoming calendar events), a slim **task strip**
(count of open tasks linking to the Task hub — a door, never a list), and the
recent-meetings overview. Home is *not* a meeting and never hosts the full
task list.

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
The hub's ranking: live due urgency first (**overdue**, then **due soon**),
then **recency** of the source meeting (newest first); undated tasks from old
meetings rank last. **Ownership is a filter** (Yours | All | Unassigned) with
the viewer's own rows highlighted — never a sort tier. A stale deadline (>14
days past) is history, not urgency.

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
