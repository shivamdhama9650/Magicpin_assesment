"""
Unit tests for API endpoints, versioning, auto-reply handling, and intent routing.
"""

import json
from fastapi.testclient import TestClient
from bot import app, compose

client = TestClient(app)


def test_healthz():
    resp = client.get("/v1/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "contexts_loaded" in data
    print("[PASS] GET /v1/healthz passed:", data)


def test_metadata():
    resp = client.get("/v1/metadata")
    assert resp.status_code == 200
    data = resp.json()
    assert "team_name" in data
    assert "model" in data
    print("[PASS] GET /v1/metadata passed:", data["team_name"])


def test_context_push_and_versioning():
    # Push version 1
    resp1 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "test_cat",
        "version": 1,
        "payload": {"slug": "test_cat", "display_name": "Test"}
    })
    assert resp1.status_code == 200
    assert resp1.json()["accepted"] is True

    # Push version 1 again -> 409 stale_version
    resp2 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "test_cat",
        "version": 1,
        "payload": {"slug": "test_cat", "display_name": "Test"}
    })
    assert resp2.status_code == 409
    assert resp2.json()["accepted"] is False
    assert resp2.json()["reason"] == "stale_version"

    # Push version 2 -> replaces atomically 200
    resp3 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "test_cat",
        "version": 2,
        "payload": {"slug": "test_cat", "display_name": "Test Updated"}
    })
    assert resp3.status_code == 200
    assert resp3.json()["accepted"] is True
    print("[PASS] POST /v1/context idempotency and version bump passed")


def test_tick_and_triggers():
    # Push sample merchant, category, and trigger
    client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": {"slug": "dentists", "voice": {"tone": "peer_clinical"}}
    })
    client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_test_dentist",
        "version": 1,
        "payload": {
            "merchant_id": "m_test_dentist",
            "category_slug": "dentists",
            "identity": {"name": "Dr. Meera Clinic", "owner_first_name": "Meera", "locality": "Lajpat Nagar", "city": "Delhi"},
            "performance": {"views": 2400, "calls": 20, "ctr": 0.025, "delta_7d": {"calls_pct": -0.40}},
            "offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}]
        }
    })
    client.post("/v1/context", json={
        "scope": "trigger",
        "context_id": "trg_test_perf_dip",
        "version": 1,
        "payload": {
            "id": "trg_test_perf_dip",
            "scope": "merchant",
            "kind": "perf_dip",
            "merchant_id": "m_test_dentist",
            "urgency": 3,
            "suppression_key": "perf_dip:m_test_dentist:W17",
            "expires_at": "2026-12-31T00:00:00Z"
        }
    })

    # Call /v1/tick
    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["trg_test_perf_dip"]
    })
    assert resp.status_code == 200
    actions = resp.json()["actions"]
    assert len(actions) == 1
    act = actions[0]
    assert act["merchant_id"] == "m_test_dentist"
    assert "40%" in act["body"]
    assert act["send_as"] == "vera"
    assert act["cta"] == "binary_yes_no"
    print("[PASS] POST /v1/tick passed with action:", act["body"][:60], "...")


def test_auto_reply_hell():
    # Turn 1
    r1 = client.post("/v1/reply", json={
        "conversation_id": "conv_auto_test",
        "merchant_id": "m_test_dentist",
        "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond shortly.",
        "turn_number": 2
    })
    assert r1.status_code == 200
    assert r1.json()["action"] in ("send", "wait")

    # Turn 2
    r2 = client.post("/v1/reply", json={
        "conversation_id": "conv_auto_test",
        "merchant_id": "m_test_dentist",
        "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond shortly.",
        "turn_number": 3
    })
    assert r2.status_code == 200
    assert r2.json()["action"] == "wait"
    assert r2.json()["wait_seconds"] == 86400

    # Turn 3
    r3 = client.post("/v1/reply", json={
        "conversation_id": "conv_auto_test",
        "merchant_id": "m_test_dentist",
        "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond shortly.",
        "turn_number": 4
    })
    assert r3.status_code == 200
    assert r3.json()["action"] == "end"
    print("[PASS] Auto-reply handling passed")


def test_intent_transition():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_intent_test",
        "merchant_id": "m_test_dentist",
        "from_role": "merchant",
        "message": "Ok lets do it. Whats next?",
        "turn_number": 2
    })
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "send"
    body_lower = data["body"].lower()

    actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
    qualifying = ["would you", "do you", "can you tell", "what if", "how about"]

    assert any(w in body_lower for w in actioning), f"Missing action words in: {body_lower}"
    assert not any(w in body_lower for w in qualifying), f"Unexpected qualifying words in: {body_lower}"
    print("[PASS] Intent transition correctly switched to ACTION mode")


def test_hostile_exit():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_hostile_test",
        "merchant_id": "m_test_dentist",
        "from_role": "merchant",
        "message": "Stop messaging me. This is useless spam.",
        "turn_number": 2
    })
    assert r.status_code == 200
    assert r.json()["action"] == "end"
    print("[PASS] Hostile opt-out exit passed")


if __name__ == "__main__":
    test_healthz()
    test_metadata()
    test_context_push_and_versioning()
    test_tick_and_triggers()
    test_auto_reply_hell()
    test_intent_transition()
    test_hostile_exit()
    print("\nALL UNIT TESTS PASSED SUCCESSFULLY!")

