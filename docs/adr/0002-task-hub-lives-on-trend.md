# 2. The task hub lives on Trend, co-headline with the graph

Date: 2026-08-04

## Status

Accepted — supersedes ADR 0001 (Intelligence views are meeting-scoped)

## Context

ADR 0001 made cross-meeting intelligence reachable only via the topbar switch
while a meeting was in focus. The product outgrew that: a top-level **Trend**
sidebar page shipped, and the team's B2C direction (Aug 2026) demands a central
place to see open tasks without digging through meetings — "as prominent as the
graph." Three shapes were considered: a tabbed Trend (Trends | Tasks), a
tasks-first Trend with the graph demoted, and a standalone Action Items page
(which briefly existed).

## Decision

- **Trend is a top-level sidebar destination** (this formally supersedes
  ADR 0001's "no other entry point" rule).
- The **Task hub** — the canonical list of open action items for the active
  scope — lives ON the Trend page, **co-headline with the health graph**. No
  tabs, no standalone tasks page.
- **Task priority**: live due urgency first (overdue → due soon), then recency
  of the source meeting; ownership (Yours | All | Unassigned) is a filter with
  the viewer's rows highlighted, never a sort tier. Stale deadlines (>14 days
  past) are history, not urgency.
- Every other task surface is a slice that routes here: Home carries only a
  one-line task-count strip; meeting pages show only their own items.

## Amendment (2026-08-04, state-aware Home)

Adopted one day later with the state-aware Home redesign:

- **Task priority is amended** to: urgency (overdue → due soon) → ownership
  tiers among equals (yours → unowned → teammates') → source-meeting recency.
  ONE order, used identically by every surface; the hub chips remain filters.
- **Home's strip becomes the "Needs-attention feed"** — still a bounded slice
  (top 3–5 tasks + top 2–3 unresolved threads + "View all tasks → hub"), never
  a second full task surface. The hub on Trend remains canonical.
- Home's hero is **state-aware** (live → starting soon → next meeting → compact
  empty row) beneath a one-line greeting; "View context" opens the workspace
  Brief (hidden for personal meetings); Send Stand-in is a first-class action.
- The standalone Action Items page is removed; its grouped-list UI is recycled
  as the hub's list.

## Consequences

- One canonical answer to "what do I need to do", one click from anywhere.
- Tabs were rejected because a hidden tab is exactly the buried UI the
  redesign exists to eliminate; tasks-first was rejected because it demotes
  the graph the page is named for.
- Home stays lightweight (upcoming meetings + a count), betting that
  next-meetings is the landing page's job and tasks are Trend's job.
- Reversal cost: information architecture, sidebar, Home, and Trend all encode
  this — hence this record.

## Amendment (2026-08-08, north-star migration)

The location decision is superseded by the approved north-star direction
(docs/superpowers/specs/2026-08-08-prism-north-star-frontend-migration-design.md):
the full Task hub moves from Trend to a standalone top-level **Actions** page,
and Trend keeps a compact open-task summary that links to it. Everything else
in this record stands — `byPriority` remains THE one task order used
identically by every surface, ownership chips remain filters, and stale
deadlines remain history, not urgency.
