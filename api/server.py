from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.ceo_agent import CEOAgent
from agents.engineer_agent import EngineerAgent
from agents.marketing_agent import MarketingAgent
from agents.product_agent import ProductAgent
from api.websocket_manager import WebSocketManager
from bus.redis_bus import RedisBus
from config import get_settings
from tools.email_tools import EmailTools
from tools.github_tools import GitHubTools
from tools.llm_tools import LLMTools
from tools.slack_tools import SlackTools

logger = logging.getLogger("launchmind")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


class LaunchRequest(BaseModel):
    startup_idea: str = (
        "GradTrack - AI-powered job application tracker for final-year university students"
    )


def create_app() -> FastAPI:
    app = FastAPI(title="LaunchMind")
    settings = get_settings(validate=False)
    bus = RedisBus(settings.redis_url)
    ws_manager = WebSocketManager()
    run_lock = threading.Lock()

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    app.mount("/frontend", StaticFiles(directory=str(frontend_dir)), name="frontend")

    def emit_event(event_type: str, agent: str, data: Dict[str, Any]) -> None:
        event = {
            "event_type": event_type,
            "agent": agent,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        ws_manager.broadcast_from_thread(event)

    bus.set_broadcast_hook(lambda event: ws_manager.broadcast_from_thread(event))

    @app.on_event("startup")
    async def startup() -> None:
        ws_manager.set_loop(asyncio.get_running_loop())

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(frontend_dir / "index.html")

    @app.get("/api/history")
    async def get_history() -> JSONResponse:
        return JSONResponse({"history": bus.get_full_history()})

    @app.post("/api/launch")
    async def launch(body: LaunchRequest) -> JSONResponse:
        try:
            current_settings = get_settings(validate=True)
        except ValueError as exc:
            return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

        if not run_lock.acquire(blocking=False):
            return JSONResponse(
                {"status": "busy", "message": "A launch is already running"},
                status_code=409,
            )

        def _run() -> None:
            try:
                llm = LLMTools(current_settings, emit_event=emit_event)
                github = GitHubTools(current_settings)
                slack = SlackTools(current_settings)
                email = EmailTools(current_settings)

                ceo = CEOAgent(
                    bus=bus,
                    llm=llm,
                    product_agent=ProductAgent(bus, llm),
                    engineer_agent=EngineerAgent(bus, llm, github),
                    marketing_agent=MarketingAgent(bus, llm, email, slack),
                    slack_tools=slack,
                    emit_event=emit_event,
                )
                result = ceo.run(body.startup_idea)
                if result.get("status") == "failed":
                    logger.error(
                        "Launch run failed: reason=%s details=%s",
                        result.get("reason"),
                        result.get("details"),
                    )
            except Exception as exc:
                logger.exception("Unhandled runtime exception in launch thread")
                emit_event(
                    "system_complete",
                    "ceo",
                    {
                        "status": "failed",
                        "reason": "Unhandled runtime exception",
                        "details": str(exc),
                    },
                )
            finally:
                run_lock.release()

        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started"})

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await ws_manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    return app
