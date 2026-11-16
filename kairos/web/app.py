"""Local-first research API. Public deployments require an owner password."""

import asyncio
import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from kairos.config.agent_definitions import get_agent_definition

from kairos.config.settings import get_settings
from kairos.observability.langfuse_tracing import flush_traces
from kairos.trading.approval import PaperApprovalService
from kairos.trading.megabull import MegabullClient, PaperOrder
from kairos.utils.security import validate_ticker
from kairos.web.runs import RunStore
from kairos.trading.market import MarketFeed, normalize_symbol
from kairos_config import CONFIG_DIR


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    risk: Literal["CONSERVATIVE", "NEUTRAL", "AGGRESSIVE"] = "NEUTRAL"
    source: Literal["live"] = "live"


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_token: str
    approved: StrictBool

    @field_validator("approved")
    @classmethod
    def require_approval(cls, value):
        if value is not True:
            raise ValueError("Explicit approval is required.")
        return value


class LoginRequest(BaseModel):
    password: str = ""


def create_app(data_dir: Path | None = None, runtime_dir: Path | None = None, paper_client=None):
    settings = get_settings()
    data_dir = (data_dir or settings.data_dir).resolve()
    runtime_dir = (runtime_dir or Path(os.environ.get("KAIROS_RUNTIME_DIR", str(data_dir / "runtime")))).resolve()
    runs = RunStore(runtime_dir / "research.db", data_dir)
    paper = PaperApprovalService(runtime_dir / "paper-orders.db", paper_client or MegabullClient())
    feed = MarketFeed(paper.client)
    password = os.environ.get("KAIROS_WEB_PASSWORD", "")
    # Persist the cookie-signing secret across restarts, outside source and frontend bundles.
    secret_file = runtime_dir / ".session-secret"
    if not secret_file.exists():
        try:
            with secret_file.open("x") as file:
                file.write(secrets.token_hex(32))
            secret_file.chmod(0o600)
        except FileExistsError:
            pass
    cookie_secret = secret_file.read_text().strip()

    def sign(session):
        import hmac
        return hmac.new(cookie_secret.encode(), session.encode(), hashlib.sha256).hexdigest()

    @asynccontextmanager
    async def lifespan(app):
        yield
        runs.worker.shutdown(wait=False, cancel_futures=True)
        flush_traces()

    app = FastAPI(title="KAIROS Research & Paper Trading", version="0.1.0", lifespan=lifespan)
    app.state.runs, app.state.paper = runs, paper

    @app.middleware("http")
    async def same_origin(request, call_next):
        origin = request.headers.get("origin")
        allowed = {str(request.base_url).rstrip("/")}
        if not password:
            allowed.update({"http://localhost:5173", "http://127.0.0.1:5173"})
        allowed.update(filter(None, os.environ.get("KAIROS_ALLOWED_ORIGINS", "").split(",")))
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in allowed:
            return Response("Cross-origin writes are forbidden", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    def owner(request: Request):
        cookie = request.cookies.get("kairos_session", "")
        session, _, signature = cookie.partition(".")
        if not session or not secrets.compare_digest(sign(session), signature):
            raise HTTPException(401, "Open a session before using KAIROS.")
        return session

    @app.get("/api/health")
    def health():
        return {"application": "KAIROS", "status": "ok", "environment": "paper-only", "owner_login_required": bool(password)}

    @app.post("/api/session")
    def session(body: LoginRequest, request: Request, response: Response):
        if password:
            if not secrets.compare_digest(body.password, password):
                raise HTTPException(401, "Incorrect workspace password.")
        elif request.client and request.client.host not in ("127.0.0.1", "::1", "testclient", "testserver"):
            raise HTTPException(403, "Remote access requires KAIROS_WEB_PASSWORD on the server.")
        existing = request.cookies.get("kairos_session", "")
        session_id, _, signature = existing.partition(".")
        if not session_id or not secrets.compare_digest(sign(session_id), signature):
            session_id = secrets.token_urlsafe(24)
        response.set_cookie("kairos_session",session_id+"."+sign(session_id),httponly=True,samesite="strict",secure=request.url.scheme=="https",max_age=86400*7)
        return {"application":"KAIROS","session":"ready","paper_trading_configured":bool(os.environ.get("MEGABULL_API_KEY"))}

    @app.get("/api/config")
    def configuration(user=Depends(owner)):
        return {"tickers":settings.target_tickers,"agents":[get_agent_definition(path.stem).role for path in sorted((CONFIG_DIR/"agents").glob("*.jsonc"))],
                "paper_trading_configured":bool(os.environ.get("MEGABULL_API_KEY")),"langfuse_configured":bool(os.environ.get("LANGFUSE_PUBLIC_KEY")),"default_source":"live"}

    @app.get("/api/runs")
    def list_runs(user=Depends(owner)):
        return runs.list(user)

    @app.post("/api/runs",status_code=202)
    def start_run(body: ResearchRequest,user=Depends(owner)):
        try:
            ticker=normalize_symbol(body.ticker).removesuffix(".NS")
        except ValueError as exc:
            raise HTTPException(422,str(exc))
        try:
            run_id=runs.create(user,ticker,body.risk,body.source)
        except ValueError as exc:
            raise HTTPException(409,str(exc))
        return {"id":run_id,"status":"QUEUED"}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id:str,user=Depends(owner)):
        result=runs.get(run_id,user)
        if result is None:
            raise HTTPException(404,"Research run not found.")
        return result

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id:str,request:Request,after:int=0,user=Depends(owner)):
        if runs.get(run_id,user) is None:
            raise HTTPException(404,"Research run not found.")
        try:
            after=max(after,int(request.headers.get("Last-Event-ID","0")))
        except ValueError:
            raise HTTPException(422,"Invalid event cursor.")
        async def stream():
            cursor=after
            while not await request.is_disconnected():
                batch=runs.events(run_id,cursor)
                for event in batch:
                    cursor=event["id"]
                    yield f'id: {cursor}\ndata: {json.dumps(event)}\n\n'
                state=runs.get(run_id,user)
                if state["status"] in ("COMPLETED","FAILED","INTERRUPTED") and not batch:
                    break
                if not batch:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(.3)
        return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

    @app.get("/api/market/{ticker}")
    def market(ticker:str,user=Depends(owner)):
        try:
            result=feed.candles(ticker,"3mo")
            points=[{"date":str(pd.Timestamp(bar["time"],unit="s"))[:10],"close":bar["close"]} for bar in result["bars"]]
            return {"ticker":ticker,"source":result["source"],"as_of":points[-1]["date"],"points":points}
        except Exception:
            raise HTTPException(502,"Fresh market chart is unavailable. Retry when the provider recovers.") from None

    @app.get("/api/stocks/search")
    def stock_search(q: str, user=Depends(owner)):
        try:
            return {"results":feed.search(q)}
        except Exception as exc:
            raise HTTPException(502,"Stock search is unavailable. Retry with a company name or full exchange symbol.") from None

    @app.get("/api/paper/market/{symbol}")
    def paper_market(symbol: str, user=Depends(owner)):
        try:
            return feed.quote(symbol)
        except Exception as exc:
            raise HTTPException(502,str(exc) if isinstance(exc,ValueError) else "Quote provider is unavailable. Retry later.") from None

    @app.get("/api/paper/candles/{symbol}")
    def paper_candles(symbol: str, period: str = "1d", user=Depends(owner)):
        try:
            return feed.candles(symbol,period)
        except Exception as exc:
            raise HTTPException(502,str(exc) if isinstance(exc,ValueError) else "Chart provider is unavailable. Retry later.") from None

    @app.get("/api/paper/account")
    def account(user=Depends(owner)):
        try:
            return paper.client.account()
        except ValueError as exc:
            raise HTTPException(502,str(exc))

    @app.get("/api/paper/orders")
    def paper_orders(user=Depends(owner)):
        try:
            return {"approvals":paper.history(user),"provider_orders":paper.client.orders()}
        except ValueError as exc:
            raise HTTPException(502,str(exc))

    @app.get("/api/paper/positions")
    def positions(user=Depends(owner)):
        try:
            return {"positions":paper.client.positions(),"holdings":paper.client.holdings()}
        except ValueError as exc:
            raise HTTPException(502,str(exc))

    @app.post("/api/paper/preview")
    def preview(body:PaperOrder,user=Depends(owner)):
        try:
            return paper.preview(body,user)
        except ValueError as exc:
            raise HTTPException(422,str(exc))

    @app.post("/api/paper/approvals/{approval_id}")
    def approve(approval_id:str,body:ApprovalRequest,user=Depends(owner)):
        try:
            return paper.approve(approval_id,body.approval_token,user)
        except ValueError as exc:
            raise HTTPException(409,str(exc))

    web_dist=Path(os.environ.get("KAIROS_WEB_DIST",str(Path(__file__).resolve().parents[2]/"web/dist")))
    if web_dist.exists():
        app.mount("/assets",StaticFiles(directory=web_dist/"assets"),name="assets")
        @app.get("/{path:path}")
        def frontend(path:str):
            if path.startswith(("api/", "a2a/")):
                raise HTTPException(404,"Endpoint not found.")
            return FileResponse(web_dist/"index.html")
    return app


def main():
    import uvicorn
    host=os.environ.get("KAIROS_WEB_HOST","127.0.0.1")
    if host not in ("localhost","127.0.0.1","::1") and not os.environ.get("KAIROS_WEB_PASSWORD"):
        raise RuntimeError("Set KAIROS_WEB_PASSWORD before exposing this workspace remotely.")
    uvicorn.run(create_app(),host=host,port=int(os.environ.get("PORT","8000")))


if __name__ == "__main__":
    main()
