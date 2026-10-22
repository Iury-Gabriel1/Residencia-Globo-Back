from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Teleprompter Realtime API", version="1.0.0")
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
allowed_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])

# Estado em memória: adequado para protótipo, não para múltiplas instâncias em produção.
sessions: dict[str, dict[str, Any]] = {}
connections: dict[str, set[WebSocket]] = defaultdict(set)
session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class SessionState(BaseModel):
    selectedStory: int = Field(default=0, ge=0)
    pageIndex: int = Field(default=0, ge=0)
    paused: bool = False
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    fontSize: int = Field(default=36, ge=18, le=72)
    editorialStories: list[dict[str, Any]] = Field(default_factory=list)
    operatorOverride: bool = False


class StateUpdate(BaseModel):
    state: SessionState


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "Teleprompter Realtime API", "docs": "/docs", "health": "/api/health"}


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "teleprompter-realtime"}


@app.get("/api/sessions/{session_id}/state")
async def get_session_state(session_id: str) -> dict[str, Any]:
    return {"sessionId": session_id, "state": sessions.get(session_id)}


async def broadcast(session_id: str, message: dict[str, Any], exclude: WebSocket | None = None) -> None:
    stale = []
    for socket in list(connections[session_id]):
        if socket is exclude:
            continue
        try:
            await socket.send_json(message)
        except Exception:
            stale.append(socket)
    for socket in stale:
        connections[session_id].discard(socket)


@app.post("/api/sessions/{session_id}/state")
async def update_session_state(session_id: str, update: StateUpdate) -> dict[str, Any]:
    state = update.state.model_dump()
    async with session_locks[session_id]:
        sessions[session_id] = state
        await broadcast(session_id, {"type": "state", "sessionId": session_id, "state": state, "source": "http"})
    return {"ok": True, "sessionId": session_id, "state": state}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    connections[session_id].add(websocket)
    await websocket.send_json({"type": "welcome", "sessionId": session_id,
                               "state": sessions.get(session_id), "clients": len(connections[session_id])})
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if kind not in {"sync", "command"}:
                await websocket.send_json({"type": "error", "message": "Tipo de mensagem não reconhecido."})
                continue
            if kind == "command" and message.get("command") not in {
                "pause", "resume", "next", "previous", "select_story", "select_page", "take_control"
            }:
                await websocket.send_json({"type": "error", "message": "Comando não reconhecido."})
                continue
            raw_state = message.get("state")
            if not isinstance(raw_state, dict):
                await websocket.send_json({"type": "error", "message": "O campo state precisa ser um objeto."})
                continue
            try:
                state = SessionState.model_validate(raw_state).model_dump()
            except Exception as exc:
                await websocket.send_json({"type": "error", "message": f"Estado inválido: {exc}"})
                continue
            async with session_locks[session_id]:
                sessions[session_id] = state
                outgoing = {"type": kind if kind == "command" else "state",
                            "sessionId": session_id, "state": state, "source": message.get("clientId")}
                if kind == "command":
                    outgoing["command"] = message.get("command")
                await broadcast(session_id, outgoing, exclude=websocket)
    except WebSocketDisconnect:
        pass
    finally:
        connections[session_id].discard(websocket)
        if not connections[session_id]:
            connections.pop(session_id, None)
