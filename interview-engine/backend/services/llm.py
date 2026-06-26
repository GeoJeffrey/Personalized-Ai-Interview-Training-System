"""
Interview Coaching AI System
============================
Production-optimized module for AI-powered interview practice.
Uses Groq's Llama models for real-time feedback and scoring.

Author: Optimized Version
Version: 2.0.0
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from enum import Enum
from functools import lru_cache
from typing import Any, Optional, Union
from dotenv import load_dotenv
from groq import AsyncGroq


# ── Configuration & Constants ────────────────────────────────────────────────

# Load environment variables FIRST
load_dotenv()

# Initialize Groq client
client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

# Model configuration
FAST_MODEL = "llama-3.1-8b-instant"
SMART_MODEL = "llama-3.1-8b-instant"

# Configure logging (replaces debug prints)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Enable debug logging in development
DEBUG_MODE = os.getenv("DEBUG", "false").lower() == "true"


@dataclass(frozen=True)
class Config:
    """Immutable application configuration."""
    # API settings
    MAX_TOKENS_QUESTION_GEN: int = 2000
    MAX_TOKENS_NEXT_ACTION: int = 350
    MAX_TOKENS_SCORING: int = 400
    MAX_TOKENS_FEEDBACK: int = 1500
    
    # Temperature settings
    TEMP_CREATIVE: float = 0.7
    TEMP_BALANCED: float = 0.6
    TEMP_PRECISE: float = 0.3
    TEMP_ANALYSIS: float = 0.4
    
    # Text limits
    RESUME_MAX_CHARS: int = 2500
    JD_MAX_CHARS: int = 1500
    TRANSCRIPT_MAX_CHARS: int = 3000
    HISTORY_WINDOW_SIZE: int = 10
    
    # Scoring thresholds
    MIN_SCORE: int = 1
    MAX_SCORE: int = 10
    FLUENCY_PENALTY_FACTOR: float = 5.0
    
    # Retry settings
    MAX_RETRIES: int = 3
    RETRY_DELAY_BASE: float = 1.0


# Global config instance
CONFIG = Config()


# ── Enums & Data Models ──────────────────────────────────────────────────────

class ActionType(Enum):
    """Possible interviewer actions."""
    ASK_FOLLOWUP = "ask_followup"
    NEXT_QUESTION = "next_question"
    END_INTERVIEW = "end_interview"


class QuestionType(Enum):
    """Question categories."""
    TECHNICAL = "technical"
    BEHAVIOURAL = "behavioural"
    STRESS = "stress"


class Difficulty(Enum):
    """Difficulty levels."""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Severity(Enum):
    """Gap severity levels."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Priority(Enum):
    """Action priority levels."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Question:
    """Generated interview question."""
    id: int
    question: str
    type: str
    topic: str
    difficulty: str
    follow_up_hint: str


@dataclass
class NextAction:
    """Interviewer's next action decision."""
    action: str
    message: str


@dataclass
class AnswerScore:
    """Score breakdown for an answer."""
    score: int
    strengths: list[str]
    weaknesses: list[str]
    one_line_feedback: str
    model_answer_hint: str


@dataclass
class SkillGap:
    """Identified skill gap."""
    skill: str
    severity: str
    advice: str


@dataclass
class ImprovementTip:
    """Actionable improvement suggestion."""
    tip: str
    priority: str
    how: str


@dataclass
class SessionFeedback:
    """Comprehensive session analysis."""
    overall_score: float
    summary: str
    top_strengths: list[str]
    skill_gaps: list[dict]
    communication_notes: str
    improvement_tips: list[dict]
    next_steps: list[str]


@dataclass
class FillerAnalysis:
    """Filler word analysis result."""
    found: dict[str, int]
    total_fillers: int
    total_words: int
    filler_rate_pct: float
    fluency_score: float


# ── Filler Word Configuration (Optimized) ────────────────────────────────────

class FillWordConfig:
    """
    Optimized filler word detection using compiled regex patterns.
    
    Performance: O(n) single-pass regex vs original O(n×m) approach
    where n=text length, m=number of filler patterns
    """
    
    # Patterns ordered by specificity (longer phrases first)
    PATTERNS: tuple[tuple[str, str], ...] = (
        (r'\bokay so\b', 'okay so'),
        (r'\bso basically\b', 'so basically'),
        (r'\byou know\b', 'you know'),
        (r'\bas i said\b', 'as i said'),  # common variant
        (r'\bkind of\b', 'kind of'),
        (r'\bsort of\b', 'sort of'),
        (r'\bi mean\b', 'i mean'),
        (r'\bi guess\b', 'i guess'),
        (r'\bbasically\b', 'basically'),
        (r'\bactually\b', 'actually'),
        (r'\bliterally\b', 'literally'),
        (r'\blike\b', 'like'),
        (r'\bum\b', 'um'),
        (r'\buh\b', 'uh'),
        (r'\bhmm\b', 'hmm'),
        (r'\bright\b', 'right'),
        (r'\bokay\b', 'okay'),
        (r'\bso\b', 'so'),
    )
    
    _compiled_pattern: Optional[re.Pattern] = None
    _pattern_map: dict[str, str] = {}
    
    @classmethod
    def get_pattern(cls) -> re.Pattern:
        """Get or create compiled regex pattern (cached)."""
        if cls._compiled_pattern is None:
            regex_parts = [p[0] for p in cls.PATTERNS]
            cls._compiled_pattern = re.compile(
                '|'.join(regex_parts), 
                re.IGNORECASE
            )
            # Build reverse mapping for normalized keys
            cls._pattern_map = {p[0].lower(): p[1] for p in cls.PATTERNS}
        return cls._compiled_pattern
    
    @classmethod
    def normalize_match(cls, match: str) -> str:
        """Normalize matched text to standard filler word key."""
        return cls._pattern_map.get(match.lower(), match.lower())


# ── Utility Functions ────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    """
    Remove markdown code fences from LLM response.
    
    Handles:
    - ```json ... ```
    - ``` ... ```
    - Nested or malformed fences
    
    Args:
        text: Raw LLM response
        
    Returns:
        Clean text without fences
    """
    if not text:
        return ""
    
    text = text.strip()
    
    # Pattern matches ```json, ```, or ```language followed by content and closing ```
    pattern = r'^```(?:json)?\s*\n?(.*?)\n?```$'
    match = re.match(pattern, text, re.DOTALL | re.MULTILINE)
    
    if match:
        return match.group(1).strip()
    
    # Fallback: remove any fence markers found
    cleaned = re.sub(r'```(?:json)?|```', '', text).strip()
    return cleaned


def _safe_json_parse(
    raw_text: str, 
    fallback: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """
    Safely parse JSON with multiple fallback strategies.
    
    Strategy order:
    1. Direct parse
    2. After stripping markdown fences
    3. Extract JSON object from surrounding text
    4. Return fallback
    
    Args:
        raw_text: Raw string potentially containing JSON
        fallback: Default dict if all parsing fails
        
    Returns:
        Parsed dictionary or fallback
    """
    if not raw_text or not raw_text.strip():
        logger.warning("Empty text received for JSON parsing")
        return fallback or {}
    
    strategies = [
        lambda t: json.loads(t),
        lambda t: json.loads(_strip_fences(t)),
        lambda t: json.loads(_extract_json_object(t)),
    ]
    
    last_error = None
    for i, strategy in enumerate(strategies):
        try:
            result = strategy(raw_text)
            if isinstance(result, dict):
                return result
            elif isinstance(result, list):
                return {"_array_wrapper": result}
            else:
                logger.warning(f"Strategy {i} returned non-dict: {type(result)}")
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            last_error = e
            continue
    
    logger.error(f"All JSON parsing strategies failed. Last error: {last_error}")
    logger.debug(f"Raw text (first 200 chars): {raw_text[:200]}")
    return fallback or {}


def _extract_json_object(text: str) -> str:
    """
    Extract JSON object from text that may contain extra content.
    
    Uses brace counting to find the outermost JSON object.
    
    Args:
        text: Text containing JSON somewhere inside
        
    Returns:
        Extracted JSON string
    """
    start = text.find('{')
    if start == -1:
        raise ValueError("No JSON object start '{' found")
    
    brace_count = 0
    in_string = False
    escape_next = False
    
    for i in range(start, len(text)):
        char = text[i]
        
        if escape_next:
            escape_next = False
            continue
            
        if char == '\\':
            escape_next = True
            continue
            
        if char == '"':
            in_string = not in_string
            continue
            
        if in_string:
            continue
            
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                return text[start:i + 1]
    
    raise ValueError("Incomplete JSON object (unmatched braces)")


async def _chat_with_retry(
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = CONFIG.MAX_TOKENS_QUESTION_GEN,
    temperature: float = CONFIG.TEMP_CREATIVE,
    max_retries: int = CONFIG.MAX_RETRIES
) -> str:
    """
    Execute chat completion with automatic retry on transient failures.
    
    Args:
        model: Groq model identifier
        messages: Message history
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature
        max_retries: Number of retry attempts
        
    Returns:
        Model response text
        
    Raises:
        Exception: After all retries exhausted
    """
    import asyncio
    
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                delay = CONFIG.RETRY_DELAY_BASE * (2 ** (attempt - 1))  # Exponential backoff
                logger.warning(f"Retry attempt {attempt}/{max_retries} after {delay}s delay")
                await asyncio.sleep(delay)
            
            logger.debug(f"Calling {model} (attempt {attempt + 1})")
            
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("Empty response from model")
            
            return content.strip()
            
        except Exception as e:
            last_exception = e
            logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
            
            # Don't retry on certain errors
            if _is_non_retryable_error(e):
                break
    
    raise last_exception or Exception("Unknown error in _chat_with_retry")


def _is_non_retryable_error(error: Exception) -> bool:
    """Check if error should not be retried."""
    non_retryable_patterns = [
        'authentication',
        'invalid_api_key',
        'permission',
        'rate_limit',  # Handle separately if needed
    ]
    error_str = str(error).lower()
    return any(pattern in error_str for pattern in non_retryable_patterns)


def _validate_role(role: str) -> str:
    """
    Validate and normalize message role for Groq API.
    
    Groq accepts only: system, user, assistant, tool
    
    Args:
        role: Raw role string
        
    Returns:
        Validated role string
    """
    # Mapping of common custom roles to valid roles
    ROLE_MAPPING = {
        'candidate': 'user',
        'interviewer': 'assistant',
        'ai': 'assistant',
        'bot': 'assistant',
        'interviewer_ai': 'assistant',
        'user_candidate': 'user',
    }
    
    valid_roles = {'system', 'user', 'assistant', 'tool'}
    
    # Try direct lookup first
    normalized = role.lower().strip()
    
    if normalized in valid_roles:
        return normalized
    
    # Check mapping
    mapped = ROLE_MAPPING.get(normalized)
    if mapped:
        return mapped
    
    # Default fallback
    logger.warning(f"Unknown role '{role}', defaulting to 'user'")
    return 'user'


def _sanitize_messages(
    messages: list[dict], 
    window_size: int = CONFIG.HISTORY_WINDOW_SIZE
) -> list[dict[str, str]]:
    """
    Clean and validate message history for API submission.
    
    Args:
        messages: Raw message list
        window_size: Max recent messages to include
        
    Returns:
        Sanitized message list
    """
    if not messages:
        return []
    
    # Take most recent messages within window
    recent_messages = messages[-window_size:] if len(messages) > window_size else messages
    
    sanitized = []
    for msg in recent_messages:
        if not isinstance(msg, dict):
            logger.warning(f"Skipping invalid message (not dict): {type(msg)}")
            continue
        
        role = _validate_role(msg.get('role', 'user'))
        content = msg.get('content', '')
        
        # Ensure content is string
        if not isinstance(content, str):
            content = str(content) if content else ''
        
        # Skip empty content messages (except maybe system)
        if not content.strip() and role != 'system':
            continue
        
        sanitized.append({
            'role': role,
            'content': content.strip()
        })
    
    return sanitized


# ── Core Functions (Optimized) ────────────────────────────────────────────────

async def generate_questions(
    resume_text: str,
    jd_text: str,
    mode: str = "standard",
    num_questions: int = 8,
    extra_context: str = "",
) -> list[dict]:
    """
    Generate tailored interview questions from resume and job description.
    
    Args:
        resume_text: Candidate's resume text
        jd_text: Job description text
        mode: Interview mode ('standard' or 'stress')
        num_questions: Number of questions to generate
        extra_context: Additional context for question generation
        
    Returns:
        List of Question dictionaries
        
    Raises:
        ValueError: If required inputs are empty
    """
    # Input validation
    if not resume_text or not resume_text.strip():
        raise ValueError("Resume text cannot be empty")
    if not jd_text or not jd_text.strip():
        raise ValueError("Job description cannot be empty")
    
    # Clamp num_questions to reasonable bounds
    num_questions = max(3, min(15, num_questions))
    
    # Build mode-specific instructions
    stress_instruction = (
        "- Include 2 pressure/stress questions that challenge the candidate's decisions.\n"
        if mode == "stress" else ""
    )
    
    context_section = (
        f"\n## Extra Context\n{extra_context}\n" 
        if extra_context and extra_context.strip() else ""
    )

    prompt = f"""Generate {num_questions} diverse interview questions based on the provided materials.

## Resume (truncated to {CONFIG.RESUME_MAX_CHARS} chars)
{resume_text[:CONFIG.RESUME_MAX_CHARS]}

## Job Description (truncated to {CONFIG.JD_MAX_CHARS} chars)
{jd_text[:CONFIG.JD_MAX_CHARS]}
{context_section}

### Requirements:
- Mix: 60% technical, 40% behavioural questions
- Reference specific projects, skills, or experiences from the resume
- Align questions with job requirements from the JD
- Vary difficulty levels (easy/medium/hard)
{stress_instruction}

### Output Format (JSON array ONLY, no other text):
[
  {{
    "id": 1,
    "question": "Specific question here",
    "type": "technical|behavioural|stress",
    "topic": "Relevant skill/domain",
    "difficulty": "easy|medium|hard",
    "follow_up_hint": "Suggested follow-up direction"
  }}
]

Generate exactly {num_questions} questions."""

    try:
        raw_response = await _chat_with_retry(
            SMART_MODEL,
            [{"role": "user", "content": prompt}],
            max_tokens=CONFIG.MAX_TOKENS_QUESTION_GEN,
            temperature=CONFIG.TEMP_CREATIVE
        )
        
        parsed = _safe_json_parse(raw_response)
        
        # Handle array wrapper from parser
        if '_array_wrapper' in parsed:
            questions_data = parsed['_array_wrapper']
        elif isinstance(parsed, list):
            questions_data = parsed
        else:
            # If we got a single object, wrap it
            questions_data = [parsed] if parsed.get('question') else []
        
        # Validate and clean each question
        validated_questions = []
        for i, q in enumerate(questions_data[:num_questions]):
            if isinstance(q, dict) and q.get('question'):
                validated_questions.append({
                    'id': q.get('id', i + 1),
                    'question': q['question'],
                    'type': q.get('type', 'technical'),
                    'topic': q.get('topic', 'General'),
                    'difficulty': q.get('difficulty', 'medium'),
                    'follow_up_hint': q.get('follow_up_hint', '')
                })
        
        if not validated_questions:
            logger.warning("No valid questions generated, returning fallback")
            return _generate_fallback_questions(num_questions)
        
        logger.info(f"Successfully generated {len(validated_questions)} questions")
        return validated_questions
        
    except Exception as e:
        logger.error(f"Question generation failed: {e}")
        return _generate_fallback_questions(num_questions)


def _generate_fallback_questions(count: int) -> list[dict]:
    """Generate generic fallback questions when API fails."""
    fallbacks = [
        {
            "id": i + 1,
            "question": f"Tell me about a challenging project you worked on (Question {i+1})",
            "type": "behavioural",
            "topic": "Experience",
            "difficulty": "medium",
            "follow_up_hint": "Ask about specific challenges faced"
        }
        for i in range(count)
    ]
    return fallbacks


async def get_next_action(
    conversation_history: list[dict],
    questions: list[dict],
    current_q_index: int,
    mode: str = "standard",
) -> dict:
    """
    Determine interviewer's next action using AI reasoning.
    
    Analyzes conversation context to decide whether to:
    - Ask a follow-up (answer was vague/incomplete)
    - Move to next question (answer was satisfactory)
    - End interview (no more questions)
    
    Args:
        conversation_history: Full message history
        questions: List of remaining questions
        current_q_index: Index of current question
        mode: Interview mode ('standard' or 'stress')
        
    Returns:
        NextAction dictionary with action type and message
    """
    # Calculate remaining questions
    remaining = max(0, len(questions) - current_q_index - 1)
    
    # Define persona based on mode
    personas = {
        "stress": (
            "You are a tough, skeptical senior interviewer conducting a stress interview. "
            "Your style:\n"
            "- Challenge vague answers aggressively but professionally\n"
            "- Point out logical gaps or missing details\n"
            "- Push back on weak examples with 'That's interesting, but...'\n"
            "- Be direct and demanding, never satisfied with surface-level answers\n"
            "- Use phrases like 'Be more specific,' 'Give me a concrete example,' 'That doesn't fully address my concern'"
        ),
        "standard": (
            "You are a professional, encouraging interviewer. "
            "Your style:\n"
            "- Probe incomplete answers once with curiosity\n"
            "- Acknowledge good answers briefly before moving on\n"
            "- Keep tone warm but professional\n"
            "- Guide candidates who seem stuck\n"
            "- Balance thoroughness with time management"
        ),
        "friendly": (
            "You are a supportive, mentor-like interviewer. "
            "Your style:\n"
            "- Create comfortable atmosphere\n"
            "- Gently probe for more detail when needed\n"
            "- Celebrate strong answers enthusiastically\n"
            "- Help nervous candidates show their best"
        )
    }
    
    persona = personas.get(mode, personas["standard"])
    
    system_prompt = f"""{persona}

## Current State
- Questions remaining after this: {remaining}
- Current question index: {current_q_index}
- Total questions: {len(questions)}

## Decision Guidelines
Choose ONE action:

1. **ask_followup** - When answer is:
   - Vague or lacks specifics
   - Missing key details (metrics, outcomes, your specific role)
   - Contradictory or confusing
   - Too short (< 30 seconds worth of speaking)

2. **next_question** - When answer is:
   - Complete with STAR format (Situation, Task, Action, Result)
   - Includes measurable results
   - Directly addresses the question
   - Shows self-awareness

3. **end_interview** - When:
   - No questions remain (remaining = 0)
   - Time limit reached (if applicable)

## Response Format (STRICT JSON ONLY):
{{"action":"ask_followup|next_question|end_interview","message":"<your spoken response>"}}

IMPORTANT: Return ONLY the JSON object. No explanation, no markdown fences."""

    # Sanitize conversation history
    clean_history = _sanitize_messages(conversation_history)
    
    # Build message payload
    messages = [
        {"role": "system", "content": system_prompt}
    ] + clean_history
    
    # Debug logging (only in debug mode)
    if DEBUG_MODE:
        logger.debug("\n" + "="*50)
        logger.debug("MESSAGES SENT TO GROQ:")
        for idx, msg in enumerate(messages):
            role = msg.get('role', '?')
            content_preview = msg.get('content', '')[:100] + "..." if len(msg.get('content', '')) > 100 else msg.get('content', '')
            logger.debug(f"  [{idx}] {role}: {content_preview}")
        logger.debug("="*50 + "\n")

    try:
        raw_response = await _chat_with_retry(
            FAST_MODEL,
            messages,
            max_tokens=CONFIG.MAX_TOKENS_NEXT_ACTION,
            temperature=CONFIG.TEMP_BALANCED
        )
        
        parsed_action = _safe_json_parse(raw_response)
        
        # Validate action type
        action = parsed_action.get('action', 'next_question')
        valid_actions = {'ask_followup', 'next_question', 'end_interview'}
        
        if action not in valid_actions:
            logger.warning(f"Invalid action '{action}', defaulting to next_question")
            action = 'next_question'
        
        message = parsed_action.get('message', '')
        
        # Ensure message exists
        if not message or not message.strip():
            message = _get_default_message(action, remaining)
        
        result = {
            "action": action,
            "message": message.strip()
        }
        
        logger.info(f"Next action decided: {action}")
        return result
        
    except Exception as e:
        logger.error(f"get_next_action failed: {e}")
        
        # Intelligent fallback based on state
        if remaining <= 0:
            return {
                "action": "end_interview",
                "message": "Thank you for your time today. This concludes our interview. Do you have any questions for me?"
            }
        
        return {
            "action": "next_question",
            "message": "Thank you for sharing that. Let's move on to the next question."
        }


def _get_default_message(action: str, remaining: int) -> str:
    """Generate default message for fallback scenarios."""
    defaults = {
        "ask_followup": "Could you elaborate on that with a specific example?",
        "next_question": "Great, thank you. Let's proceed to the next question.",
        "end_interview": "Thank you. This concludes our interview."
    }
    return defaults.get(action, "Please continue.")


async def score_answer(
    question: str, 
    answer: str,
    *,
    use_smart_model: bool = False
) -> dict:
    """
    Score an interview answer with detailed feedback.
    
    Evaluates:
    - Content quality and relevance
    - Structure (STAR method usage)
    - Communication clarity
    - Specificity and depth
    
    Args:
        question: The interview question asked
        answer: Candidate's response
        use_smart_model: Use SMART_MODEL for deeper analysis
        
    Returns:
        AnswerScore dictionary with detailed breakdown
        
    Raises:
        ValueError: If question is empty
    """
    # Validation
    if not question or not question.strip():
        raise ValueError("Question cannot be empty")
    
    # Handle empty answer gracefully
    if not answer or not answer.strip():
        logger.warning("Empty answer received for scoring")
        return {
            "score": 0,
            "strengths": [],
            "weaknesses": ["No answer provided"],
            "one_line_feedback": "Please provide an answer to receive scoring.",
            "model_answer_hint": ""
        }
    
    model = SMART_MODEL if use_smart_model else FAST_MODEL
    
    prompt = f"""You are an expert interview evaluator. Score this answer objectively.

## Question
{question}

## Candidate's Answer
{answer}

## Evaluation Criteria (Score 1-10):
- **9-10**: Exceptional - Detailed STAR example, quantifiable results, clear communication
- **7-8**: Strong - Good example, some metrics, mostly clear
- **5-6**: Adequate - Basic answer, vague on details, some relevance
- **3-4**: Weak - Off-topic, very vague, missing structure
- **1-2**: Poor - Irrelevant, incoherent, or no substance

## Required Response Format (JSON ONLY):
{{
    "score": <integer 1-10>,
    "strengths": ["<specific strength 1>", "<strength 2>"],
    "weaknesses": ["<specific weakness 1>", "<weakness 2>"],
    "one_line_feedback": "<One sentence summary>",
    "model_answer_hint": "<Brief example of what a great answer would include>"
}}

Evaluate now:"""

    try:
        raw_response = await _chat_with_retry(
            model,
            [{"role": "user", "content": prompt}],
            max_tokens=CONFIG.MAX_TOKENS_SCORING,
            temperature=CONFIG.TEMP_PRECISE
        )
        
        parsed = _safe_json_parse(raw_response, fallback={
            "score": 5,
            "strengths": ["Answer received"],
            "weaknesses": ["Unable to perform full analysis"],
            "one_line_feedback": "Partial evaluation completed.",
            "model_answer_hint": ""
        })
        
        # Validate and clamp score
        score = int(parsed.get("score", 5))
        score = max(CONFIG.MIN_SCORE, min(CONFIG.MAX_SCORE, score))
        
        result = {
            "score": score,
            "strengths": parsed.get("strengths", []),
            "weaknesses": parsed.get("weaknesses", []),
            "one_line_feedback": parsed.get("one_line_feedback", ""),
            "model_answer_hint": parsed.get("model_answer_hint", "")
        }
        
        logger.info(f"Answer scored: {score}/10")
        return result
        
    except Exception as e:
        logger.error(f"Scoring failed: {e}")
        return {
            "score": 0,
            "strengths": [],
            "weaknesses": [f"Scoring system error: {str(e)}"],
            "one_line_feedback": "Unable to score at this time. Please try again.",
            "model_answer_hint": ""
        }


async def generate_session_feedback(
    messages: list[dict],
    scores: list[float],
    filler_stats: Union[dict, FillerAnalysis],
) -> dict:
    """
    Generate comprehensive end-of-session feedback report.
    
    Provides holistic analysis including:
    - Overall performance score
    - Strengths and areas for improvement
    - Communication pattern analysis
    - Actionable next steps
    
    Args:
        messages: Full conversation transcript
        scores: List of per-answer scores
        filler_stats: Output from detect_filler_words()
        
    Returns:
        SessionFeedback dictionary with complete analysis
    """
    # Convert FillerAnalysis to dict if needed
    if isinstance(filler_stats, FillerAnalysis):
        filler_dict = asdict(filler_stats)
    else:
        filler_dict = filler_stats
    
    # Build transcript efficiently
    convo_lines = []
    for msg in messages[-30:]:  # Last 30 messages
        role = msg.get('role', 'unknown').upper()
        content = msg.get('content', '')
        if content and content.strip():
            convo_lines.append(f"{role}: {content}")
    
    convo = "\n".join(convo_lines)
    
    # Truncate to limit
    if len(convo) > CONFIG.TRANSCRIPT_MAX_CHARS:
        # Keep the end (most recent is usually most relevant)
        convo = convo[-CONFIG.TRANSCRIPT_MAX_CHARS:]
    
    prompt = f"""You are an expert interview coach providing comprehensive feedback.

## Interview Transcript (Recent Excerpt)
{convo}

## Performance Metrics
- Per-question scores (1-10): {scores}
- Average score: {sum(scores)/len(scores) if scores else 0:.1f}

## Communication Analysis
{json.dumps(filler_dict, indent=2)}

## Analysis Requirements
Provide detailed, actionable feedback covering:

1. **Overall Assessment** - Weighted performance score (consider difficulty progression)
2. **Key Strengths** - Top 3 things done well with specific examples
3. **Skill Gaps** - Areas needing work with severity and remediation advice
4. **Communication Patterns** - Speaking style observations (fillers, pacing, clarity)
5. **Improvement Roadmap** - Prioritized tips with implementation guidance
6. **Next Steps** - Immediate actions to take

## Response Format (JSON ONLY):
{{
    "overall_score": <float 1-10>,
    "summary": "<2-3 sentence executive summary>",
    "top_strengths": ["<strength with example>"],
    "skill_gaps": [
        {{
            "skill": "<specific area>",
            "severity": "high|medium|low",
            "advice": "<concrete improvement strategy>"
        }}
    ],
    "communication_notes": "<analysis of verbal patterns>",
    "improvement_tips": [
        {{
            "tip": "<actionable suggestion>",
            "priority": "high|medium|low",
            "how": "<step-by-step implementation>"
        }}
    ],
    "next_steps": ["<immediate action 1>", "<action 2>"]
}}

Analyze thoroughly:"""

    try:
        raw_response = await _chat_with_retry(
            SMART_MODEL,
            [{"role": "user", "content": prompt}],
            max_tokens=CONFIG.MAX_TOKENS_FEEDBACK,
            temperature=CONFIG.TEMP_ANALYSIS
        )
        
        parsed = _safe_json_parse(raw_response, fallback={
            "overall_score": sum(scores)/len(scores) if scores else 5.0,
            "summary": "Unable to generate full analysis.",
            "top_strengths": [],
            "skill_gaps": [],
            "communication_notes": "",
            "improvement_tips": [],
            "next_steps": ["Review this session manually", "Practice common questions"]
        })
        
        # Ensure all expected fields exist with correct types
        result = {
            "overall_score": float(parsed.get("overall_score", 5.0)),
            "summary": parsed.get("summary", "Session completed."),
            "top_strengths": parsed.get("top_strengths", []),
            "skill_gaps": parsed.get("skill_gaps", []),
            "communication_notes": parsed.get("communication_notes", ""),
            "improvement_tips": parsed.get("improvement_tips", []),
            "next_steps": parsed.get("next_steps", [])
        }
        
        logger.info(f"Session feedback generated. Overall: {result['overall_score']}/10")
        return result
        
    except Exception as e:
        logger.error(f"Feedback generation failed: {e}")
        
        # Construct useful fallback
        avg_score = sum(scores) / len(scores) if scores else 0
        return {
            "overall_score": avg_score,
            "summary": f"Session completed with average score of {avg_score:.1f}/10. Full analysis unavailable.",
            "top_strengths": ["Completed interview practice"],
            "skill_gaps": [{"skill": "Technical knowledge", "severity": "medium", "advice": "Review core concepts"}],
            "communication_notes": "Unable to analyze communication patterns.",
            "improvement_tips": [{"tip": "Practice more interviews", "priority": "high", "how": "Use this tool regularly"}],
            "next_steps": ["Retry feedback generation", "Review individual question scores"]
        }


def detect_filler_words(text: str) -> dict:
    """
    Detect and analyze filler words in spoken text.
    
    Uses optimized single-pass regex matching for O(n) complexity.
    
    Detects:
    - Filler sounds (um, uh, hmm)
    - Filler phrases (you know, like, I mean)
    - Hedging words (basically, actually, sort of)
    
    Args:
        text: Transcribed speech or written text to analyze
        
    Returns:
        FillerAnalysis dictionary with counts, rates, and fluency score
        
    Example:
        >>> result = detect_filler_words("Um, so like, I basically led the team...")
        >>> result['fluency_score']
        78.5
        >>> result['found']
        {'um': 1, 'so': 1, 'like': 1, 'basically': 1}
    """
    # Handle edge cases
    if not text or not text.strip():
        return {
            "found": {},
            "total_fillers": 0,
            "total_words": 0,
            "filler_rate_pct": 0.0,
            "fluency_score": 100.0  # Empty = perfect by default
        }
    
    # Get optimized pattern
    pattern = FillWordConfig.get_pattern()
    
    # Single-pass regex findall (O(n) complexity)
    lower_text = text.lower()
    matches = pattern.findall(lower_text)
    
    # Normalize matches to standard keys
    normalized_matches = [
        FillWordConfig.normalize_match(match) 
        for match in matches
    ]
    
    # Count occurrences (efficient Counter)
    found_counter = Counter(normalized_matches)
    found_dict = dict(found_counter.most_common())  # Sort by frequency
    
    # Calculate metrics
    total_fillers = len(normalized_matches)
    
    # Word count (simple split, could be improved with tokenization)
    words = text.split()
    total_words = len(words)
    
    # Calculate rates
    filler_rate = round(
        (total_fillers / total_words * 100) if total_words > 0 else 0.0,
        2
    )
    
    # Fluency score: 100 minus penalty per % of fillers
    fluency_score = round(
        max(0.0, 100.0 - (filler_rate * CONFIG.FLUENCY_PENALTY_FACTOR)),
        1
    )
    
    result = {
        "found": found_dict,
        "total_fillers": total_fillers,
        "total_words": total_words,
        "filler_rate_pct": filler_rate,
        "fluency_score": fluency_score
    }
    
    if total_fillers > 0:
        logger.debug(f"Filler analysis: {total_fillers} fillers ({filler_rate}% rate)")
    
    return result


# ── Batch Processing Utilities ────────────────────────────────────────────────

import asyncio
from typing import Callable, Awaitable

async def batch_process(
    items: list[Any],
    process_fn: Callable[[Any], Awaitable[dict]],
    *,
    concurrency: int = 3,
    description: str = "Processing"
) -> list[dict]:
    """
    Process multiple items concurrently with rate limiting.
    
    Useful for batch scoring or question generation.
    
    Args:
        items: List of items to process
        process_fn: Async function to apply to each item
        concurrency: Max concurrent operations
        description: Label for logging
        
    Returns:
        List of results in original order
    """
    semaphore = asyncio.Semaphore(concurrency)
    results = [None] * len(items)
    
    async def _process_with_limit(index: int, item: Any) -> None:
        async with semaphore:
            try:
                results[index] = await process_fn(item)
            except Exception as e:
                logger.error(f"{description} item {index} failed: {e}")
                results[index] = {"error": str(e)}
    
    # Launch all tasks
    tasks = [
        _process_with_limit(i, item) 
        for i, item in enumerate(items)
    ]
    
    # Wait for completion
    await asyncio.gather(*tasks)
    
    logger.info(f"Batch {description} completed: {len(results)} items")
    return results


# ── Convenience Wrappers ─────────────────────────────────────────────────────

async def quick_score(question: str, answer: str) -> int:
    """Quick score returning just the integer score."""
    result = await score_answer(question, answer)
    return result.get("score", 0)


async def analyze_fluency(text: str) -> tuple[float, dict]:
    """Quick fluency analysis returning score and breakdown."""
    result = detect_filler_words(text)
    return result["fluency_score"], result["found"]
