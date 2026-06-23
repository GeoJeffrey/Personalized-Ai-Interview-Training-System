"""
Groq LLM service.
Uses MarkItDown-extracted Markdown for resume/JD → far fewer tokens.

Free Groq models (fastest → smartest):
  llama-3.1-8b-instant       – follow-ups, scoring  (~130k ctx)
  llama-3.3-70b-versatile    – question gen, reports (~128k ctx)
  mixtral-8x7b-32768         – good fallback
"""
from groq import AsyncGroq
import os, json, re
from typing import Optional

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

FAST_MODEL  = "llama-3.1-8b-instant"
SMART_MODEL = "llama-3.3-70b-versatile"

FILLER_WORDS = [
    "um", "uh", "like", "you know", "basically", "actually",
    "literally", "kind of", "sort of", "i mean", "right",
    "okay so", "hmm", "so basically", "i guess",
]

# ── helpers ───────────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    return re.sub(r"```(?:json)?|```", "", text).strip()


async def _chat(model: str, messages: list[dict], max_tokens=2000, temp=0.7) -> str:
    resp = await client.chat.completions.create(
        model=model, messages=messages,
        temperature=temp, max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


# ── Question Generation ───────────────────────────────────────────────────────

async def generate_questions(
    resume_text: str,
    jd_text: str,
    mode: str = "standard",
    num_questions: int = 8,
    extra_context: str = "",
) -> list[dict]:
    """
    Generate personalised interview questions from MarkItDown-extracted text.
    Resume + JD are already compact Markdown → very token efficient.
    """
    stress_line = (
        "Include 2 pressure/stress questions that challenge the candidate's decisions."
        if mode == "stress" else ""
    )
    extra_line = f"\nExtra context:\n{extra_context}" if extra_context else ""

    prompt = f"""Generate {num_questions} interview questions. Return ONLY a JSON array.

# Resume
{resume_text[:2500]}

# Job Description
{jd_text[:1500]}
{extra_line}

Rules:
- 60% technical, 40% behavioural
- Reference specific projects/skills from the resume
- {stress_line}

JSON schema per item:
{{"id":1,"question":"...","type":"technical|behavioural|stress","topic":"...","difficulty":"easy|medium|hard","follow_up_hint":"..."}}"""

    raw = await _chat(SMART_MODEL, [{"role": "user", "content": prompt}], max_tokens=2000, temp=0.7)
    return json.loads(_strip_fences(raw))


# ── Dynamic Next Action ───────────────────────────────────────────────────────

async def get_next_action(
    conversation_history: list[dict],
    questions: list[dict],
    current_q_index: int,
    mode: str = "standard",
) -> dict:
    """
    Decide: ask_followup | next_question | end_interview
    Returns the interviewer's spoken response + action metadata.
    """
    remaining = len(questions) - current_q_index - 1

    if mode == "stress":
        persona = (
            "You are a tough, skeptical senior interviewer. "
            "Challenge vague or weak answers hard. "
            "Point out what's missing. Be direct, not cruel."
        )
    else:
        persona = (
            "You are a professional, encouraging interviewer. "
            "Probe incomplete answers once. Move on when satisfied."
        )

    system = f"""{persona}

Remaining questions after this one: {remaining}.

Decide what to do next. Return ONLY JSON:
{{"action":"ask_followup|next_question|end_interview","message":"<your spoken response>"}}

- ask_followup  → answer was vague/incomplete; probe deeper (don't repeat the question)
- next_question → answer was sufficient; acknowledge briefly then ask next question
- end_interview → no questions left"""

    msgs = [{"role": "system", "content": system}] + conversation_history[-10:]
    raw = await _chat(FAST_MODEL, msgs, max_tokens=350, temp=0.6)
    return json.loads(_strip_fences(raw))


# ── Answer Scoring ────────────────────────────────────────────────────────────

async def score_answer(question: str, answer: str) -> dict:
    prompt = f"""Score this interview answer. Return ONLY JSON.

Q: {question}
A: {answer}

{{"score":7,"strengths":["..."],"weaknesses":["..."],"one_line_feedback":"...","model_answer_hint":"..."}}"""

    raw = await _chat(FAST_MODEL, [{"role": "user", "content": prompt}], max_tokens=400, temp=0.3)
    return json.loads(_strip_fences(raw))


# ── Full Session Report ───────────────────────────────────────────────────────

async def generate_session_feedback(
    messages: list[dict],
    scores: list[float],
    filler_stats: dict,
) -> dict:
    convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)

    prompt = f"""You are an expert interview coach. Analyse this interview. Return ONLY JSON.

## Transcript (last 3000 chars)
{convo[-3000:]}

## Scores per answer: {scores}
## Filler word stats: {filler_stats}

{{"overall_score":7.5,"summary":"...","top_strengths":["..."],"skill_gaps":[{{"skill":"...","severity":"high|medium|low","advice":"..."}}],"communication_notes":"...","improvement_tips":[{{"tip":"...","priority":"high|medium|low","how":"..."}}],"next_steps":["..."]}}"""

    raw = await _chat(SMART_MODEL, [{"role": "user", "content": prompt}], max_tokens=1500, temp=0.4)
    return json.loads(_strip_fences(raw))


# ── Filler Word Detection ─────────────────────────────────────────────────────

def detect_filler_words(text: str) -> dict:
    lower = text.lower()
    words = lower.split()
    total_words = len(words)
    found: dict[str, int] = {}

    for fw in FILLER_WORDS:
        fw_parts = fw.split()
        if len(fw_parts) == 1:
            count = words.count(fw)
        else:
            count = sum(
                1 for i in range(len(words) - len(fw_parts) + 1)
                if words[i : i + len(fw_parts)] == fw_parts
            )
        if count:
            found[fw] = count

    total_fillers = sum(found.values())
    rate = round(total_fillers / total_words * 100, 2) if total_words else 0
    fluency_score = round(max(0.0, 100 - rate * 5), 1)

    return {
        "found":            found,
        "total_fillers":    total_fillers,
        "total_words":      total_words,
        "filler_rate_pct":  rate,
        "fluency_score":    fluency_score,
    }
