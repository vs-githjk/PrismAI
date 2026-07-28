import asyncio
import contextvars
import os
import random
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

PRIMARY_MODEL = "claude-haiku-4-5-20251001"   # Anthropic — DEFAULT for llm_call: RAG helpers
                                              # (rewriter/reranker/preamble) + meeting_memory.
                                              # Kept fast/cheap because those are latency-critical.
FALLBACK_MODEL = "gpt-4o-mini"                # OpenAI — cross-provider fallback
# Post-meeting ANALYSIS agents (the 10 pipeline agents + cross-meeting synthesis + /agent
# re-runs) route here instead — higher quality, latency-tolerant since it's post-meeting.
# Selected per-call via the model= arg or the _AGENT_MODEL contextvar (set by the analysis
# dispatch), so flipping agents to Sonnet does NOT drag the latency-critical RAG/memory
# calls along. Env-overridable so the model can be re-pinned without a redeploy.
AGENT_MODEL = os.getenv("PRISM_AGENT_MODEL", "claude-sonnet-5")

# The newest Anthropic models (Sonnet 5 family) DEPRECATE the `temperature` param —
# passing it 400s ("`temperature` is deprecated for this model"), which is NOT transient,
# so every agent used to hard-fail with no fallback → empty meeting. Omit temperature for
# these. Haiku still accepts it. Substring match so dated variants are covered too.
_NO_TEMPERATURE_MODELS = ("claude-sonnet-5",)
def _accepts_temperature(model: str) -> bool:
    return not any(m in (model or "") for m in _NO_TEMPERATURE_MODELS)

# Set by the analysis-pipeline dispatch (analysis_service) + /agent re-run, read inside
# llm_call to pick AGENT_MODEL for those calls only. Empty → llm_call uses PRIMARY_MODEL.
_AGENT_MODEL: contextvars.ContextVar[str] = contextvars.ContextVar("agent_model", default="")


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


# The pipeline fans out 5 Tier-1 agents in parallel, then 4 Tier-2 — a burst that
# reliably trips Haiku's per-minute rate limit, and then trips OpenAI's when all 9
# fall over at once. Retrying with backoff+jitter (rather than failing to the
# agent's _DEFAULT, which silently nulls a card) is what makes sentiment/health
# survive the burst. Env-overridable so it can be tuned without a code change.
_PRIMARY_ATTEMPTS = int(os.getenv("PRISM_LLM_PRIMARY_ATTEMPTS", "3"))
_FALLBACK_ATTEMPTS = int(os.getenv("PRISM_LLM_FALLBACK_ATTEMPTS", "3"))
_LLM_BACKOFF_BASE = float(os.getenv("PRISM_LLM_BACKOFF_BASE", "0.6"))
_LLM_BACKOFF_CAP = float(os.getenv("PRISM_LLM_BACKOFF_CAP", "8.0"))


async def _backoff_sleep(attempt: int) -> None:
    """Exponential backoff with full jitter — spreads the parallel agents' retries
    apart so they stop hammering the rate limit in lockstep."""
    delay = min(_LLM_BACKOFF_CAP, _LLM_BACKOFF_BASE * (2 ** attempt))
    await asyncio.sleep(random.uniform(0, delay))


async def llm_call(
    system: str,
    user: str,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    model: str | None = None,
) -> str:
    """Call the primary Anthropic model. On rate-limit/overload/5xx, fall back to
    OpenAI gpt-4o-mini for cross-provider resilience.

    model: explicit Anthropic model override. When unset, resolves to the _AGENT_MODEL
    contextvar (Sonnet, set by the analysis dispatch) if present, else PRIMARY_MODEL
    (Haiku) — so post-meeting agents get Sonnet while latency-critical RAG helpers +
    meeting_memory keep Haiku, all through this one function.

    max_tokens: optional cap on response length. Useful for short, structured
    outputs (e.g. context preambles, reranker decisions, query rewrites) so
    we don't pay for runaway generation. Anthropic requires a max_tokens — when
    unset we default generously (4096) since these are bounded structured outputs."""
    system = system + get_persona_suffix()
    # Anthropic caps temperature at 1.0; our agents stay ≤1 but clamp defensively.
    temp = min(temperature, 1.0)
    out_tokens = max_tokens if max_tokens is not None else 4096
    primary_model = model or _AGENT_MODEL.get() or PRIMARY_MODEL

    anthropic_client = _get_anthropic()
    primary_exc = None
    if anthropic_client:
        # Retry the primary on transient errors (rate-limit/overload/5xx) with backoff
        # before conceding to the fallback — a burst-induced 429 usually clears in
        # a second or two, so retrying keeps the work on the primary model.
        primary_kwargs = {
            "model": primary_model,
            "max_tokens": out_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if _accepts_temperature(primary_model):
            primary_kwargs["temperature"] = temp
        for attempt in range(_PRIMARY_ATTEMPTS):
            try:
                resp = await anthropic_client.messages.create(**primary_kwargs)
                # claude-sonnet-5 can emit a ThinkingBlock BEFORE the TextBlock, so
                # content[0] isn't always the answer (content[0].text → AttributeError on
                # the thinking block). Concatenate the text from every text block instead.
                return "".join(getattr(block, "text", "") for block in resp.content)
            except Exception as exc:
                primary_exc = exc
                # A NON-transient error (bad request, unsupported param, bad model id) won't
                # clear on retry — stop retrying, but still fall through to the OpenAI fallback
                # rather than raising here. Raising used to make every agent return its empty
                # default (an all-blank meeting) on any primary incompatibility; degrading to
                # the fallback keeps the meeting alive. Loud log so the incompatibility is seen.
                if not _is_transient(exc):
                    print(f"[agent] {primary_model} NON-transient error ({exc!r}) — "
                          f"falling back to {FALLBACK_MODEL}")
                    break
                if attempt < _PRIMARY_ATTEMPTS - 1:
                    print(f"[agent] {primary_model} transient ({exc!r}), retry {attempt + 1}/{_PRIMARY_ATTEMPTS - 1}")
                    await _backoff_sleep(attempt)
        else:
            print(f"[agent] {primary_model} exhausted {_PRIMARY_ATTEMPTS} attempts ({primary_exc!r}), "
                  f"falling back to {FALLBACK_MODEL}")

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
        # Retry the fallback too: when Haiku rate-limits the whole 9-agent burst at
        # once, they ALL land on OpenAI simultaneously and can rate-limit it in turn.
        fallback_exc = None
        for attempt in range(_FALLBACK_ATTEMPTS):
            try:
                resp = await openai_client.chat.completions.create(**oai_kwargs)
                return resp.choices[0].message.content
            except Exception as exc:
                fallback_exc = exc
                if not _is_transient(exc) or attempt == _FALLBACK_ATTEMPTS - 1:
                    break
                print(f"[agent] {FALLBACK_MODEL} transient ({exc!r}), retry {attempt + 1}/{_FALLBACK_ATTEMPTS - 1}")
                await _backoff_sleep(attempt)
        # Both providers failed — surface the most relevant error to the agent's
        # try/except (which returns its _DEFAULT), now only after real retries.
        raise fallback_exc or primary_exc or RuntimeError("LLM fallback failed")
    if primary_exc:
        raise primary_exc
    raise RuntimeError("No LLM provider configured: set ANTHROPIC_API_KEY or OPENAI_API_KEY")
