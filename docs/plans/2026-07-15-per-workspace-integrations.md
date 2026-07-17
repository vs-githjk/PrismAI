# Per-Workspace Integrations (#2) — Architecture Plan

**Status:** DRAFT for review · **Date:** Jul 15 2026 · **Owner:** deep-dive Tier 3
**Companion:** `docs/plans/2026-07-15-feature-deep-dive.md` (Tier 3)

## 1. The problem & goal

**Today** integrations are **per-user**: each person connects their own Jira/Linear/Slack/Teams/Notion, stored in `user_settings` keyed by `user_id`. In a team meeting, tickets/messages route to **whoever's bot ran it** — not to the team's shared board/channel. That's wrong for the workspace model: a client workspace's meetings should file into *that client's* Jira and post to *that client's* Slack, regardless of which member's bot recorded.

**Goal:** an **admin (workspace owner) connects an integration once per workspace**, and every action taken in that workspace's meetings routes there — with a **fallback to the acting user's personal integration** when the workspace hasn't configured one. Personal (non-workspace) meetings are unchanged.

**Guiding principle:** *config lives at the level the work belongs to.* A workspace meeting's outputs belong to the workspace.

---

## 2. Current state (grounded)

**Storage** — all in `user_settings` (per `user_id`):
| Provider | Fields | Type |
|---|---|---|
| Jira | `jira_base_url`, `jira_email`, `jira_api_token`, `jira_project_key` | token |
| Linear | `linear_api_key` | token |
| Slack | `slack_bot_token` (tool), `slack_webhook` (export) | token/webhook |
| Teams | `teams_webhook` | webhook |
| Notion | `notion_token`/`notion_access_token`, `notion_page_id` | token |
| Google | `google_*` (calendar + gmail) | **OAuth** |
| Microsoft | `ms_*` (calendar) | **OAuth** |
| flags | `auto_send_slack/notion/teams` | bool |

**Consumption points** (where creds are actually used):
1. **`actions_routes.py`** — Suggested Actions execute → `_get_user_settings(user_id)` → `confirm_and_execute`. Request carries **`meeting_id`** (→ resolvable to a workspace).
2. **`chat_routes.py`** — `/chat`, `/chat/global`, `/agent` → `_get_user_settings(user_id)` → tool loop. Per-meeting chat knows its meeting; global doesn't.
3. **`realtime_routes.py`** — live bot → `_get_settings_for_bot(bot_id)` → tools. The bot **already knows `workspace_id`** (`bot_store[bot_id]["workspace_id"]`).
4. **`export_routes.py`** — Slack/Teams/Notion export take the **webhook/token from the request body** (frontend-routed), *not* server settings.
5. `calendar_routes` / `ms_calendar_routes` / `knowledge_service` — OAuth tokens, per-user by nature.

**Roles** — `workspace_members.role` = `owner | member`; `_require_owner()` already exists. `meetings.workspace_id` (nullable) scopes a meeting. `workspace_id` is **text** in some tables (workspace convention) — cast carefully.

**Key realization:** tool execution routes by *user_id*; export routes by *request body*. Per-workspace needs a **server-side resolver** for (1)(2)(3) and a **frontend routing choice** for (4).

---

## 3. Scope — what's IN vs OUT of v1

**IN (v1):** the **token-based** integrations that actually cause the pain — **Jira, Linear, Slack, Teams, Notion**. These are a fixed secret an admin can paste once.

**OUT (v1, deferred with reason):**
- **Google & Microsoft (Calendar/Gmail)** — these are **OAuth tied to a person's identity**. "Workspace Gmail" means a shared service account + workspace-level OAuth consent — a materially bigger lift (separate OAuth app config, token refresh ownership, consent UX). Calendar/Gmail are also naturally *personal* (your calendar, your sent mail). **Stay per-user in v1.** Revisit only if a real need appears.
- **Knowledge-source tokens** (Notion/Google for doc ingestion) — ingestion is a personal action; leave per-user.

This keeps v1 tractable and hits 100% of the reported pain (Jira/Slack routing).

---

## 4. Data model

New table `workspace_integrations` — **one row per (workspace, provider)**, owner-managed:

```sql
create table if not exists workspace_integrations (
  workspace_id text not null,          -- workspace convention: text, not uuid
  provider     text not null,          -- 'jira' | 'linear' | 'slack' | 'teams' | 'notion'
  config       jsonb not null default '{}'::jsonb,  -- provider-specific creds (see below)
  enabled      boolean not null default true,
  configured_by text,                  -- user_id of the owner who set it (audit)
  updated_at   timestamptz not null default now(),
  primary key (workspace_id, provider)
);
create index if not exists workspace_integrations_ws_idx on workspace_integrations(workspace_id);
```

`config` shapes (mirror the `user_settings` field names so the resolver output is drop-in):
- jira → `{jira_base_url, jira_email, jira_api_token, jira_project_key}`
- linear → `{linear_api_key}`
- slack → `{slack_bot_token, slack_webhook}`
- teams → `{teams_webhook}`
- notion → `{notion_token, notion_page_id}`

**Why a table (not columns on `workspaces`):** per-provider rows keep `enabled` + audit per integration, avoid a wide sparse row, and make the resolver a clean per-provider lookup. **Why `jsonb config`:** adding a provider needs no migration.

**RLS / access:** members can **read** their workspaces' integration *status* (configured/not, provider, account label) but **never the raw secrets**; only the **owner** can write. Enforced in the API layer (service-role key + explicit `_require_owner`), consistent with how `knowledge`/`workspace` routes already gate.

---

## 5. The resolver (the heart of it)

A single function every server-side tool path calls **instead of** `_get_user_settings(user_id)`:

```python
async def resolve_tool_settings(user_id: str, workspace_id: str | None) -> dict:
    """Merge personal + workspace integration creds for tool execution.
    Per-PROVIDER precedence: a workspace's configured+enabled integration wins
    for that provider; otherwise fall back to the user's personal creds.
    OAuth (google_/ms_) always stays personal. Membership-checked."""
    personal = await _get_user_settings(user_id)          # existing loader (keeps OAuth refresh)
    if not workspace_id:
        return personal
    if not await _is_member(user_id, workspace_id):        # defensive: never route a non-member
        return personal
    ws_rows = await _load_workspace_integrations(workspace_id)   # {provider: config} for enabled rows
    merged = dict(personal)
    for provider, cfg in ws_rows.items():
        if _provider_complete(provider, cfg):              # only override if the ws config is usable
            merged.update(cfg)                             # provider fields overwrite personal
    return merged
```

**Design rules:**
- **Per-provider, all-or-nothing** — never field-mix (a workspace `jira_base_url` with a personal `jira_api_token` = broken auth). If the workspace's Jira config is complete+enabled, use it *entirely*; else personal Jira.
- **OAuth untouched** — `google_*` / `ms_*` never come from the workspace in v1; personal only.
- **Fallback is the acting user's personal** — so a workspace with no Jira configured still works exactly like today.
- **Membership-checked** — the resolver refuses to hand a non-member workspace creds (defense-in-depth; the callers are already members, but never rely on that).
- Output is the **same dict shape** `confirm_and_execute` / `get_available_tools` already consume → **drop-in** at every call site.

---

## 6. Threading `workspace_id` into each consumption point

| Point | Has workspace_id? | Change |
|---|---|---|
| **realtime bot** (`_get_settings_for_bot`) | ✅ `bot_store[bot_id]["workspace_id"]` | call `resolve_tool_settings(user_id, ws_id)` |
| **actions execute** | via `meeting_id` → look up `meetings.workspace_id` | resolve meeting→ws, then resolver |
| **chat per-meeting** (`/chat`, `/agent`) | frontend passes `meeting_id`/`workspace_id` (add field) | thread ws_id → resolver |
| **chat global** (`/chat/global`) | ✅ frontend sends `activeWorkspaceId` (App.jsx already has it) | pass through → resolver |
| **export** Slack/Teams/Notion | frontend-routed (creds in body) | see §7 |

For chat/actions, add an optional `workspace_id` to the request models (App.jsx already tracks `activeWorkspaceId`). When present + the caller is a member, route to workspace creds.

---

## 7. Export routing (the frontend-routed path)

Export endpoints take the webhook/token in the body today, so **the client decides**. Two options — **a decision for you** (§11):

- **Option A (server-resolve, recommended for secret hygiene):** add member-gated `POST /workspaces/{id}/export/{slack|teams|notion}` that resolves the workspace webhook **server-side** and posts. The raw webhook **never reaches the browser**. More work; keeps secrets server-only.
- **Option B (client-resolve, faster):** the frontend fetches the workspace's export webhooks (via a GET) and posts them in the body like today. Simpler, but the webhook secret is exposed to every member's browser. Acceptable *only* if we treat webhooks as low-sensitivity + members-are-trusted.

**Recommendation: A for tokens/bot-tokens (Slack bot token, Jira token — never leave the server), and A for export webhooks too** to avoid any client secret exposure. The auto-send-on-analysis flags then also read the workspace config server-side.

---

## 8. UI

**IntegrationsModal gains a scope switcher** at the top: `Personal | <Workspace A> | <Workspace B>`.
- **Personal** — exactly today's per-user config.
- **Workspace X** — visible to all members; **editable only by the owner** (members see a read-only "Configured by the workspace · <account label>" + can run "Test connection", but fields are disabled with a "Only the workspace owner can change this" note).
- Reuse the **§8 "Test connection"** buttons (already built for Jira/Linear) against whichever scope is active.
- A small badge on each provider tab: "Personal" / "Workspace" so it's always clear where a save lands.
- Entry from the workspace settings panel too ("Integrations" link), not only the account menu.

**Transparency win:** on a meeting's Suggested Actions / ticket-filing, show where it routed ("→ Acme workspace Jira") — so users *see* the routing, tying into the deep-dive transparency lens.

---

## 9. Security & permissions

- **Writes:** owner-only (`_require_owner(workspace_id, user_id)` — already exists).
- **Secrets never to the client:** raw tokens/webhooks stay server-side; the GET returns only **status + a masked account label** (e.g. "Jira: connected as Acme (PROJ)"), never the token. (This is why §7 Option A matters.)
- **Resolver membership check** — never route workspace creds for a non-member (defense-in-depth).
- **Audit:** `configured_by` + `updated_at` on each row; optionally log routed executions (which scope) into `action_refs`.
- **Blast radius:** an owner rotating a bad token fixes it for the whole workspace in one place (a *reliability* win too).

---

## 10. Migration & rollout

- **Migration:** additive — create `workspace_integrations` (supabase migration #24; **not** in `schema.sql` boot path, so manual like the proxy tables — or add to `schema.sql` if we want auto-apply). No backfill (personal configs stay personal).
- **Backward compatible:** with zero workspace_integrations rows, `resolve_tool_settings` == `_get_user_settings` → **behavior identical to today**. Ship dark, enable per-workspace as owners configure.
- **Flag:** `PRISM_WORKSPACE_INTEGRATIONS` (default ON once tested) gating the resolver's workspace branch, so we can fall back instantly.
- **Phasing within v1:** (a) table + resolver + realtime-bot path (the highest-value: team meetings) → (b) actions + chat paths → (c) export server-resolve → (d) UI scope switcher. Each shippable independently behind the flag.

---

## 11. Decisions — LOCKED (Jul 16 2026)

1. ✅ **Export secrets = Option A (server-resolve).** Add member-gated `POST /workspaces/{id}/export/{slack|teams|notion}` that resolves the workspace webhook server-side; the raw secret never reaches the browser. Bot tokens (Slack/Jira) likewise stay server-only.
2. ✅ **Google/MS stay per-user in v1.** OAuth = personal identity; workspace OAuth deferred.
3. ✅ **Fallback to the acting user's personal creds** when the workspace hasn't configured that provider (= today's behavior; no surprise hard-stops).
4. ✅ **Full v1 provider set:** Jira + Linear + Slack + Teams + Notion.
5. ✅ **Migration = manual supabase file** (like the proxy tables), user runs it. See §10 / migration #24.

---

## 12. Testing

- **Resolver unit tests:** no ws_id → personal; ws with complete Jira → workspace Jira; ws with incomplete Jira → personal fallback; non-member → personal; OAuth never overridden.
- **Routing integration:** actions/chat/bot with a workspace meeting hit the workspace creds (mock the tool, assert which config it received).
- **Permission tests:** member write → 403; owner write → 200; member GET returns masked labels, never raw tokens.
- **Backward-compat:** zero ws rows → identical to current behavior.

---

## 13. Effort estimate

~**3–4 focused days**: table+resolver+tests (0.5d) · thread the 3 tool paths (1d) · export server-resolve (0.5–1d) · UI scope switcher + owner gating + masked GET (1d) · e2e + polish (0.5d). Shippable in flag-gated slices.
