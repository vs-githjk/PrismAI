# PrismAI QA Sweep Checklist

Last updated: 2026-04-20

This checklist is for a full product pass on the deployed app.

Goal:
- verify that the core product works end to end
- catch regressions across auth, analysis, persistence, integrations, and mobile
- log both broken behavior and UX friction

Recommended environments:
- desktop Chrome
- desktop Safari
- mobile Safari or Chrome DevTools device mode

Recommended accounts:
- one signed-in Google account with Calendar connected
- one signed-out / anonymous session

### Before sweeping — run pending migrations

Run these in Supabase SQL Editor if not already applied (in order):

1. `supabase/auth_migration.sql`
2. `supabase/calendar_migration.sql`
3. `supabase/tools_migration.sql`
4. `supabase/bot_commands_migration.sql` ✓ applied Apr 20
5. `supabase/chats_unique_migration.sql` — **run before this sweep** (required for chat persistence fix)

---

## How To Use This Checklist

For each item:
- mark `Pass`, `Fail`, or `Needs polish`
- if it fails, note:
  - exact screen
  - exact action
  - what happened
  - what you expected
  - screenshot if useful

Suggested issue format:

```md
### Issue
- Area:
- Steps:
- Expected:
- Actual:
- Severity:
- Screenshot:
```

---

## 1. Landing Page

### 1.1 First load
- Open the production app in a fresh browser session.
- Confirm the landing page loads without layout breaks.
- Confirm the hero fits reasonably above the fold on a common laptop viewport.
- Confirm the CTA buttons are visible and readable.
- Confirm the page does not feel visually broken on mobile.

Expected:
- no overlapping sections
- no clipped CTA
- no missing logo or header

### 1.2 Landing CTA flow
- Click `See it in action`.
- Confirm demo mode opens correctly.
- Return to landing and click `Use my own transcript`.
- Confirm the real workspace opens correctly.

Expected:
- demo and real-workspace paths are clearly different
- no stale demo state appears in the real workspace

---

## 2. Auth

### 2.1 Sign in
- From the workspace, click `Sign in`.
- Complete Google sign-in.
- Confirm you return to the app successfully.
- Confirm signed-in UI appears in the header.

Expected:
- no blank screen
- no auth loop
- no silent failure

### 2.2 Sign out
- Click `Sign out`.
- Confirm signed-in UI disappears.
- Confirm `Sign in` returns.
- Confirm the app clearly shows local-only state when signed out.

Expected:
- signed-out state is obvious
- no stale signed-in data lingers in the header

### 2.3 Signed-out persistence rule
- While signed out, paste a transcript and analyze it.
- Refresh the page.

Expected:
- the local workspace should not behave like saved account history
- signed-out state should remain local-only

### 2.4 Signed-in persistence rule
- While signed in, analyze a meeting.
- Refresh the page.
- Check History.

Expected:
- meeting should be saved to your account
- history should reload correctly

---

## 3. Transcript Workspace

### 3.1 Paste Transcript
- Open `Paste Transcript`.
- Confirm the empty-state transcript area is clear and readable.
- Paste a transcript with named speakers.
- Confirm stats update.
- Confirm `Analyze Meeting` is clearly visible.

Expected:
- transcript box feels usable
- analyze CTA is easy to find

### 3.2 Record Audio
- Switch to `Record Audio`.
- Confirm the transcript does not incorrectly reuse the pasted sample unless intentionally preserved for that tab.
- Start and stop recording.

Expected:
- record tab has its own state
- no transcript leakage from other tabs unless designed

### 3.3 Upload Audio
- Switch to `Upload Audio`.
- Upload a valid audio file.
- Confirm transcription appears.

Expected:
- upload/transcription flow works
- clear status while transcribing

### 3.4 Join Meeting tab
- Switch to `Join Meeting`.
- Confirm join UI is clear.
- If Calendar is connected, confirm upcoming-meeting support appears where expected.

Expected:
- join flow is understandable
- no dead or confusing controls

---

## 4. Demo Mode

### 4.1 Demo load
- Click `See it in action`.
- Confirm demo sample loads correctly.
- Confirm the right side shows a polished sample state.

Expected:
- demo content appears consistently
- no broken cards or missing data

### 4.2 Demo exit
- While demo is loading or visible, click `Use my own transcript`.
- Confirm demo state clears.
- Confirm the real workspace is clean.

Expected:
- no stale demo analysis remains
- no demo banner or sample data lingers unexpectedly

### 4.3 Demo chat
- Confirm demo chat is collapsed by default.
- Open it manually.

Expected:
- left panel stays calmer by default
- demo chat opens intentionally

---

## 5. Analysis Flow

### 5.1 Analyze transcript
- Paste a realistic transcript and click `Analyze Meeting`.
- If the speaker-role modal appears, test both:
  - complete it
  - skip it

Expected:
- analysis starts in both cases
- skip remains optional

### 5.2 Streaming / results
- Confirm agent results appear correctly.
- Confirm summary, action items, decisions, sentiment, email draft, calendar, and health score render.
- Confirm no placeholder result like `0` health / `Pending` appears unless the transcript truly lacks content.

Expected:
- no partial placeholder state is saved as a “real” result

### 5.3 Save behavior
- Signed in: confirm result saves to history.
- Signed out: confirm result remains local-only.

---

## 6. History

### 6.1 Load history
- Open `History`.
- Confirm meetings load.
- Open multiple saved meetings.

Expected:
- only your signed-in meetings appear
- loading a saved meeting restores transcript, results, and chat

### 6.2 Recent meeting continuity
- Confirm the left panel shows recent meeting pills when applicable.
- Click one.

Expected:
- it loads the selected meeting cleanly

---

## 7. Chat

### 7.1 Post-analysis chat
- Analyze a meeting.
- Ask follow-up questions in chat.

Expected:
- chat responds meaningfully to the current meeting

### 7.2 Chat persistence
- Signed in: ask questions, refresh, reload that meeting.

Expected:
- chat history persists for that meeting

> **Requires `chats_unique_migration.sql` applied first.** If not run, chat saves will error silently.

### 7.3 Signed-out chat
- Signed out: confirm chat behavior is appropriate for local-only use.

Expected:
- no misleading saved-history behavior

---

## 8. Sharing And Export

### 8.1 Share button
- After a real analysis, click the normal share controls.
- Click the green time-saved `Share` button if present.

Expected:
- it should do something visible
- copy/share feedback should appear

### 8.2 Share link
- Open the generated share link in:
  - desktop
  - mobile

Expected:
- shared recap view loads correctly
- mobile share page is readable

### 8.3 Export
- Test markdown / export options.
- If Slack/Notion are connected, test export actions.

Expected:
- export succeeds or fails clearly

### 8.4 Notion export — large meeting
- Export a meeting with a long transcript (ideally one with many action items, decisions, and a full summary).
- Open the Notion page and scroll to the bottom.

Expected:
- all content is present, not truncated at roughly the first 100 blocks
- previously large meetings would silently cut off here

---

## 9. Slack / Notion Auto-Send

### 9.1 Integration settings
- Open `Integrations`.
- Confirm Slack and Notion settings are readable.
- Toggle auto-send recap options.

Expected:
- settings save
- no broken controls

### 9.2 Real meeting recap delivery
- Run a real meeting analysis while auto-send is enabled.

Expected:
- recap sends automatically after analysis completes
- demo runs should not auto-send

### 9.3 Auto-deliver dedup — same title, same score
- Run two separate meetings that produce the same title and similar health score.
- Both should trigger auto-delivery independently.

Expected:
- both deliveries fire (each meeting's ID is now used as the dedup key, not title+score)
- previously the second delivery would be silently skipped

---

## 10. Google Calendar / Upcoming Meetings / Auto-Join

### 10.1 Calendar connection
- Open `Integrations`.
- Connect Google Calendar.

Expected:
- connection succeeds
- connected state is visible

### 10.1a Calendar tool with calendar NOT connected
- While calendar is disconnected, type a calendar command in chat (e.g. "schedule a follow-up for tomorrow").

Expected:
- receive a readable error message like "Calendar not connected"
- previously this returned a silent 500 error

### 10.2 Next-up strip
- With calendar connected and an upcoming meeting available, confirm the left panel shows a `Next up` strip.

Expected:
- meeting title is readable
- timing looks correct
- `Join` action is available if relevant

### 10.3 Upcoming meetings panel
- Open the `Join Meeting` flow and inspect upcoming meetings.

Expected:
- events load
- meeting links are detected for supported providers

### 10.4 One-click join
- Use `Join with PrismAI` from an upcoming event.

Expected:
- join flow starts without manually pasting a link

### 10.4a Calendar event creation timezone
- With calendar connected, ask Prism to create a calendar event via chat (e.g. "schedule a sync tomorrow at 2pm").
- Check the created event in Google Calendar.

Expected:
- event time is correct — not shifted by Eastern Time offset
- previously the default was hardcoded to America/New_York

### 10.5 Auto-join
- If auto-join rules are enabled, verify behavior:
  - `ask`
  - `auto`
  - `marked`

Expected:
- prompts or joins happen according to the selected rule
- no surprise joins outside the rule

---

## 11. Recall / Live Meeting Bot

### 11.1 Manual join by URL
- Paste a meeting URL manually.
- Start join flow.

Expected:
- bot joins correctly
- status updates are readable

### 11.2 Post-meeting transcript return
- End the meeting.

Expected:
- transcript returns
- result either auto-analyzes or clearly offers analysis

---

## 12. Cross-Meeting Intelligence

### 12.1 Insights visibility
- Signed in with multiple saved meetings, confirm the intelligence surface appears.

Expected:
- recurring blockers
- resurfacing decisions
- ownership drift
- action hygiene signals

### 12.2 Actionability
- Click insight items.

Expected:
- related meetings open or the signal becomes inspectable

---

## 13. Mobile

### 13.1 Header
- Verify header is not covered or broken on mobile.

### 13.2 Analyze CTA
- Confirm `Analyze Meeting` is always accessible on mobile input flows.

### 13.3 Tabs / transitions
- Confirm mobile input/results switching feels intentional.

### 13.4 Share page
- Open a shared recap on mobile.

Expected:
- readable layout
- no clipped cards

---

## 14. Visual / UX Polish Review

Mark anything that feels:
- cluttered
- repetitive
- unclear
- too hidden
- awkward on common laptop sizes
- strong enough to keep as-is

Focus especially on:
- left workspace panel
- demo mode
- landing page fit
- results header
- sign-in/save cues

---

## 15. Final Signoff Questions

Before calling the product ready to pitch:

- Does the app feel trustworthy?
- Does the difference between local-only and signed-in persistence feel clear?
- Is the main workflow obvious for a first-time user?
- Does the product feel more than “just a meeting summarizer”?
- Would you feel comfortable demoing this live without apologizing for UX rough edges?

---

## Post-QA Triage Buckets

Use these buckets after the sweep:

### Must fix now
- broken flows
- data loss
- auth regressions
- share/export failure
- join/Recall failure

### Fix soon
- cramped layouts
- confusing copy
- unclear save/sync messaging
- mobile awkwardness

### Nice to have
- visual polish
- stronger landing story
- richer micro-interactions
- additional product delight
