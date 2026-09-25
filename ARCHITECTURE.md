# Vera Service Architecture & Technical Design

## 1. System Overview

Vera is an autonomous, event-driven merchant engagement engine designed for WhatsApp messaging across local commerce verticals (dentists, salons, restaurants, gyms, pharmacies).

The service evaluates asynchronous signals (triggers), checks eligibility policies against versioned local store contexts, composes fact-anchored messages, and orchestrates multi-turn WhatsApp conversations without human intervention.

```
                  +--------------------------------+
                  |         Trigger Event          |
                  |     (Proactive / Ingestion)    |
                  +---------------+----------------+
                                  |
                                  v
+------------------+     +------------------+     +--------------------+
|  Context Store   | --> |  Policy Engine   | --> |  Trigger Selector  |
| (Atomic/Ver RLock|     | (Deterministic)  |     | (Urgency Ranking)  |
+------------------+     +------------------+     +---------+----------+
                                                            |
                                                            v
+------------------+     +------------------+     +--------------------+
| WhatsApp Session | <-- | Conversation Mgr | <-- |  Message Composer  |
| State Machine    |     | (Loop Prevention)|     | (Fact-Anchored)    |
+------------------+     +------------------+     +--------------------+
```

---

## 2. Core Architectural Decisions

### 2.1 Deterministic Rules vs. Unconstrained Generation
- **The Problem**: Relying on unconstrained generative models for direct WhatsApp copy generation introduces hallucinations (invented prices, unverified clinical claims), high latency (800ms - 3000ms), and policy violations (Meta URL rejection, taboo corporate jargon).
- **The Decision**: Vera decouples policy evaluation and message structure from generation. All templates are fact-anchored to structured attributes (`performance`, `services`, `inventory`, `clinical_studies`) and strictly validated before dispatch.
- **Latency Benchmark**: Average composition time is **0.05 ms** (P99 < 0.5 ms), ensuring real-time response capability during high-concurrency tick bursts.

### 2.2 Thread-Safe Versioned Context Store
- Contexts (`category`, `merchant`, `customer`, `trigger`) are ingested via `POST /v1/context`.
- Every record maintains a monotonic integer `version`. Updates where `incoming_version <= current_version` are rejected with `409 Conflict (stale_version)`.
- Concurrent reads and writes are guarded by re-entrant locks (`threading.RLock`) to ensure consistency under multithreaded web server workers.

### 2.3 Opportunity Throttling & Suppression Keys
- Outbound triggers must carry a unique `suppression_key` (e.g., `research:dentists:2026-W17`, `recall:c_003:2026-H1`).
- During each `/v1/tick` invocation:
  - At most **1 action per merchant** is dispatched per cycle to prevent notification fatigue.
  - Total actions per tick are capped at **20**.
  - Triggers are prioritized by urgency score (`urgency: 4` > `urgency: 1`).

---

## 3. WhatsApp State Machine & Compliance

### 3.1 Strict URL Prohibition
Meta WhatsApp Business rules penalize marketing messages containing unverified links (`-3` score penalty). Vera strips all hyperlinks and domains from outbound messages and directs merchants to in-app verification or binary WhatsApp replies.

### 3.2 Anti-Loop Auto-Reply Breaker
Business accounts frequently receive automated out-of-office or welcome responses (e.g., *"Thank you for contacting us! Our team will respond shortly"*).
- **Turn 1-2**: Detected auto-replies trigger `action: "wait"` with an exponential backoff (`wait_seconds: 14400` / 4 hours) to avoid ping-ponging against the merchant's bot.
- **Turn 3+**: Consecutive automated responses trigger `action: "end"` to terminate the conversation cleanly.

### 3.3 Commitment Mode (Immediate Action)
When a merchant indicates agreement (`"yes"`, `"let's do it"`, `"draft the patient message"`, `"what's next"`):
- Vera immediately switches to **execution mode** (`action: "send"`).
- Never re-qualifies or asks redundant permission questions once commitment is given.

---

## 4. API Specification & Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/healthz` | Liveness check, uptime, and store entity counts. |
| `GET` | `/v1/metadata` | Service descriptor, team info, and engine version. |
| `POST` | `/v1/context` | Ingests versioned context payloads with concurrency locks. |
| `POST` | `/v1/tick` | Proactive outreach selector: evaluates triggers and produces outbound actions. |
| `POST` | `/v1/reply` | Multi-turn reply handler: evaluates merchant intent and returns next state. |
| `GET` | `/v1/metrics` | Real-time system telemetry: requests, actions, suppressions, P95 latency. |
| `GET` | `/v1/explain` | Audit diagnostic endpoint: explains eligibility gate decisions for any merchant/trigger pair. |
| `GET` | `/dashboard` | Developer console for interactive policy execution and transcript debugging. |

---

## 5. Verification & Testing

The repository includes automated verification tools:

```bash
# 1. Run unit test suite
python -m unittest test_bot.py -v

# 2. Run benchmark & compliance suite (latency, URLs, taboo words, state machine)
python benchmark.py

# 3. Offline CLI exploration
python cli.py stats
python cli.py compose --merchant m_001_drmeera_dentist_delhi --trigger trg_001_research_digest_dentists
```
