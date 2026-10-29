"""Same-origin local API and production frontend serving."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from review_app.store import ReviewStore


def create_app(
    store: ReviewStore, frontend: Path | None = None, sync: bool = True, online: bool = True
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(refresh_loop(store, online)) if sync else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="Codex Review App", lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "app": "codex-review-app"}

    @app.get("/api/sessions")
    def sessions(instance: Literal["claude", "codex"] = "claude") -> dict:
        return store.catalog(instance)

    @app.get("/api/sessions/{day}")
    def session(day: date, instance: Literal["claude", "codex"] = "claude") -> dict:
        if day.isoformat() not in {s["date"] for s in store.catalog(instance)["sessions"]}:
            raise HTTPException(404, "Session is outside the six-session review window")
        return store.session(day.isoformat(), instance)

    if frontend and (frontend / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(frontend / "index.html")

    return app


async def refresh_loop(store: ReviewStore, online: bool) -> None:
    while True:
        await asyncio.to_thread(store.synchronize, online)
        await asyncio.sleep(60)
