"""
HTTP service and message composition handler for the Vera challenge.
Implements the 5 required endpoints and the standalone compose function.
"""

from __future__ import annotations
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field

from context_store import ContextStore
from policy import PolicyEngine
from trigger_selector import TriggerSelector
from composer import Composer
from validator import OutputValidator
from conversation_manager import ConversationManager

app = FastAPI(
    title="Vera Assistant Service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.time()
        METRICS["total_requests"] += 1
        try:
            response = await call_next(request)
            duration_ms = (time.time() - t0) * 1000
            if len(METRICS["latencies_ms"]) > 1000:
                METRICS["latencies_ms"].pop(0)
            METRICS["latencies_ms"].append(duration_ms)
            response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"
            return response
        except Exception as exc:
            duration_ms = (time.time() - t0) * 1000
            return JSONResponse(
                status_code=500,
                content={"accepted": False, "error": "internal_server_error", "details": str(exc)},
                headers={"X-Response-Time-Ms": f"{duration_ms:.2f}"},
            )


app.add_middleware(RequestLoggingMiddleware)

START_TIME = time.time()
store = ContextStore()
policy = PolicyEngine()
selector = TriggerSelector(policy=policy)
composer = Composer()
validator = OutputValidator()
conversation_mgr = ConversationManager()

used_suppression_keys: set[str] = set()

# Telemetry counters
METRICS = {
    "total_requests": 0,
    "total_actions": 0,
    "total_suppressions": 0,
    "latencies_ms": [],
}

# Preload dataset if directory exists
for default_dir in ["expanded", "dataset"]:
    if os.path.isdir(default_dir):
        store.load_from_directory(default_dir)
        break


def compose(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Offline composition function called directly by evaluators."""
    return composer.compose(category, merchant, trigger, customer)


from fastapi.responses import HTMLResponse
from pathlib import Path

DASHBOARD_FILE = Path(__file__).parent / "dashboard.html"


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serves the interactive Vera Mission Control dashboard."""
    if DASHBOARD_FILE.exists():
        return HTMLResponse(content=DASHBOARD_FILE.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Vera Assistant Live</h1><p><a href='/v1/healthz'>/v1/healthz</a></p>")


# Endpoint 1: Healthcheck
@app.get("/v1/healthz")
async def healthz():
    uptime = int(time.time() - START_TIME)
    counts = store.counts_by_scope()
    return {
        "status": "ok",
        "uptime_seconds": uptime,
        "contexts_loaded": counts,
    }


# Endpoint 2: Service Metadata
@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Shiva",
        "team_members": ["Shiva"],
        "model": "rule-engine-v1",
        "approach": "Deterministic category rules and state machine for whatsapp engagement",
        "contact_email": "shiva@example.com",
        "version": "1.0.0",
        "submitted_at": "2026-04-26T08:00:00Z",
    }


# Endpoint 3: Context Ingestion
class ContextPushBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None


@app.post("/v1/context")
async def push_context(body: ContextPushBody):
    accepted, res, status_code = store.push(
        scope=body.scope,
        context_id=body.context_id,
        version=body.version,
        payload=body.payload,
        delivered_at=body.delivered_at,
    )
    return JSONResponse(status_code=status_code, content=res)


# Endpoint 4: Proactive Tick
class TickBody(BaseModel):
    now: str
    available_triggers: List[str] = Field(default_factory=list)


@app.post("/v1/tick")
async def tick(body: TickBody):
    selected_items = selector.select_triggers_for_tick(
        store=store,
        available_trigger_ids=body.available_triggers,
        simulated_now=body.now,
        used_suppression_keys=used_suppression_keys,
        opted_out_merchants=conversation_mgr.opted_out_merchants,
        active_conversations=conversation_mgr.conversations,
        max_actions=20,
    )

    actions = []
    for item in selected_items:
        trigger = item["trigger"]
        merchant = item["merchant"]
        category = item["category"]
        customer = item["customer"]
        merchant_id = merchant["merchant_id"]
        customer_id = customer.get("customer_id") if customer else None
        trigger_id = trigger.get("id")

        composed = composer.compose(category, merchant, trigger, customer)
        conv_id = f"conv_{merchant_id}_{trigger_id}_{int(time.time() * 1000) % 100000}"

        supp_key = composed.get("suppression_key") or trigger.get("suppression_key")
        if supp_key:
            used_suppression_keys.add(supp_key)

        conv_state = conversation_mgr.get_or_create(conv_id, merchant_id, customer_id)
        conv_state.last_bot_body = composed.get("body")
        conv_state.last_action = "send"
        conv_state.turns.append({"from": "bot", "msg": composed.get("body"), "turn": 1})

        actions.append({
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": composed.get("send_as", "vera"),
            "trigger_id": trigger_id,
            "template_name": composed.get("template_name", f"vera_{trigger.get('kind', 'generic')}_v1"),
            "template_params": composed.get("template_params", [merchant.get("identity", {}).get("name", "")]),
            "body": composed.get("body", ""),
            "cta": composed.get("cta", "binary_yes_no"),
            "suppression_key": supp_key,
            "rationale": composed.get("rationale", ""),
        })

    METRICS["total_actions"] += len(actions)
    METRICS["total_suppressions"] += max(0, len(body.available_triggers) - len(actions))
    return {"actions": actions}


# Endpoint 5: Conversation Reply
class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str = "merchant"
    message: str
    received_at: Optional[str] = None
    turn_number: int = 2


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    return conversation_mgr.handle_reply(
        conversation_id=body.conversation_id,
        merchant_id=body.merchant_id,
        customer_id=body.customer_id,
        from_role=body.from_role,
        message=body.message,
        turn_number=body.turn_number,
    )


# Telemetry and Operational Inspection
@app.get("/v1/metrics")
async def get_metrics():
    latencies = METRICS["latencies_ms"]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

    return {
        "status": "healthy",
        "uptime_seconds": int(time.time() - START_TIME),
        "telemetry": {
            "total_requests": METRICS["total_requests"],
            "total_actions_dispatched": METRICS["total_actions"],
            "total_suppressed_opportunities": METRICS["total_suppressions"],
            "active_conversations_count": len(conversation_mgr.conversations),
            "opted_out_merchants_count": len(conversation_mgr.opted_out_merchants),
            "avg_latency_ms": round(avg_latency, 2),
            "p95_latency_ms": round(p95_latency, 2),
        },
        "context_inventory": store.counts_by_scope(),
    }


# Explainability / Diagnostic Audit Endpoint
@app.get("/v1/explain")
async def explain(merchant_id: str, trigger_id: str, simulated_now: Optional[str] = None):
    now_str = simulated_now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    merchant = store.get_merchant(merchant_id)
    trigger = store.get_trigger(trigger_id)

    if not merchant:
        return {"eligible": False, "reason": f"Merchant {merchant_id} not found in store"}
    if not trigger:
        return {"eligible": False, "reason": f"Trigger {trigger_id} not found in store"}

    category_slug = merchant.get("category_slug")
    category = store.get_category(category_slug) if category_slug else {}

    # Check suppression key
    candidate_key = trigger.get("suppression_key") or f"{trigger.get('kind')}:{merchant_id}"
    is_suppressed = candidate_key in used_suppression_keys

    active_count = sum(1 for c in conversation_mgr.conversations.values() if getattr(c, "merchant_id", None) == merchant_id and getattr(c, "state", "") != "ended")
    passed, rejection_reason = policy.check_eligibility(
        trigger=trigger,
        merchant=merchant,
        category=category,
        customer=None,
        simulated_now=now_str,
        used_suppression_keys=used_suppression_keys,
        opted_out_merchants=conversation_mgr.opted_out_merchants,
        active_conversations_for_merchant=active_count,
    )

    return {
        "merchant_id": merchant_id,
        "trigger_id": trigger_id,
        "category_id": category_slug,
        "eligible": passed,
        "rejection_reason": rejection_reason,
        "suppression_key": candidate_key,
        "already_suppressed": is_suppressed,
        "urgency_score": trigger.get("urgency", 0.5),
    }


# Optional teardown endpoint
@app.post("/v1/teardown")
async def teardown():
    store.clear()
    used_suppression_keys.clear()
    conversation_mgr.conversations.clear()
    conversation_mgr.opted_out_merchants.clear()
    METRICS["total_requests"] = 0
    METRICS["total_actions"] = 0
    METRICS["total_suppressions"] = 0
    METRICS["latencies_ms"].clear()
    return {"status": "ok", "message": "State wiped"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("bot:app", host=host, port=port, reload=False)
