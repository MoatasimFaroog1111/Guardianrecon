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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .state import state, ApprovalStatus
from ..engine.models import ReconciliationItem, ReconCategory
from ..engine.reconciler import ReconciliationEngine

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
# Helpers — تحويل ReconciliationItem إلى JSON قابل للعرض
# ============================================================
def serialize_item(item: ReconciliationItem) -> dict:
    approval = state.approvals.get(item.id)
    ref_txn = item.bank_txn or item.gl_txn
    return {
        "id": item.id,
        "category": item.category.value,
        "date": str(ref_txn.txn_date) if ref_txn else None,
        "description": (
            (item.bank_txn.description_en if item.bank_txn else None)
            or (item.gl_txn.description if item.gl_txn else "")
        ),
        "party_type": item.bank_txn.party_type.value if item.bank_txn and item.bank_txn.party_type else None,
        "amount": ref_txn.amount if ref_txn else 0,
        "difference": item.difference,
        "status": item.status.value,
        "age_days": item.age_days,
        "match_confidence": item.match_confidence,
        "note": item.note,
        "approval_status": approval.status.value if approval else "unknown",
        "decided_by": approval.decided_by if approval else None,
        "decided_at": approval.decided_at.isoformat() if approval and approval.decided_at else None,
        "posted_to_odoo": approval.posted_to_odoo if approval else False,
    }


# ============================================================
# Routes — تشغيل تسوية جديدة (تجريبي، لحد ما نربط Odoo فعلياً)
# ============================================================
@app.post("/api/run-demo")
async def run_demo_reconciliation():
    """يشغّل تسوية بنفس بيانات الديمو — نقطة بداية سريعة لاختبار اللوحة."""
    from ..demo import build_sample_data

    bank_txns, gl_txns = build_sample_data()
    engine = ReconciliationEngine(bank_txns, gl_txns, as_of=date(2026, 6, 30))
    engine.run()
    state.load_from_engine(engine)

    await manager.broadcast({"type": "refresh", "stats": state.stats()})
    return {"ok": True, "stats": state.stats()}


@app.get("/api/stats")
async def get_stats():
    return state.stats()


@app.get("/api/items")
async def get_items(category: Optional[str] = None, approval_status: Optional[str] = None):
    items = list(state.items.values())

    if category:
        items = [i for i in items if i.category.value == category]
    if approval_status:
        items = [
            i for i in items
            if state.approvals.get(i.id) and state.approvals[i.id].status.value == approval_status
        ]

    # الأخطر أولاً: تصعيد ثم الأعلى مبلغاً
    items.sort(key=lambda i: (
        0 if (abs(i.difference) > 10000 or i.status.value in ("Overdue", "Stale")) else 1,
        -abs(i.difference)
    ))

    return [serialize_item(i) for i in items]


@app.get("/api/activity")
async def get_activity():
    return state.activity_log[:50]


@app.post("/api/decide")
async def decide(req: DecisionRequest):
    try:
        record = state.decide(req.item_id, req.approve, req.decided_by, req.comment)
    except KeyError:
        raise HTTPException(status_code=404, detail="العنصر غير موجود")

    await manager.broadcast({
        "type": "decision",
        "item_id": req.item_id,
        "status": record.status.value,
        "stats": state.stats(),
    })
    return {"ok": True, "status": record.status.value}


@app.post("/api/bulk-decide")
async def bulk_decide(req: BulkDecisionRequest):
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
async def dashboard_page():
    html_path = os.path.join(STATIC_DIR, "dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
