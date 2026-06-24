from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from dotenv import load_dotenv

load_dotenv()

from services.database import get_db, InterviewSession, SessionAnalytics, Message

router = APIRouter()


@router.get("/user/{user_id}/overview")
async def user_overview(user_id: int, db: AsyncSession = Depends(get_db)):
    """Dashboard overview: all sessions + aggregate stats."""

    result = await db.execute(
        select(InterviewSession)
        .where(InterviewSession.user_id == user_id)
        .order_by(InterviewSession.started_at.desc())
    )
    sessions = result.scalars().all()

    session_ids = [s.id for s in sessions]
    analytics_map = {}
    if session_ids:
        ar = await db.execute(
            select(SessionAnalytics).where(SessionAnalytics.session_id.in_(session_ids))
        )
        analytics_map = {a.session_id: a for a in ar.scalars().all()}

    sessions_out = []
    for s in sessions:
        a = analytics_map.get(s.id)
        sessions_out.append({
            "id":            s.id,
            "title":         s.title,
            "mode":          s.mode,
            "status":        s.status,
            "overall_score": s.overall_score,
            "started_at":    s.started_at,
            "ended_at":      s.ended_at,
            "fluency_score": a.fluency_score if a else None,
            "filler_rate":   a.filler_word_rate if a else None,
        })

    scores  = [s["overall_score"] for s in sessions_out if s["overall_score"]]
    fluency = [s["fluency_score"] for s in sessions_out if s["fluency_score"]]

    return {
        "total_sessions":     len(sessions),
        "completed_sessions": sum(1 for s in sessions if s.status == "completed"),
        "avg_score":          round(sum(scores)  / len(scores),  1) if scores  else None,
        "avg_fluency":        round(sum(fluency) / len(fluency), 1) if fluency else None,
        "sessions":           sessions_out,
    }


@router.get("/session/{session_id}/report")
async def session_report(session_id: int, db: AsyncSession = Depends(get_db)):
    """Full report for a single session."""

    session = await db.get(InterviewSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    ar = await db.execute(
        select(SessionAnalytics).where(SessionAnalytics.session_id == session_id)
    )
    analytics = ar.scalar_one_or_none()

    mr = await db.execute(
        select(Message)
        .where(Message.session_id == session_id, Message.role == "candidate")
        .order_by(Message.created_at)
    )
    msgs = mr.scalars().all()

    answer_scores = [
        {
            "answer":      m.content[:200],
            "score":       m.score,
            "feedback":    m.feedback,
            "filler_words": m.filler_words,
        }
        for m in msgs
    ]

    return {
        "session": {
            "id":            session.id,
            "title":         session.title,
            "mode":          session.mode,
            "overall_score": session.overall_score,
            "started_at":    session.started_at,
            "ended_at":      session.ended_at,
        },
        "analytics": {
            "fluency_score":      analytics.fluency_score      if analytics else None,
            "avg_answer_quality": analytics.avg_answer_quality if analytics else None,
            "filler_word_count":  analytics.filler_word_count  if analytics else None,
            "filler_word_rate":   analytics.filler_word_rate   if analytics else None,
            "total_words":        analytics.total_words        if analytics else None,
            "skill_gaps":         analytics.skill_gaps         if analytics else [],
            "improvement_tips":   analytics.improvement_tips   if analytics else [],
            "detailed_feedback":  analytics.detailed_feedback  if analytics else "",
        },
        "answer_scores": answer_scores,
    }
