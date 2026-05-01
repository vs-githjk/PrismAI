import asyncio
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
    """Call Groq LLM. On rate-limit/server errors, retries once if Groq says wait ≤5s, then falls back to claude-haiku-4-5."""
    groq = _get_groq()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    groq_exc = None
    for attempt in range(2):
        try:
            resp = await groq.chat.completions.create(
                model="llama-3.3-70b-versatile",
                temperature=temperature,
                messages=messages,
            )
            return resp.choices[0].message.content
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            err_str = str(exc)
            is_transient = (
                status_code in _FALLBACK_STATUS_CODES
                or any(kw in err_str for kw in ("rate_limit", "overloaded", "capacity"))
            )
            if not is_transient:
                raise
            groq_exc = exc
            if attempt == 0:
                m = re.search(r"try again in ([\d.]+)(ms|s)", err_str)
                if m:
                    val, unit = float(m.group(1)), m.group(2)
                    wait = val / 1000 if unit == "ms" else val
                    if wait <= 5:
                        await asyncio.sleep(wait)
                        continue
            break

    anthropic_client = _get_anthropic()
    if anthropic_client:
        print(f"[agent] Groq failed ({groq_exc!r}), falling back to claude-haiku-4-5")
        resp = await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text
    raise groq_exc
