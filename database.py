from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


load_dotenv()


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url


DATABASE_URL = normalize_database_url(
    os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./teleprompter.db")
)
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "teleprompter_sessions"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    selected_story: Mapped[int] = mapped_column(Integer, default=0)
    page_index: Mapped[int] = mapped_column(Integer, default=0)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    speed: Mapped[float] = mapped_column(default=1.0)
    font_size: Mapped[int] = mapped_column(Integer, default=36)
    operator_override: Mapped[bool] = mapped_column(Boolean, default=False)
    reading_preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class StoryRecord(Base):
    __tablename__ = "teleprompter_stories"
    __table_args__ = (UniqueConstraint("session_id", "position"),)

    session_id: Mapped[str] = mapped_column(
        ForeignKey("teleprompter_sessions.session_id"), primary_key=True
    )
    story_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(128))
    headline: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(128))
    tone: Mapped[str] = mapped_column(String(256))
    guidance: Mapped[str] = mapped_column(Text, default="")
    alert_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PageRecord(Base):
    __tablename__ = "teleprompter_pages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "story_id"],
            ["teleprompter_stories.session_id", "teleprompter_stories.story_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("session_id", "story_id", "position"),
    )

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    story_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    page_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    story_position: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(256))
    text: Mapped[str] = mapped_column(Text)
    secondary: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


async def init_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def close_database() -> None:
    await engine.dispose()
