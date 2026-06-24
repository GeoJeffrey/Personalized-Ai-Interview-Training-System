from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Text, Float, Integer, DateTime, ForeignKey, JSON
from datetime import datetime
from typing import Optional, List
import os

# ── Database URL ──────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./interview_engine.db")

# Convert postgres:// → postgresql+asyncpg:// for async
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

# ── Models ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True)
    email:      Mapped[str]           = mapped_column(String(255), unique=True, index=True)
    name:       Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    sessions:   Mapped[List["InterviewSession"]] = relationship(back_populates="user")
    documents:  Mapped[List["Document"]]         = relationship(back_populates="user")


class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    id:            Mapped[int]            = mapped_column(Integer, primary_key=True)
    user_id:       Mapped[int]            = mapped_column(ForeignKey("users.id"), index=True)
    title:         Mapped[str]            = mapped_column(String(255))
    mode:          Mapped[str]            = mapped_column(String(50), default="standard")
    status:        Mapped[str]            = mapped_column(String(50), default="active")
    jd_text:       Mapped[Optional[str]]  = mapped_column(Text)
    resume_text:   Mapped[Optional[str]]  = mapped_column(Text)
    overall_score: Mapped[Optional[float]]= mapped_column(Float)
    started_at:    Mapped[datetime]       = mapped_column(DateTime, default=datetime.utcnow)
    ended_at:      Mapped[Optional[datetime]] = mapped_column(DateTime)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    user:          Mapped["User"]         = relationship(back_populates="sessions")
    messages:      Mapped[List["Message"]]= relationship(back_populates="session", order_by="Message.created_at")
    analytics:     Mapped[Optional["SessionAnalytics"]] = relationship(back_populates="session", uselist=False)


class Message(Base):
    __tablename__ = "messages"
    id:           Mapped[int]            = mapped_column(Integer, primary_key=True)
    session_id:   Mapped[int]            = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    role:         Mapped[str]            = mapped_column(String(20))
    content:      Mapped[str]            = mapped_column(Text)
    score:        Mapped[Optional[float]]= mapped_column(Float)
    feedback:     Mapped[Optional[str]]  = mapped_column(Text)
    filler_words: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at:   Mapped[datetime]       = mapped_column(DateTime, default=datetime.utcnow)
    session:      Mapped["InterviewSession"] = relationship(back_populates="messages")


class Document(Base):
    __tablename__ = "documents"
    id:           Mapped[int]            = mapped_column(Integer, primary_key=True)
    user_id:      Mapped[int]            = mapped_column(ForeignKey("users.id"), index=True)
    filename:     Mapped[str]            = mapped_column(String(255))
    doc_type:     Mapped[str]            = mapped_column(String(50))
    file_path:    Mapped[str]            = mapped_column(String(512))
    text_content: Mapped[Optional[str]]  = mapped_column(Text)
    created_at:   Mapped[datetime]       = mapped_column(DateTime, default=datetime.utcnow)
    user:         Mapped["User"]         = relationship(back_populates="documents")


class SessionAnalytics(Base):
    __tablename__ = "session_analytics"
    id:                 Mapped[int]            = mapped_column(Integer, primary_key=True)
    session_id:         Mapped[int]            = mapped_column(ForeignKey("interview_sessions.id"), unique=True)
    fluency_score:      Mapped[Optional[float]]= mapped_column(Float)
    avg_answer_quality: Mapped[Optional[float]]= mapped_column(Float)
    filler_word_count:  Mapped[Optional[int]]  = mapped_column(Integer)
    filler_word_rate:   Mapped[Optional[float]]= mapped_column(Float)
    total_words:        Mapped[Optional[int]]  = mapped_column(Integer)
    eye_contact_score:  Mapped[Optional[float]]= mapped_column(Float)
    skill_gaps:         Mapped[Optional[dict]] = mapped_column(JSON)
    improvement_tips:   Mapped[Optional[dict]] = mapped_column(JSON)
    detailed_feedback:  Mapped[Optional[str]]  = mapped_column(Text)
    session:            Mapped["InterviewSession"] = relationship(back_populates="analytics")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
