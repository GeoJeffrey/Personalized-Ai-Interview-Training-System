from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import os, uuid, aiofiles
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from services.database import get_db, Document
from services.parser import extract_text

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MAX_SIZE_MB = 15


@router.post("/document")
async def upload_document(
    file: UploadFile = File(...),
    user_id: int = Form(...),
    doc_type: str = Form(...),   # resume | jd | prep_material
    db: AsyncSession = Depends(get_db),
):
    # ── Validate extension ────────────────────────────────────────────────────
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # ── Read and size-check ───────────────────────────────────────────────────
    content = await file.read()
    if len(content) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"File too large. Max {MAX_SIZE_MB} MB.")

    # ── Save file to disk ─────────────────────────────────────────────────────
    upload_dir = os.getenv("UPLOAD_DIR", "./uploads")
    os.makedirs(upload_dir, exist_ok=True)
    saved_name = f"{uuid.uuid4()}{ext}"
    saved_path = os.path.join(upload_dir, saved_name)

    async with aiofiles.open(saved_path, "wb") as f:
        await f.write(content)

    # ── Extract text via MarkItDown ───────────────────────────────────────────
    try:
        md_text = extract_text(saved_path)
    except Exception as e:
        os.remove(saved_path)
        raise HTTPException(500, f"Could not parse file: {e}")

    # ── Save to database ──────────────────────────────────────────────────────
    doc = Document(
        user_id=user_id,
        filename=file.filename,
        doc_type=doc_type,
        file_path=saved_path,
        text_content=md_text,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    return {
        "doc_id":       doc.id,
        "filename":     doc.filename,
        "doc_type":     doc.doc_type,
        "char_count":   len(md_text),
        "token_est":    len(md_text) // 4,
        "text_preview": md_text[:400] + "…" if len(md_text) > 400 else md_text,
    }


@router.get("/document/{user_id}")
async def list_documents(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return [
        {
            "id":         d.id,
            "filename":   d.filename,
            "doc_type":   d.doc_type,
            "char_count": len(d.text_content or ""),
            "created_at": d.created_at,
        }
        for d in docs
    ]


@router.get("/document/{user_id}/{doc_id}/text")
async def get_document_text(
    user_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.user_id == user_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Document not found")
    return {"doc_id": doc.id, "text": doc.text_content}