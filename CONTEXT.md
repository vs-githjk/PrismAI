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
A pinned sidebar page, always present, that is the default landing surface. It
shows the overview (stats hero + recent-meeting overview). Home is scope-aware:
it reflects the active workspace. Home is *not* a meeting.

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

### New meeting
The action that starts a new analysis (paste / upload / record / bot).

### Chat
The assistant panel docked at the bottom-right, for asking questions about
meetings and triggering agent/global actions.

## Design language

Canonical visual identity (do not drift):

- **Accent:** cyan / sky — `#22d3ee`, `#67e8f9`, Tailwind `sky-*` / `cyan-*`.
- **Type:** Inter (body/UI default), Poppins (landing hero/H2 only),
  Satoshi (logo wordmark only). No other font families.
- **Surfaces:** shadcn / radix-style product surfaces on the dark base.
  Glass treatment is an *accent only* (CTAs, focused highlights, special
  moments) — never the default surface language for dashboard chrome.
