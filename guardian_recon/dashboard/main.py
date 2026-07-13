"""
GuardianRecon Dashboard — FastAPI Backend
==============================================
لوحة مراقبة وموافقات (Human-in-the-loop) فوق محرك التسوية.
المعتصم يراقب فقط ويوافق/يرفض — لا شيء يترحّل لأودو تلقائياً.

تشغيل:
    cd /home/claude
    uvicorn guardian_recon.dashboard.main:app --host 0.0.0.0 --port 8420 --reload
"""

from __future__ import annotations
from datetime import date
from typing import List, Optional
import json
import os

import logging
import secrets

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .state import state, ApprovalStatus
from ..engine.models import ReconciliationItem, ReconCategory
from ..engine.reconciler import ReconciliationEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("guardian_recon.api")

# ============================================================
# حماية بكلمة مرور (HTTP Basic) — بند 1.2 من خارطة الطريق
# تُعرَّف عبر متغيري بيئة: DASHBOARD_USER و DASHBOARD_PASSWORD
# لو ما كانا معرّفين (تطوير محلي)، الحماية تتعطل تلقائياً.
# ============================================================
security = HTTPBasic(auto_error=False)


def verify_auth(credentials: HTTPBasicCredentials = Depends(security)):
    expected_user = os.environ.get("DASHBOARD_USER")
    expected_pass = os.environ.get("DASHBOARD_PASSWORD")

    if not expected_user or not expected_pass:
        return "dev"  # تطوير محلي بدون حماية

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="تسجيل الدخول مطلوب",
            headers={"WWW-Authenticate": "Basic"},
        )

    user_ok = secrets.compare_digest(credentials.username, expected_user)
    pass_ok = secrets.compare_digest(credentials.password, expected_pass)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="بيانات دخول خاطئة",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

app = FastAPI(title="GuardianRecon Dashboard")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ============================================================
# WebSocket Connection Manager — للبث الحي عند أي تغيير
# ============================================================
class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


# ============================================================
# Pydantic Schemas
# ============================================================
class DecisionRequest(BaseModel):
    item_id: str
    approve: bool
    decided_by: str = "معتصم"
    comment: str = ""


class BulkDecisionRequest(BaseModel):
    item_ids: List[str]
    approve: bool
    decided_by: str = "معتصم"


# ============================================================
# Routes — تشغيل تسوية جديدة (تجريبي، لحد ما نربط Odoo فعلياً)
# ============================================================
@app.post("/api/run-demo")
async def run_demo_reconciliation(user: str = Depends(verify_auth)):
    """يشغّل تسوية بنفس بيانات الديمو — نقطة بداية سريعة لاختبار اللوحة."""
    from ..demo import build_sample_data

    bank_txns, gl_txns = build_sample_data()
    engine = ReconciliationEngine(bank_txns, gl_txns, as_of=date(2026, 6, 30))
    engine.run()
    run_id = state.load_from_engine(engine, source="demo")
    logger.info("Demo reconciliation run created: %s", run_id)

    stats = state.stats()
    await manager.broadcast({"type": "refresh", "stats": stats})
    return {"ok": True, "run_id": run_id, "stats": stats}


@app.get("/api/stats")
async def get_stats(user: str = Depends(verify_auth)):
    return state.stats()


@app.get("/api/items")
async def get_items(category: Optional[str] = None, approval_status: Optional[str] = None, user: str = Depends(verify_auth)):
    return state.get_items(category=category, approval_status=approval_status)


@app.get("/api/activity")
async def get_activity(user: str = Depends(verify_auth)):
    return state.get_activity(limit=50)


@app.post("/api/decide")
async def decide(req: DecisionRequest, user: str = Depends(verify_auth)):
    try:
        result = state.decide(req.item_id, req.approve, req.decided_by, req.comment)
    except KeyError:
        raise HTTPException(status_code=404, detail="العنصر غير موجود")

    stats = state.stats()
    await manager.broadcast({
        "type": "decision",
        "item_id": req.item_id,
        "status": result["status"],
        "stats": stats,
    })
    return {"ok": True, "status": result["status"]}


@app.post("/api/bulk-decide")
async def bulk_decide(req: BulkDecisionRequest, user: str = Depends(verify_auth)):
    records = state.bulk_decide(req.item_ids, req.approve, req.decided_by)
    await manager.broadcast({"type": "refresh", "stats": state.stats()})
    return {"ok": True, "count": len(records)}


# ============================================================
# WebSocket — بث حي لأي تغيير في اللوحة
# ============================================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "connected", "stats": state.stats()})
        while True:
            await websocket.receive_text()  # نبقي الاتصال حي فقط
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ============================================================
# Static Dashboard
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def dashboard_page(user: str = Depends(verify_auth)):
    html_path = os.path.join(STATIC_DIR, "dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
