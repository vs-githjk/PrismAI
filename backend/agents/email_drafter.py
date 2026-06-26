import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are an email drafter. Based on the meeting transcript, write a follow-up email "
    "summarizing key decisions and action items. "
    "If a '[Meeting owner: NAME]' line is present, write the email FROM that person's perspective — "
    "they are the sender (sign off with their name), and the email is addressed TO the OTHER participant(s), "
    "never to the meeting owner themselves. "
    "An AI assistant or note-taker — named 'Prism', 'PrismAI', or a persona like 'Flash'/'Glint'/'Echo' — "
    "is NOT a participant: it may have spoken on the owner's behalf (a stand-in), so treat any of its lines as "
    "the OWNER's own contributions. Never address the email to the assistant and never sign as the assistant. "
    "If no meeting owner is specified, infer the sender as the attendee (not the advisor or facilitator). "
    "FORMAT the body as a real email, not one run-on paragraph. Use actual newline characters (\\n) to separate parts:\n"
    "  - Greeting on its own line (e.g. 'Hi Nirmal,'), followed by a blank line.\n"
    "  - One or two short body paragraphs, separated by a blank line.\n"
    "  - When listing action items or next steps, put each on its own line, prefixed with '- '.\n"
    "  - A blank line, then a sign-off on its own line (e.g. 'Best,'), then the sender's name on the next line.\n"
    "Keep it concise and scannable. Do NOT cram the greeting, body, and sign-off onto one line. "
    'Return ONLY valid JSON: { "follow_up_email": { "subject": "", "body": "" } } — '
    "the body string must contain the \\n line breaks described above. "
    "If the transcript contains a [User instruction: ...] line, follow it exactly — "
    "including any requested tone, style, length, or content changes."
)


_DEFAULT = {"follow_up_email": {"subject": "", "body": ""}}


async def run(transcript: str, context: dict = {}) -> dict:
    # Build the user message from whichever inputs are present. The analysis
    # pipeline normally passes empty transcript + populated context (token
    # efficiency — see analysis_service.TIER2_CONTEXT_ONLY). The chat_routes
    # re-run flow passes the full transcript (with [User instruction: ...]
    # appended) + empty context. Both must work, so build additively.
    parts = []
    if context:
        # Owner header FIRST so the sender-perspective rule fires even on the
        # context-only path (Tier-2 agents don't receive the transcript, where this
        # header normally lives — see analysis_service._tier1_barrier).
        if context.get("owner_name"):
            parts.append(f"[Meeting owner: {context['owner_name']}]")
        if context.get("summary"):
            parts.append(f"Meeting summary: {context['summary']}")
        if context.get("decisions"):
            decisions_text = "\n".join(
                f"- {d.get('decision', str(d))}" for d in context["decisions"]
            )
            parts.append(f"Decisions made:\n{decisions_text}")
        if context.get("action_items"):
            items_text = "\n".join(
                f"- {a.get('task', str(a))} (owner: {a.get('owner', 'Unassigned')})"
                for a in context["action_items"]
            )
            parts.append(f"Action items:\n{items_text}")
    if transcript:
        parts.append(f"Transcript:\n{transcript}")

    # Fail-safe: if absolutely nothing was provided, give the model the bare
    # transcript header so it doesn't see an empty user message.
    user_content = "\n\n---\n\n".join(parts) if parts else "Transcript:\n"

    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, user_content, temperature=0.7)
            return json.loads(strip_fences(raw))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT
