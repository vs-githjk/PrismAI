# PrismAI — MCP Tool-Calling Layer Implementation Plan

> Hand this to a new Claude session along with the codebase. Read PRISM_AI_CONTEXT.md first for full architecture context.

---

## Goal

Transform PrismAI's chat from a read-only Q&A into an **agentic chat** that can take real actions — send emails, read Slack, create tickets, schedule meetings — by giving the LLM access to tools it can call during conversation.

---

## Current State

- Chat backend: `backend/chat_routes.py` — `POST /chat` (single meeting context), `POST /chat/global` (cross-meeting)
- LLM: Groq API, LLaMA 3.3-70B (`groq.AsyncGroq`)
- LLaMA 3.3-70B supports **tool/function calling** via Groq's API
- Existing integrations (export-only, no read): Slack webhook, Notion API, Google Calendar, Gmail (draft only via email_drafter agent)
- Auth: Supabase Auth, Google OAuth tokens stored in `user_settings` table

---

## Architecture

```
User message
    ↓
POST /chat (or /chat/global)
    ↓
LLM called with:
  - system prompt (meeting context)
  - conversation history
  - tools[] array (available actions)
    ↓
LLM responds with either:
  A) text response → return to user
  B) tool_calls[] → execute tools → feed results back to LLM → get final response
    ↓
Return final response to user
```

### Tool Execution Loop

```python
# Pseudocode for the tool-calling loop
messages = [system, ...history, user_message]
tools = get_available_tools(user_id)

while True:
    response = await groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        tools=tools,
    )
    
    if response.choices[0].finish_reason == "tool_calls":
        for tool_call in response.choices[0].message.tool_calls:
            result = await execute_tool(tool_call.function.name, tool_call.function.arguments, user_id)
            messages.append(response.choices[0].message)  # assistant's tool_call
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(result)})
        continue  # let LLM process tool results
    
    break  # text response, return to user

return response.choices[0].message.content
```

---

## Implementation Phases

### Phase 1: Tool-calling infrastructure (do this first)

**Files to create/modify:**

1. **`backend/tools/registry.py`** — Tool registry
   - Define tools as dicts matching Groq's function-calling schema
   - Each tool: `name`, `description`, `parameters` (JSON Schema), `handler` (async function)
   - `get_available_tools(user_id)` — returns tools based on what the user has connected
   - `execute_tool(name, args, user_id)` — dispatches to handler, returns result

2. **`backend/chat_routes.py`** — Modify `/chat` and `/chat/global`
   - Import tool registry
   - Add tool-calling loop (see pseudocode above)
   - Cap at 3 tool calls per turn to prevent runaway loops
   - Return tool actions taken alongside the response so frontend can show them

3. **Frontend: `ChatPanel.jsx`** — Show tool usage
   - When response includes `tools_used`, render small badges/chips showing what actions were taken
   - e.g., "Sent email to team" chip, "Read #engineering" chip

**Response format change:**
```json
{
  "reply": "I've sent the follow-up email to the team.",
  "tools_used": [
    { "tool": "gmail_send", "summary": "Sent email: 'Q2 Planning Follow-up' to alice@co.com, bob@co.com" }
  ]
}
```

### Phase 2: Gmail (send + read)

**Why first:** You already have Google OAuth tokens in `user_settings`. You already draft emails. Adding "send" is the smallest leap.

**Files:**
- `backend/tools/gmail.py`

**Tools to implement:**
```
gmail_send:
  description: "Send an email on behalf of the user"
  parameters: { to: string[], subject: string, body: string }
  requires: Google OAuth token with gmail.send scope

gmail_read:
  description: "Read recent emails, optionally filtered by sender or subject"
  parameters: { query?: string, max_results?: number }
  requires: Google OAuth token with gmail.readonly scope
```

**OAuth scope changes needed:**
- Add `gmail.send` and `gmail.readonly` to the Google OAuth consent screen
- Update the OAuth flow in `calendar_routes.py` (or create a unified Google OAuth flow)
- Store tokens are already in `user_settings` — just need broader scopes

**Google API endpoints:**
- Send: `POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send`
- List: `GET https://gmail.googleapis.com/gmail/v1/users/me/messages`
- Get: `GET https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}`

### Phase 3: Slack (read + post)

**Why second:** You already have Slack webhook export. Reading Slack channels adds major value — "what did Jake say in #engineering about auth?"

**Files:**
- `backend/tools/slack.py`

**Tools to implement:**
```
slack_read_channel:
  description: "Read recent messages from a Slack channel"
  parameters: { channel: string, limit?: number }
  requires: Slack Bot Token (OAuth)

slack_post_message:
  description: "Post a message to a Slack channel"
  parameters: { channel: string, text: string }
  requires: Slack Bot Token (OAuth)

slack_search:
  description: "Search Slack messages across channels"
  parameters: { query: string, limit?: number }
  requires: Slack Bot Token (OAuth)
```

**Setup needed:**
- Create a Slack App with Bot Token Scopes: `channels:history`, `channels:read`, `chat:write`, `search:read`
- Add Slack OAuth flow (similar to Google Calendar PKCE flow)
- Store `slack_bot_token` in `user_settings`
- Slack API: `https://slack.com/api/conversations.history`, `https://slack.com/api/chat.postMessage`

### Phase 4: Google Calendar (create events)

**Files:**
- `backend/tools/calendar.py`

**Tools:**
```
calendar_create_event:
  description: "Create a calendar event / schedule a follow-up meeting"
  parameters: { title: string, start: string (ISO), end: string (ISO), attendees?: string[], description?: string }
  requires: Google OAuth with calendar.events scope

calendar_list_events:
  description: "List upcoming calendar events"
  parameters: { days_ahead?: number }
  # Already implemented in calendar_routes.py — just wrap it
```

### Phase 5: Linear/Jira (create tickets)

**Files:**
- `backend/tools/linear.py` (or `jira.py`)

**Tools:**
```
linear_create_issue:
  description: "Create a Linear issue from an action item"
  parameters: { title: string, description?: string, team?: string, assignee?: string, priority?: number }
  requires: Linear API key or OAuth token
```

---

## Key Design Decisions

### Safety: Confirmation for destructive actions
Some tools should require user confirmation before executing:
- `gmail_send` — always confirm (show draft, user clicks "Send")
- `slack_post_message` — always confirm
- `calendar_create_event` — always confirm
- Read operations — no confirmation needed

**Implementation:** Tool handler returns `{ requires_confirmation: true, preview: {...} }` instead of executing. Frontend shows a confirmation card. User clicks confirm → `POST /chat/confirm-tool` → executes.

### Tool availability
Only show tools the user has connected:
- No Slack token → don't include slack tools in the tools array
- No Gmail scope → don't include gmail tools
- This prevents the LLM from trying to use unavailable tools

### Rate limiting
- Max 3 tool calls per chat turn
- Max 10 tool calls per minute per user
- Prevent the LLM from going on a tool-calling spree

---

## File Structure After Implementation

```
backend/
├── tools/
│   ├── __init__.py
│   ├── registry.py      # Tool registration, dispatch, schema
│   ├── gmail.py          # Gmail send/read
│   ├── slack.py          # Slack read/post/search
│   ├── calendar.py       # Calendar create event (wraps existing)
│   └── linear.py         # Linear issue creation
├── chat_routes.py        # Modified: tool-calling loop
└── ... (existing files unchanged)
```

---

## Example User Interactions After Implementation

```
User: "Send the follow-up email to alice@company.com and bob@company.com"
→ LLM calls gmail_send with the drafted email
→ Shows confirmation card
→ User confirms → email sent

User: "What did the engineering team discuss about the auth migration in Slack?"
→ LLM calls slack_search({ query: "auth migration" })
→ Returns relevant messages
→ LLM summarizes findings

User: "Create a Linear ticket for each action item from this meeting"
→ LLM calls linear_create_issue 3x (one per action item)
→ Returns links to created tickets

User: "Schedule the follow-up meeting for next Thursday at 2pm"
→ LLM calls calendar_create_event
→ Shows confirmation card with event details
→ User confirms → event created
```

---

## Getting Started

1. Start with Phase 1 (infrastructure) — get the tool-calling loop working in `/chat` with a single dummy tool (e.g., `get_current_time`)
2. Test the loop end-to-end: user message → LLM decides to call tool → tool executes → LLM responds with result
3. Then add Gmail (Phase 2) since OAuth plumbing already exists
4. Each subsequent phase follows the same pattern: write handler, register tool, done
