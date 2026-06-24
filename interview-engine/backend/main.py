from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from routers import interview, upload, analytics, session
from services.database import create_tables
from dotenv import load_dotenv

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await create_tables()
    os.makedirs(os.getenv("UPLOAD_DIR", "./uploads"), exist_ok=True)
    print("✅ Interview Engine backend started")
    yield
    # Shutdown
    print("👋 Shutting down")

app = FastAPI(
    title="Interview Engine API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving for uploaded PDFs
app.mount("/uploads", StaticFiles(directory=os.getenv("UPLOAD_DIR", "./uploads")), name="uploads")

# Routers
app.include_router(interview.router, prefix="/api/interview", tags=["interview"])
app.include_router(upload.router,    prefix="/api/upload",    tags=["upload"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(session.router,   prefix="/api/session",   tags=["session"])

@app.get("/health")
async def health():
    return {"status": "ok", "service": "Interview Engine"}