"""In-memory per-present token service — Phase 2 of Bot Screen Presentation.

Spec: docs/specs/2026-07-07-bot-screen-presentation-design.md ("Wrapper page":
rotating per-present tokens, not a permanent URL).

A present token is the capability to VIEW one presentation's sandbox stream. It
is minted when a present starts and revoked when it ends, so a chat-posted
fallback link or a screen-scraped URL is worthless the moment the present is
over — no one can reopen the owner's desktop later.

ponytail: this store is in-memory ONLY, mirroring `bot_store` in
recall_routes.py. A Render restart wipes every active token — which is fine: a
restart also wipes `bot_store`, the live bot session, and the Recall
`output_media` that the token fronted, so the present it pointed at is already
dead. A token that outlived them would front nothing anyway.

SECURITY: each entry holds a SandboxRef whose `auth_key` IS the noVNC password.
This store's contents must NEVER be logged (no entry dumps, no ref repr, no url
built from it in a log line).
"""

import secrets
import time
from typing import Optional

from sandbox import SandboxRef

# token -> {ref: SandboxRef, view_only: bool, expires_at: float, bot_id: str|None}
_tokens: dict[str, dict] = {}


def mint_present_token(
    ref: SandboxRef,
    view_only: bool = True,
    ttl_s: int = 3600,
    bot_id: Optional[str] = None,
) -> str:
    """Mint an opaque token for one presentation and stash its stream ref.

    `view_only` selects which provider URL /present/{token}/vnc hands back (view
    URL vs interactive URL). `bot_id` lets Phase 3 revoke every token for a bot
    when its present ends (see revoke_for_bot)."""
    token = secrets.token_urlsafe(32)
    _tokens[token] = {
        "ref": ref,
        "view_only": bool(view_only),
        "expires_at": time.time() + ttl_s,
        "bot_id": bot_id,
    }
    return token


def resolve_present_token(token: str) -> Optional[dict]:
    """Return the token's entry, or None if it is missing or expired.

    Expired entries are pruned lazily on access — there is no background sweeper
    (YAGNI: the store is tiny and process-lifetime bounded)."""
    entry = _tokens.get(token)
    if entry is None:
        return None
    if entry["expires_at"] <= time.time():
        _tokens.pop(token, None)
        return None
    return entry


def revoke_present_token(token: str) -> None:
    """Kill one token immediately (idempotent)."""
    _tokens.pop(token, None)


def revoke_for_bot(bot_id: str) -> int:
    """Revoke every token minted for `bot_id`. Phase 3 calls this when a bot's
    present ends. Returns the count revoked."""
    if not bot_id:
        return 0
    doomed = [tok for tok, entry in _tokens.items() if entry.get("bot_id") == bot_id]
    for tok in doomed:
        _tokens.pop(tok, None)
    return len(doomed)
