from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    PageRecord,
    SessionRecord,
    StoryRecord,
    close_database,
    init_database,
    session_factory,
)

DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
logger = logging.getLogger("teleprompter")
allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", DEFAULT_ORIGINS).split(",")
    if origin.strip()
]
connections: dict[str, set[WebSocket]] = defaultdict(set)
session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class ScriptPage(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    label: str
    text: str
    secondary: str | None = None
    keywords: list[str] = Field(default_factory=list)


class ScriptStory(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    code: str
    headline: str
    category: str
    tone: str
    guidance: str = ""
    alertLevel: str | None = None
    pages: list[ScriptPage] = Field(min_length=1)


class SessionState(BaseModel):
    selectedStory: int = Field(default=0, ge=0)
    pageIndex: int = Field(default=0, ge=0)
    paused: bool = False
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    fontSize: int = Field(default=36, ge=18, le=72)
    editorialStories: list[ScriptStory] = Field(default_factory=list)
    operatorOverride: bool = False
    readingPreferences: dict[str, Any] = Field(default_factory=dict)


class StateUpdate(BaseModel):
    state: SessionState


class RundownImport(BaseModel):
    stories: list[ScriptStory] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> RundownImport:
        story_ids = [story.id for story in self.stories]
        if len(set(story_ids)) != len(story_ids):
            raise ValueError("O espelho contém IDs de matérias duplicados.")
        for story in self.stories:
            page_ids = [page.id for page in story.pages]
            if len(set(page_ids)) != len(page_ids):
                raise ValueError(f"A matéria {story.code} contém IDs de páginas duplicados.")
        return self


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_database()
    yield
    await close_database()


app = FastAPI(
    title="Teleprompter Realtime API",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


async def read_session(db: AsyncSession, session_id: str) -> dict[str, Any] | None:
    record = await db.get(SessionRecord, session_id)
    if record is None:
        return None

    stories = (
        await db.execute(
            select(StoryRecord)
            .where(StoryRecord.session_id == session_id)
            .order_by(StoryRecord.position)
        )
    ).scalars().all()
    pages = (
        await db.execute(
            select(PageRecord)
            .where(PageRecord.session_id == session_id)
            .order_by(PageRecord.story_position, PageRecord.position)
        )
    ).scalars().all()
    pages_by_story: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        page_data = {
            "id": page.page_id,
            "title": page.title,
            "label": page.label,
            "text": page.text,
            "keywords": page.keywords,
            **page.extra_data,
        }
        if page.secondary is not None:
            page_data["secondary"] = page.secondary
        pages_by_story[page.story_id].append(page_data)

    editorial_stories = []
    for story in stories:
        story_data = {
            "id": story.story_id,
            "code": story.code,
            "headline": story.headline,
            "category": story.category,
            "tone": story.tone,
            "guidance": story.guidance,
            "pages": pages_by_story[story.story_id],
            **story.extra_data,
        }
        if story.alert_level is not None:
            story_data["alertLevel"] = story.alert_level
        editorial_stories.append(story_data)

    return {
        "selectedStory": record.selected_story,
        "pageIndex": record.page_index,
        "paused": record.paused,
        "speed": record.speed,
        "fontSize": record.font_size,
        "editorialStories": editorial_stories,
        "operatorOverride": record.operator_override,
        "readingPreferences": record.reading_preferences,
    }


async def save_session(
    db: AsyncSession, session_id: str, state: SessionState
) -> dict[str, Any]:
    state_data = state.model_dump(exclude_none=True)
    record = await db.get(SessionRecord, session_id)
    if record is None:
        record = SessionRecord(session_id=session_id)
        db.add(record)

    record.selected_story = state.selectedStory
    record.page_index = state.pageIndex
    record.paused = state.paused
    record.speed = state.speed
    record.font_size = state.fontSize
    record.operator_override = state.operatorOverride
    record.reading_preferences = state.readingPreferences

    await db.execute(delete(PageRecord).where(PageRecord.session_id == session_id))
    await db.execute(delete(StoryRecord).where(StoryRecord.session_id == session_id))
    for story_position, story in enumerate(state.editorialStories):
        story_data = story.model_dump()
        pages_data = story_data.pop("pages")
        extra_data = {
            key: value
            for key, value in story_data.items()
            if key not in {"id", "code", "headline", "category", "tone", "guidance", "alertLevel"}
        }
        db.add(
            StoryRecord(
                session_id=session_id,
                story_id=story.id,
                position=story_position,
                code=story.code,
                headline=story.headline,
                category=story.category,
                tone=story.tone,
                guidance=story.guidance,
                alert_level=story.alertLevel,
                extra_data=extra_data,
            )
        )
        for page_position, page in enumerate(pages_data):
            page_extra_data = {
                key: value
                for key, value in page.items()
                if key not in {"id", "title", "label", "text", "secondary", "keywords"}
            }
            db.add(
                PageRecord(
                    session_id=session_id,
                    story_id=story.id,
                    story_position=story_position,
                    page_id=page["id"],
                    position=page_position,
                    title=page["title"],
                    label=page["label"],
                    text=page["text"],
                    secondary=page.get("secondary"),
                    keywords=page.get("keywords", []),
                    extra_data=page_extra_data,
                )
            )

    await db.commit()
    return state_data


async def broadcast(
    session_id: str, message: dict[str, Any], exclude: WebSocket | None = None
) -> None:
    stale: list[WebSocket] = []
    for socket in list(connections[session_id]):
        if socket is exclude:
            continue
        try:
            await socket.send_json(message)
        except (WebSocketDisconnect, RuntimeError, OSError):
            stale.append(socket)
    for socket in stale:
        connections[session_id].discard(socket)


def execute_command(state: SessionState, message: dict[str, Any]) -> SessionState:
    command = message.get("command")
    if command == "pause":
        state.paused = True
    elif command == "resume":
        state.paused = False
    elif command == "take_control":
        state.operatorOverride = True
        state.paused = True
    elif command in {"next", "previous"}:
        if state.editorialStories:
            story_index = min(state.selectedStory, len(state.editorialStories) - 1)
            pages = state.editorialStories[story_index].pages
            page_index = min(state.pageIndex, len(pages) - 1) if pages else 0
            if command == "next" and pages and page_index < len(pages) - 1:
                state.pageIndex = page_index + 1
            elif command == "next" and story_index < len(state.editorialStories) - 1:
                state.selectedStory = story_index + 1
                state.pageIndex = 0
            elif command == "previous" and page_index > 0:
                state.pageIndex = page_index - 1
            elif command == "previous" and story_index > 0:
                state.selectedStory = story_index - 1
                state.pageIndex = len(state.editorialStories[story_index - 1].pages) - 1
        state.operatorOverride = True
        state.paused = True
    elif command == "select_story":
        story_index = message.get("selectedStory", message.get("value"))
        if not isinstance(story_index, int) or not 0 <= story_index < len(state.editorialStories):
            raise ValueError("Índice de matéria inválido.")
        state.selectedStory = story_index
        state.pageIndex = 0
        state.operatorOverride = True
        state.paused = True
    elif command == "select_page":
        page_index = message.get("pageIndex", message.get("value"))
        if (
            not isinstance(page_index, int)
            or not 0 <= state.selectedStory < len(state.editorialStories)
            or not 0 <= page_index < len(state.editorialStories[state.selectedStory].pages)
        ):
            raise ValueError("Índice de página inválido.")
        state.pageIndex = page_index
        state.operatorOverride = True
        state.paused = True
    else:
        raise ValueError("Comando não reconhecido.")
    return state


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "Teleprompter Realtime API",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/api/health")
async def health() -> dict[str, str]:
    async with session_factory() as db:
        await db.execute(select(1))
    return {"status": "ok", "service": "teleprompter-realtime"}


@app.get("/api/sessions/{session_id}/state")
async def get_session_state(session_id: str) -> dict[str, Any]:
    async with session_factory() as db:
        state = await read_session(db, session_id)
    return {"sessionId": session_id, "state": state}


@app.post("/api/sessions/{session_id}/state")
async def update_session_state(session_id: str, update: StateUpdate) -> dict[str, Any]:
    async with session_locks[session_id]:
        async with session_factory() as db:
            state = await save_session(db, session_id, update.state)
        await broadcast(
            session_id,
            {"type": "state", "sessionId": session_id, "state": state, "source": "http"},
        )
    return {"ok": True, "sessionId": session_id, "state": state}


@app.post("/api/sessions/{session_id}/rundown")
async def import_rundown(session_id: str, rundown: RundownImport) -> dict[str, Any]:
    async with session_locks[session_id]:
        async with session_factory() as db:
            current_data = await read_session(db, session_id)
            if current_data is None:
                current_data = SessionState().model_dump()
            current_data["editorialStories"] = [
                story.model_dump() for story in rundown.stories
            ]
            current_data["selectedStory"] = 0
            current_data["pageIndex"] = 0
            current_data["paused"] = True
            current_data["operatorOverride"] = True
            state = SessionState.model_validate(current_data)
            saved_state = await save_session(db, session_id, state)
        await broadcast(
            session_id,
            {
                "type": "state",
                "sessionId": session_id,
                "state": saved_state,
                "source": "rundown-import",
            },
        )
    return {
        "ok": True,
        "sessionId": session_id,
        "storiesImported": len(state.editorialStories),
        "pagesImported": sum(len(story.pages) for story in state.editorialStories),
        "state": saved_state,
    }


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    try:
        async with session_factory() as db:
            current_state = await read_session(db, session_id)
        connections[session_id].add(websocket)
        await websocket.send_json(
            {
                "type": "welcome",
                "sessionId": session_id,
                "state": current_state,
                "clients": len(connections[session_id]),
            }
        )
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                await websocket.send_json(
                    {"type": "error", "message": "A mensagem precisa ser um objeto."}
                )
                continue
            kind = message.get("type")
            if kind == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if kind not in {"sync", "command"}:
                await websocket.send_json(
                    {"type": "error", "message": "Tipo de mensagem não reconhecido."}
                )
                continue
            try:
                async with session_locks[session_id]:
                    async with session_factory() as db:
                        if kind == "sync":
                            state = SessionState.model_validate(message.get("state"))
                        else:
                            raw_state = message.get("state")
                            if raw_state is None:
                                raw_state = await read_session(db, session_id)
                            state = SessionState.model_validate(raw_state or {})
                            state = execute_command(state, message)
                        saved_state = await save_session(db, session_id, state)
                    outgoing = {
                        "type": "state" if kind == "sync" else "command",
                        "sessionId": session_id,
                        "state": saved_state,
                        "source": message.get("clientId"),
                    }
                    if kind == "command":
                        outgoing["command"] = message.get("command")
                    await broadcast(
                        session_id,
                        outgoing,
                        exclude=websocket if kind == "sync" else None,
                    )
            except (ValidationError, ValueError) as exc:
                await websocket.send_json(
                    {"type": "error", "message": f"Estado ou comando inválido: {exc}"}
                )
            except Exception:
                logger.exception("Falha ao processar mensagem WebSocket da sessão %s", session_id)
                await websocket.send_json(
                    {"type": "error", "message": "Falha ao processar ou persistir a mensagem."}
                )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Falha na conexão WebSocket da sessão %s", session_id)
        try:
            await websocket.close(code=1011, reason="Falha interna do servidor.")
        except RuntimeError:
            pass
    finally:
        connections[session_id].discard(websocket)
        if not connections[session_id]:
            connections.pop(session_id, None)
