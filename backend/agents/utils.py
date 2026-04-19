import os

_groq_client = None
_anthropic_client = None


def strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output before JSON parsing."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines).strip()
    return text


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


async def llm_call(system: str, user: str, temperature: float = 0.3) -> str:
    """Call Groq LLM. On 429/503/error, falls back to claude-haiku-4-5 if ANTHROPIC_API_KEY is set."""
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
        err = str(exc)
        should_fallback = any(code in err for code in ("429", "503", "rate", "overloaded"))
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
