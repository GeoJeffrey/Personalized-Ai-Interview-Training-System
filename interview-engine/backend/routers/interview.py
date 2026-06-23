from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import json, time

from services.database import get_db, InterviewSession, Message, User, SessionAnalytics
from services.llm import (
    generate_questions, get_next_action, score_answer,
    generate_session_feedback, detect_filler_words
)

router = APIRouter()


# ─── REST: Create Session ─────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    user_id: int
    title: str
    resume_text: str
    jd_text: str
    mode: str = "standard"          # standard | stress
    num_questions: int = 8
    extra_context: Optional[str] = ""

@router.post("/session")
async def create_session(req: CreateSessionRequest, db: AsyncSession = Depends(get_db)):
    """Create a new interview session and pre-generate questions."""

    # Generate questions
    questions = await generate_questions(
        resume_text=req.resume_text,
        jd_text=req.jd_text,
        mode=req.mode,
        num_questions=req.num_questions,
        extra_context=req.extra_context or "",
    )

    # Opening message from interviewer
    opening = (
        "Welcome. Let's get started. I'll be asking you some challenging questions today. "
        "I expect concise, well-structured answers. Ready?"
        if req.mode == "stress"
        else
        "Hi! Welcome to your mock interview. I'll ask you a mix of technical and behavioural questions. "
        "Take your time and answer naturally. Let's begin!"
    )

    session = InterviewSession(
        user_id=req.user_id,
        title=req.title,
        mode=req.mode,
        resume_text=req.resume_text,
        jd_text=req.jd_text,
        metadata_json={"questions": questions, "current_q": 0},
    )
    db.add(session)
    await db.flush()

    # Store opening message
    db.add(Message(
        session_id=session.id,
        role="interviewer",
        content=opening,
    ))
    await db.commit()
    await db.refresh(session)

    return {
        "session_id": session.id,
        "questions": questions,
        "opening_message": opening,
    }


# ─── REST: Submit Text Answer ─────────────────────────────────────────────────

class AnswerRequest(BaseModel):
    session_id: int
    answer_text: str

@router.post("/answer")
async def submit_answer(req: AnswerRequest, db: AsyncSession = Depends(get_db)):
    """Process a candidate answer, score it, and get the next interviewer message."""

    session = await db.get(InterviewSession, req.session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    meta = session.metadata_json or {}
    questions = meta.get("questions", [])
    current_q = meta.get("current_q", 0)

    # Filler word analysis
    filler_stats = detect_filler_words(req.answer_text)

    # Score the answer
    current_question = questions[current_q]["question"] if current_q < len(questions) else ""
    scoring = await score_answer(current_question, req.answer_text)

    # Save candidate message
    db.add(Message(
        session_id=req.session_id,
        role="candidate",
        content=req.answer_text,
        score=scoring.get("score"),
        feedback=scoring.get("one_line_feedback"),
        filler_words=filler_stats["found"],
    ))
    await db.flush()

    # Build conversation history for context
    result = await db.execute(
        select(Message)
        .where(Message.session_id == req.session_id)
        .order_by(Message.created_at)
    )
    all_msgs = result.scalars().all()
    history = [{"role": m.role, "content": m.content} for m in all_msgs]

    # Decide next action
    action_data = await get_next_action(
        conversation_history=history,
        questions=questions,
        current_q_index=current_q,
        mode=session.mode,
    )

    next_q = current_q
    if action_data["action"] == "next_question":
        next_q = current_q + 1
        # Prepend the actual next question if moving forward
        if next_q < len(questions):
            next_question_text = questions[next_q]["question"]
            action_data["message"] = f"{action_data['message']} {next_question_text}"

    # Update session metadata
    meta["current_q"] = next_q
    session.metadata_json = meta
    if action_data["action"] == "end_interview":
        session.status = "completed"
        from datetime import datetime
        session.ended_at = datetime.utcnow()

    # Save interviewer response
    db.add(Message(
        session_id=req.session_id,
        role="interviewer",
        content=action_data["message"],
    ))
    await db.commit()

    return {
        "action": action_data["action"],
        "interviewer_message": action_data["message"],
        "scoring": scoring,
        "filler_stats": filler_stats,
        "current_q_index": next_q,
        "total_questions": len(questions),
    }


# ─── REST: End Session & Get Full Report ─────────────────────────────────────

@router.post("/session/{session_id}/end")
async def end_session(session_id: int, db: AsyncSession = Depends(get_db)):
    """Finalise session and generate full analytics report."""

    session = await db.get(InterviewSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    all_msgs = result.scalars().all()

    candidate_msgs = [m for m in all_msgs if m.role == "candidate"]
    scores = [m.score for m in candidate_msgs if m.score is not None]

    # Aggregate filler words
    all_candidate_text = " ".join(m.content for m in candidate_msgs)
    filler_stats = detect_filler_words(all_candidate_text)

    # Generate full coaching report
    history = [{"role": m.role, "content": m.content} for m in all_msgs]
    report = await generate_session_feedback(history, scores, filler_stats)

    # Save analytics
    analytics = SessionAnalytics(
        session_id=session_id,
        fluency_score=filler_stats["fluency_score"],
        avg_answer_quality=sum(scores) / len(scores) if scores else None,
        filler_word_count=filler_stats["total_fillers"],
        filler_word_rate=filler_stats["filler_rate_pct"],
        total_words=filler_stats["total_words"],
        overall_score=report.get("overall_score"),
        skill_gaps=report.get("skill_gaps"),
        improvement_tips=report.get("improvement_tips"),
        detailed_feedback=report.get("summary"),
    )
    db.add(analytics)

    from datetime import datetime
    session.status = "completed"
    session.ended_at = datetime.utcnow()
    session.overall_score = report.get("overall_score")
    await db.commit()

    return {"report": report, "filler_stats": filler_stats, "scores": scores}


# ─── REST: Get Session ────────────────────────────────────────────────────────

@router.get("/session/{session_id}")
async def get_session(session_id: int, db: AsyncSession = Depends(get_db)):
    session = await db.get(InterviewSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    return {
        "session": {
            "id": session.id,
            "title": session.title,
            "mode": session.mode,
            "status": session.status,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "overall_score": session.overall_score,
            "current_q": (session.metadata_json or {}).get("current_q", 0),
            "total_questions": len((session.metadata_json or {}).get("questions", [])),
        },
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "score": m.score,
                "feedback": m.feedback,
                "filler_words": m.filler_words,
                "created_at": m.created_at,
            }
            for m in messages
        ],
    }
