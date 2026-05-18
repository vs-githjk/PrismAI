# 1. Intelligence views are meeting-scoped

Date: 2026-05-16

## Status

Accepted

## Context

The dashboard redesign introduces a Linear-style sidebar + topbar shell. The
sidebar has a pinned **Home** page and a list of **Meeting pages**. Two analysis
surfaces exist: **Current-meeting intelligence** (the detailed analysis of one
meeting) and **Cross-meeting intelligence** (aggregate trends across meetings in
the active scope).

A natural alternative was to make Cross-meeting intelligence a top-level,
always-available destination — e.g. a pinned "Intelligence" item in the sidebar
next to Home, reachable at any time regardless of what is open.

## Decision

Both intelligence views are **meeting-scoped**. Neither is a sidebar item. They
are reached only via an **intelligence switch** in the center of the topbar that
toggles the meeting *currently in focus* between its Current-meeting and
Cross-meeting views. The switch is **disabled (grayed)** whenever no meeting is
in focus (e.g. on Home).

Clickpath to cross-meeting intelligence, stated explicitly:
**open any meeting page → topbar switch flips to "Cross-meeting".**
There is no other entry point.

## Consequences

- Single, consistent mental model: intelligence is always entered from a meeting
  context; the switch only ever has meaning when a meeting is open.
- Home stays a lightweight overview and is not overloaded with a third nav peer.
- Trade-off: a user who wants the cross-meeting aggregate must first open a
  meeting page. This is intentional and was chosen explicitly over a top-level
  Intelligence destination.
- Hard to reverse: changing this later touches information architecture, the
  topbar, and the view-state model simultaneously — hence this record.
