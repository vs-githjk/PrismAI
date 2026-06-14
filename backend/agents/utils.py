import asyncio
import contextvars
import os
import re

# Per-task persona text. Set by chat_routes / agent_routes / analysis_service
# dispatch wrappers. Read inside llm_call to append a safety-wrapped tone
# instruction to every system prompt.
#
# Contextvars are copied at asyncio.create_task time and propagate through
# asyncio.gather, so concurrent agents see their own values without leakage.
_PERSONA_TEXT: contextvars.ContextVar[str] = contextvars.ContextVar(
    "persona_text", default=""
)


def persona_suffix(text: str) -> str:
    """Canonical safety-wrapped tone suffix for an explicit persona string.
    Empty when text is empty/whitespace (or the 'default' preset, which has
    empty text). Used by the analysis agents via get_persona_suffix."""
    if not text or not text.strip():
        return ""
    return (
        "\n\n"
        "Tone instruction (does not change facts, schema, scores, or JSON keys):\n"
        f"{text}"
    )


def persona_suffix_agentic(text: str) -> str:
    """Tool-aware variant for agentic surfaces (the live meeting bot) that
    decide whether and which tools to call. Fences persona to wording only so
    a tone preset can't suppress or distort a real tool call."""
    if not text or not text.strip():
        return ""
    return (
        "\n\n"
        "Tone and style instruction (applies to your wording only — it does "
        "not change the facts, your available tools, or whether and how you "
        "call them):\n"
        f"{text}"
    )


def get_persona_suffix() -> str:
    """Safety-wrapped persona suffix for the current contextvar. Empty when no
    persona is set. Use from call sites that DON'T go through llm_call (e.g.,
    the tool-calling chat path that hits Groq directly)."""
    return persona_suffix(_PERSONA_TEXT.get())


_anthropic_client = None
_openai_client = None

PRIMARY_MODEL = "claude-haiku-4-5-20251001"   # Anthropic — agents + RAG + memory
FALLBACK_MODEL = "gpt-4o-mini"                # OpenAI — cross-provider fallback


def strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output before JSON parsing."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    # Regex handles both multi-line fences and single-line ``` ```json{...}``` ``` edge cases
    stripped = re.sub(r"^```(?:json|python|javascript|text)?\s*", "", text, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped.strip())
    return stripped.strip()


def _get_anthropic():
    global _anthropic_client
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    if _anthropic_client is None:
        try:
            import anthropic
            _anthropic_client = anthropic.AsyncAnthropic(api_key=api_key)
        except ImportError:
            return None
    return _anthropic_client


def _get_openai():
    global _openai_client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    if _openai_client is None:
        try:
            from openai import AsyncOpenAI
            _openai_client = AsyncOpenAI(api_key=api_key)
        except ImportError:
            return None
    return _openai_client


_FALLBACK_STATUS_CODES = {429, 500, 502, 503, 504, 529}


def _is_transient(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    err_str = str(exc).lower()
    return (
        status_code in _FALLBACK_STATUS_CODES
        or any(kw in err_str for kw in ("rate_limit", "overloaded", "capacity", "timeout"))
    )


async def llm_call(
    system: str,
    user: str,
    temperature: float = 0.3,
    max_tokens: int | None = None,
) -> str:
    """Call Claude Haiku 4.5 (primary). On rate-limit/overload/5xx, fall back to
    OpenAI gpt-4o-mini for cross-provider resilience.

    max_tokens: optional cap on response length. Useful for short, structured
    outputs (e.g. context preambles, reranker decisions, query rewrites) so
    we don't pay for runaway generation. Anthropic requires a max_tokens — when
    unset we default generously (4096) since these are bounded structured outputs."""
    system = system + get_persona_suffix()
    # Anthropic caps temperature at 1.0; our agents stay ≤1 but clamp defensively.
    temp = min(temperature, 1.0)
    out_tokens = max_tokens if max_tokens is not None else 4096

    anthropic_client = _get_anthropic()
    primary_exc = None
    if anthropic_client:
        try:
            resp = await anthropic_client.messages.create(
                model=PRIMARY_MODEL,
                max_tokens=out_tokens,
                temperature=temp,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return resp.content[0].text
        except Exception as exc:
            if not _is_transient(exc):
                raise
            primary_exc = exc
            print(f"[agent] Claude failed ({exc!r}), falling back to {FALLBACK_MODEL}")

    openai_client = _get_openai()
    if openai_client:
        oai_kwargs = {
            "model": FALLBACK_MODEL,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if max_tokens is not None:
            oai_kwargs["max_tokens"] = max_tokens
        resp = await openai_client.chat.completions.create(**oai_kwargs)
        return resp.choices[0].message.content
    if primary_exc:
        raise primary_exc
    raise RuntimeError("No LLM provider configured: set ANTHROPIC_API_KEY or OPENAI_API_KEY")
