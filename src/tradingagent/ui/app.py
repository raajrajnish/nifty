"""Local dashboard (DESIGN.md §6). A client of the Runtime: it cannot edit config, stops or quantity.

Allowed writes: connect Groww, kill, resume (+ approve/reject from Phase 6).
"""

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from tradingagent.core.events import Event
from tradingagent.orchestrator.runtime import Runtime
from tradingagent.ui.auth import Session, SessionStore

_HERE = Path(__file__).parent
COOKIE = "ta_session"


class LoginBody(BaseModel):
    passphrase: str = Field(min_length=1, max_length=256)


class KillBody(BaseModel):
    confirm: str
    reason: str = Field(default="manual kill from dashboard", max_length=300)


class ResumeBody(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


def create_app(runtime: Runtime, sessions: SessionStore,
               background: list[Callable[[], Coroutine[Any, Any, None]]] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(fn()) for fn in (background or [])]
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="tradingagent", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    templates = Jinja2Templates(directory=str(_HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    port = runtime.cfg.ui.port
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", "testserver"}
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", "http://testserver"}

    candles: deque[dict[str, Any]] = deque(maxlen=300)
    recent: deque[dict[str, Any]] = deque(maxlen=200)

    def _buffer(evt: Event) -> None:
        if evt.type == "CANDLE":
            candles.append(evt.payload["candle"])
        else:
            recent.append(evt.to_dict())

    runtime.bus.subscribe(_buffer)

    @app.middleware("http")
    async def _guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # DNS-rebinding and cross-site protection: only our own host/origin may talk to us.
        if request.headers.get("host") not in allowed_hosts:
            return JSONResponse({"error": "bad host"}, status_code=400)
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin is not None and origin not in allowed_origins:
                return JSONResponse({"error": "bad origin"}, status_code=403)
        resp = await call_next(request)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def session(request: Request) -> Session:
        sess = sessions.get(request.cookies.get(COOKIE))
        if sess is None:
            raise HTTPException(401, "login required")
        return sess

    def csrf(request: Request, sess: Session = Depends(session)) -> Session:
        if request.headers.get("x-csrf-token") != sess.csrf:
            raise HTTPException(403, "bad csrf token")
        return sess

    def ui_action(action: str, **detail: Any) -> None:
        runtime.bus.publish("UI_ACTION", runtime.clock.now(), {"action": action, **detail})

    # ---- pages -------------------------------------------------------------------------------
    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> Response:
        if not runtime.cfg.ui.require_login:
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "login.html",
                                          {"configured": sessions.configured, "locked": sessions.locked_out})

    @app.post("/login")
    async def login(body: LoginBody) -> Response:
        result = sessions.login(body.passphrase)
        ui_action("login", ok=result is not None)
        if result is None:
            return JSONResponse({"error": "invalid passphrase (or locked out for 5 min)"}, status_code=401)
        sid, _ = result
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, sid, httponly=True, samesite="strict",
                        max_age=runtime.cfg.ui.session_hours * 3600)
        return resp

    @app.post("/logout")
    async def logout(request: Request, _: Session = Depends(csrf)) -> Response:
        sessions.logout(request.cookies.get(COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> Response:
        sess = sessions.get(request.cookies.get(COOKIE))
        new_sid = None
        if sess is None:
            if runtime.cfg.ui.require_login:
                return RedirectResponse("/login", status_code=303)
            new_sid, sess = sessions.auto_login()  # dev mode: no passphrase, but still a CSRF-bound session
        resp = templates.TemplateResponse(request, "dashboard.html",
                                          {"csrf": sess.csrf, "require_login": runtime.cfg.ui.require_login})
        if new_sid:
            resp.set_cookie(COOKIE, new_sid, httponly=True, samesite="strict",
                            max_age=runtime.cfg.ui.session_hours * 3600)
        return resp

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # ---- read API ----------------------------------------------------------------------------
    @app.get("/api/state")
    async def state(_: Session = Depends(session)) -> dict[str, Any]:
        return runtime.snapshot()

    @app.get("/api/overview")
    async def overview(_: Session = Depends(session)) -> dict[str, Any]:
        return runtime.overview()

    @app.get("/api/paper")
    async def paper(_: Session = Depends(session)) -> dict[str, Any]:
        return runtime.paper_snapshot()

    @app.get("/api/candles")
    async def get_candles(_: Session = Depends(session)) -> list[dict[str, Any]]:
        return list(candles)

    @app.get("/api/events")
    async def get_events(_: Session = Depends(session)) -> list[dict[str, Any]]:
        return list(recent)

    @app.get("/api/stream")
    async def stream(request: Request, _: Session = Depends(session)) -> StreamingResponse:
        q = runtime.bus.open_queue()

        async def gen() -> AsyncIterator[str]:
            try:
                yield "retry: 3000\n\n"
                while not await request.is_disconnected():
                    try:
                        evt = await asyncio.wait_for(q.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"event: {evt.type}\ndata: {json.dumps(evt.to_dict(), default=str)}\n\n"
            finally:
                runtime.bus.close_queue(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    # ---- owner actions (the only writes the UI may perform) ----------------------------------
    @app.post("/api/auth/groww")
    async def connect_groww(_: Session = Depends(csrf)) -> dict[str, Any]:
        ui_action("connect_groww")
        return await runtime.connect_broker(source="ui")

    @app.post("/api/kill")
    async def kill(body: KillBody, _: Session = Depends(csrf)) -> dict[str, Any]:
        if body.confirm != "KILL":
            raise HTTPException(400, 'type KILL to confirm')
        ui_action("kill", reason=body.reason)
        runtime.halt(body.reason, source="ui")
        return runtime.snapshot()

    @app.post("/api/resume")
    async def resume(body: ResumeBody, _: Session = Depends(csrf)) -> dict[str, Any]:
        ui_action("resume", reason=body.reason)
        runtime.resume(body.reason, source="ui")
        return runtime.snapshot()

    return app
