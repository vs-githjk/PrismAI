import os
import re

_groq_client = None
_anthropic_client = None


def strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output before JSON parsing."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    # Regex handles both multi-line fences and single-line ``` ```json{...}``` ``` edge cases
    stripped = re.sub(r"^```(?:json|python|javascript|text)?\s*", "", text, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped.strip())
    return stripped.strip()


def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import AsyncGroq
        _groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
    return _groq_client


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


_FALLBACK_STATUS_CODES = {429, 500, 502, 503, 504}


async def llm_call(system: str, user: str, temperature: float = 0.3) -> str:
    """Call Groq LLM. On rate-limit or server errors, falls back to claude-haiku-4-5 if ANTHROPIC_API_KEY is set."""
    groq = _get_groq()
    try:
        resp = await groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        err_str = str(exc)
        # Fall back on rate-limit / server errors — check both typed attribute and message substring
        should_fallback = (
            status_code in _FALLBACK_STATUS_CODES
            or any(kw in err_str for kw in ("rate_limit", "overloaded", "capacity"))
        )
        anthropic_client = _get_anthropic()
        if should_fallback and anthropic_client:
            print(f"[agent] Groq failed ({exc!r}), falling back to claude-haiku-4-5")
            resp = await anthropic_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return resp.content[0].text
        raise
