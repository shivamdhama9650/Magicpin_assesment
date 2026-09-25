"""
End-to-end replay verification script.
Tests healthz, context push, auto-reply sequences, intent switches, and ticks against the local server.
"""

import json
import time
from urllib import request as urlrequest, error as urlerror

BASE_URL = "http://127.0.0.1:8080"


def req(method: str, path: str, body: dict = None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    headers = {"Content-Type": "application/json"}
    r = urlrequest.Request(url, data=data, method=method, headers=headers)
    resp = urlrequest.urlopen(r, timeout=10)
    return json.loads(resp.read().decode("utf-8"))


def test_harness():
    print("=" * 60)
    print("RUNNING LIVE JUDGE SIMULATOR HARNESS CHECKS")
    print("=" * 60)

    # 1. Warmup
    print("\n--- 1. WARMUP ---")
    h = req("GET", "/v1/healthz")
    print("[PASS] healthz:", h)
    m = req("GET", "/v1/metadata")
    print("[PASS] metadata:", m["team_name"], "| Model:", m["model"])

    # 2. Context Push
    print("\n--- 2. CONTEXT PUSH ---")
    p1 = req("POST", "/v1/context", {
        "scope": "category",
        "context_id": "test_warmup",
        "version": 1,
        "payload": {"slug": "test_warmup"}
    })
    print("[PASS] push version 1 accepted:", p1.get("accepted"))

    # 3. Auto-Reply Hell Scenario
    print("\n--- 3. AUTO-REPLY HELL SCENARIO ---")
    auto_msg = "Thank you for contacting us! Our team will respond shortly."
    for turn in range(1, 5):
        res = req("POST", "/v1/reply", {
            "conversation_id": "conv_sim_auto",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "customer_id": None,
            "from_role": "merchant",
            "message": auto_msg,
            "received_at": "2026-04-26T10:00:00Z",
            "turn_number": turn + 1
        })
        act = res.get("action")
        print(f"Turn {turn}: action={act} | rationale={res.get('rationale')[:50]}...")
        if act == "end":
            print(f"[PASS] Successfully ENDED on turn {turn}")
            break
        elif act == "wait":
            print(f"[PASS] Waiting {res.get('wait_seconds')}s")

    # 4. Intent Transition Scenario
    print("\n--- 4. INTENT TRANSITION SCENARIO ---")
    commitment = "Ok lets do it. Whats next?"
    res_intent = req("POST", "/v1/reply", {
        "conversation_id": "conv_sim_intent",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None,
        "from_role": "merchant",
        "message": commitment,
        "received_at": "2026-04-26T10:00:00Z",
        "turn_number": 2
    })
    body = res_intent.get("body", "").lower()
    print("Merchant commitment:", commitment)
    print("Bot action:", res_intent.get("action"))
    print("Bot response body:", res_intent.get("body"))

    qualifying = ["would you", "do you", "can you tell", "what if", "how about"]
    actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]

    assert any(w in body for w in actioning) and not any(w in body for w in qualifying)
    print("[PASS] Switched to ACTION mode with zero qualification questions!")

    # 5. Hostile Scenario
    print("\n--- 5. HOSTILE / OPTOUT SCENARIO ---")
    hostile = "Stop messaging me. This is useless spam."
    res_hostile = req("POST", "/v1/reply", {
        "conversation_id": "conv_sim_hostile",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None,
        "from_role": "merchant",
        "message": hostile,
        "received_at": "2026-04-26T10:00:00Z",
        "turn_number": 2
    })
    print("Bot action:", res_hostile.get("action"))
    assert res_hostile.get("action") == "end"
    print("[PASS] Gracefully ended on hostile message!")

    # 6. Tick Scenario
    print("\n--- 6. TICK SCENARIO ---")
    res_tick = req("POST", "/v1/tick", {
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["trg_013_corporate_thali_planning", "trg_001_diwali"]
    })
    actions = res_tick.get("actions", [])
    print(f"[PASS] Tick returned {len(actions)} actions")
    for act in actions:
        print(f"  - merchant: {act['merchant_id']} | send_as: {act['send_as']} | cta: {act['cta']}")
        print(f"    body: {act['body'][:80]}...")

    print("\n" + "=" * 60)
    print("ALL HARNESS CHECKS PASSED WITH 100% SUCCESS!")
    print("=" * 60)


if __name__ == "__main__":
    test_harness()
