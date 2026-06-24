from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from services.database import get_db, User

router = APIRouter()


class CreateUserRequest(BaseModel):
    email: str
    name: str = ""


@router.post("/user")
async def create_user(req: CreateUserRequest, db: AsyncSession = Depends(get_db)):
    """Create or get existing user by email."""

    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if user:
        return {
            "user_id":  user.id,
            "email":    user.email,
            "name":     user.name,
            "existing": True,
        }

    user = User(email=req.email, name=req.name)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return {
        "user_id":  user.id,
        "email":    user.email,
        "name":     user.name,
        "existing": False,
    }
