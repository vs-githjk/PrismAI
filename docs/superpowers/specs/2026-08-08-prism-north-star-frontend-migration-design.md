# Prism North-Star Frontend Migration Design

**Date:** 2026-08-08  
**Status:** Approved for implementation  
**North star:** the isolated `prism-redesign-demo`, especially its matte graphite shell, content-rich sidebar, two-column Home, standalone Actions surface, and source-grounded Meeting record.

## Goal

Move the approved north-star visual and structural direction into the real Prism frontend without replacing Prism's production data, authentication, integrations, meeting analysis, chat tools, workspace controls, or live-meeting behavior.

## Product decisions

1. The redesign is a migration of the real React application, not a transplant of the demo. Demo fixtures, scenario controls, review banners, story parameters, and simulated receipts never enter production.
2. Actions returns as a top-level destination. Trend remains a separate cross-meeting intelligence destination. This supersedes the “no standalone tasks page” decision in ADR 0002 while preserving its single ranking algorithm and shared task components.
3. The approved dark interface is the primary design. Prism's existing light-theme control remains functional; it uses equivalent matte tokens rather than being removed.
4. Existing callbacks and data contracts remain stable during visual migration. The redesign must not rewrite analysis streaming, meeting persistence, workspace scoping, calendar connections, integrations, auth, Live, Stand-in, or Knowledge behavior.
5. Work ships in vertical slices. Each slice must leave a usable product rather than a partially transplanted shell.

## Visual direction

Prism becomes a restrained, operational workspace rather than a collection of floating glass cards.

- **Tone:** refined, matte, content-dense, calm.
- **Canvas:** charcoal-black with low-contrast tonal separation.
- **Surfaces:** solid or very shallow gradients; glass is reserved for focused or transient moments.
- **Accent:** cyan is reserved for selection, primary action, focus, and provenance.
- **Typography:** Inter for product UI, with tighter tracking and stronger hierarchy rather than decorative type.
- **Shape:** 12–18px radii, thin neutral borders, compact navigation rows, generous whitespace around the principal content.
- **Motion:** one restrained page entrance and short state transitions, disabled under reduced motion.

The memorable composition is the split Home: operational context on the left and a tall, source-aware Prism assistant on the right.

## Information architecture

The desktop sidebar contains, in order:

1. Workspace switcher.
2. Home.
3. Actions with the open-task count.
4. Trend.
5. Calendar.
6. Knowledge.
7. Stand-in.
8. Live session when present.
9. Meetings grouped by the existing date ladder.
10. Account and settings.

The topbar contains the page title/back control, contextual meeting actions, global meeting search, notifications, and responsive navigation entry. It does not contain demo-only Current/Proposed or scenario controls.

Dashboard navigation continues to use the existing `activeView` state and session persistence. Adding `actions` removes the current compatibility rewrite from `actions` to `intelligence`; no React Router migration is included.

## Screen designs

### Home

Home is a two-column workspace on wide screens and a single flow on narrow screens.

The operational column contains:

- time-aware greeting and a short product promise;
- inline capture actions for Join, Paste, Upload, and Record, all invoking the existing New Meeting workflow;
- the existing state-aware Meeting hero, visually recomposed as the primary operational card;
- a bounded Needs-attention preview using the canonical action ranking;
- a compact recent-meetings continuation or onboarding guidance.

The assistant column contains a Home-specific `WorkspaceChatPanel`. It asks across saved meetings via the existing global-chat endpoint, shows source/tool context returned by the server, and does not mutate a focused meeting. Until the backend supports active-workspace filtering for `/chat/global`, its header truthfully says “Across your saved meetings” rather than claiming it is limited to the selected workspace.

The existing meeting-specific `ChatPanel` remains unchanged in behavior and stays scoped to a focused meeting.

### Actions

Actions is the canonical execution surface for open action items in the active scope.

- It reuses `collectOpenActions`, `byPriority`, `scopeFilter`, `ActionItemRow`, and existing toggle handlers.
- One queue surface contains grouped/divided rows rather than a card per group.
- Filters remain All, Yours, and Unassigned.
- A contextual rail explains ranking, totals, and current pressure without inventing completion or provider state.
- Opening a source routes to the exact Meeting page.

Trend keeps health, semantic topics, open threads, decision evolution, and other cross-meeting intelligence. It no longer owns the full Task hub; it may retain a compact task summary that links to Actions.

### Meeting

The Meeting page becomes a source-grounded record while retaining every current production card and edit/export workflow.

- The title, date, attendees, sharing, moving, export, and back controls remain.
- TL;DR/summary becomes the strongest record surface.
- Actions and decisions form the primary work grid and preserve linked-decision/source behavior.
- Sentiment, health, recording, transcript, documents, presentation, content analysis, email, calendar, and deeper analysis remain available below or within disclosures; none are deleted.
- The existing meeting `ChatPanel` is visually aligned with the new shell after the record migration, but its persistence and mutation logic are not rewritten.

### Remaining destinations

Calendar, Knowledge, Stand-in, Live, Shared, Invite, Legal, Profile, integrations, and auth retain their current workflows. Their presentation adopts the same tokens and shell progressively after Home, Actions, and Meeting are stable.

## Component boundaries

### Existing controllers kept stable

- `frontend/src/App.jsx`: auth, analysis, bot, history, sharing, and global product state.
- `frontend/src/components/DashboardPage.jsx`: current view coordination, workspace state, and screen composition.
- Existing API helpers and backend routes.

### Shell components reshaped

- `WorkspaceIsland.jsx`
- `DashboardSidebar.jsx`
- `DashboardTopbar.jsx`
- `frontend/src/index.css`
- `dashboardStyles.js`

### Focused screen components

- Home: `StatsCanvas.jsx`, `MeetingHero.jsx`, `NeedsAttention.jsx`, plus a new `WorkspaceChatPanel.jsx`.
- Actions: a new `ActionsView.jsx`, supported by a presentation-focused update to `TaskHub.jsx` or shared task-list primitives.
- Trend: `IntelligenceView.jsx` changes only enough to remove the full canonical task list and link to Actions.
- Meeting: `MeetingView.jsx` is recomposed after the shell and task migration; its business callbacks remain unchanged.

## Data flow

Production props continue flowing from `App` to `DashboardPage`. `DashboardPage` passes already scope-filtered history and existing action handlers to Home, Actions, Trend, Calendar, and Meeting.

`WorkspaceChatPanel` uses `apiFetch('/chat/global')` and renders only the server response, tool metadata, and grounding context it receives. It does not import mock fixtures, synthesize citations locally, or pretend external tools executed.

The standalone Actions view derives its rows from the same history objects used by Home and Trend. Completing or reopening an item uses the existing `toggleHistoryActionItem` path so `result`, history state, and persisted server state remain synchronized.

## Responsive and accessibility behavior

- At desktop widths, the Home assistant is a fixed-height right column and the operational column scrolls with the page.
- Below the shell breakpoint, the sidebar becomes the existing drawer and Home becomes one column.
- On phones, the Home assistant becomes a full-height sheet opened by a single Ask Prism control; it does not compete with the page for viewport height.
- All visible controls retain at least 44px touch targets where practical, visible focus, Escape dismissal for overlays, and focus restoration.
- Reduced-motion users receive no page or panel transitions.

## Error and empty states

- First run shows concise onboarding guidance and capture controls, never fabricated meetings or actions.
- Loading and errors reuse current application state and `ErrorCard`/skeleton conventions.
- Global chat failures remain in the assistant thread with a retryable message.
- An empty Actions queue says that completed or newly analyzed meeting items will appear there; it does not display fake counts.
- Missing scores render a dash, never zero.

## Rollout

1. Foundation and shell.
2. Complete Home, including the real global assistant.
3. Standalone Actions and Trend separation.
4. Meeting record and meeting chat presentation.
5. Remaining destinations and responsive polish.

Each slice receives an `npm run build` check and a focused browser smoke check. Existing frontend unit tests run when shared action/date/insight utilities change. No backend schema or API change is part of this design.

## Explicit preservation list

The migration must preserve authentication, sample/test mode, light theme, workspace switching/settings/invites, personal and workspace integrations, all capture modes, analysis streaming, meeting history/search/delete/move/share/export, calendar providers, notifications, Knowledge workflows, Stand-in workflows and follow-up briefs, Live and public/shared views, all meeting summary/intelligence cards, recording/transcript/document/presentation features, personas, source-linked action completion, and meeting-scoped chat persistence/tools/corrections.

## Superseded decision

ADR 0002 remains authoritative for the canonical task model and priority order, but its location decision is superseded: the full Task hub moves from Trend to standalone Actions, and Trend links to it.
