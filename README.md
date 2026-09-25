# magicpin Assessment — Vera Merchant Assistant

## 1. Architecture & Design

This service implements the 4-context WhatsApp assistant for local merchants across 5 verticals (dentists, salons, restaurants, gyms, pharmacies). It uses deterministic policy checks before composing, handles multi-turn conversation states, and validates all outgoing messages against category rules and verifiable facts.

```
Incoming Request (/v1/context) ──► ContextStore (versioned dictionary)
                                         │
Incoming Tick (/v1/tick) ───────► PolicyEngine (eligibility & consent gates)
                                         │
                                   TriggerSelector (urgency & signal ranking)
                                         │
                                   Composer (category-calibrated templates)
                                         │
                                   OutputValidator (URL & taboo checks)
                                         │
                                   Actions returned + ConversationState updated
```

### Components:
- **`context_store.py`**: Thread-safe in-memory store keyed by `(scope, context_id)`. Re-posts with identical or lower versions return `409 Conflict (stale_version)`. Higher versions replace prior payloads atomically.
- **`policy.py`**: Pre-composition checks. Verifies trigger expiry against simulated clock (`now`), validates merchant existence, checks customer consent scopes (`recall_reminders`, `appointment_reminders`, `promotional_offers`), checks suppression keys, and prevents duplicate outreach on active threads.
- **`trigger_selector.py`**: Ranks candidate triggers by urgency (1–5), merchant signals (`ctr_below_peer_median`, `high_risk_adult_cohort`, etc.), and active offers. Limits outreach to one priority action per merchant per tick (max 20 actions per tick).
- **`composer.py`**: Category-calibrated message composition. Formats numbers, dates, prices, and source citations (`JIDA Oct 2026 p.14`, `DCI circular`) directly from input contexts. Honors Hindi-English code-mixing when requested.
- **`validator.py`**: Post-composition validation. Verifies required fields, correct `send_as`, suppression key match, category taboo words, and strictly strips URLs to avoid WhatsApp delivery rejection.
- **`conversation_manager.py` / `conversation_handlers.py`**: Multi-turn state machine:
  - **Auto-replies**: Detects canned phrases and repeated messages. Waits on turns 1–2, and exits cleanly (`action: end`) on turn 3+.
  - **Intent commitments**: When a merchant says *"ok let's do it"* or *"whats next"*, switches immediately to action execution with drafted copy, skipping redundant qualification questions.
  - **Opt-outs**: Gracefully exits (`action: end`) on *"stop"* or *"not interested"* and flags the merchant for suppression.

---

## 2. API Endpoints

- `GET /v1/healthz`: Liveness probe returning uptime and loaded context counts.
- `GET /v1/metadata`: Service metadata and engine description.
- `POST /v1/context`: Ingests category, merchant, customer, and trigger contexts with versioning checks.
- `POST /v1/tick`: Evaluates active triggers and returns proactive actions.
- `POST /v1/reply`: Handles incoming customer and merchant replies.
- `POST /v1/teardown`: State reset endpoint.
- `compose()`: Standalone Python function in `bot.py` for direct evaluation.

---

## 3. Test & Benchmark Results

Verified against the full dataset (5 categories, 50 merchants, 200 customers, 100 triggers) and 30 canonical test pairs (`test_pairs.json`):

| Check / Test | Expected Behavior | Result |
|---|---|---|
| Health & Metadata | Correct schemas and counts | PASS |
| Context Versioning | 409 on equal/lower version, atomic replace on bump | PASS |
| Auto-Reply Detection | Wait on Turn 1 & 2; Graceful `end` on Turn 3 | PASS |
| Intent Transitions | Switches to action mode without qualifying questions | PASS |
| Hostile / Opt-out | Immediate `action: end` and merchant suppression | PASS |
| 30-Pair Benchmark | All 30 test pairs composed, validated, 0 URLs, 0 taboos | PASS |
| Response Latency | Average response time < 5ms | PASS |

---

## 4. Local Execution

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn bot:app --host 0.0.0.0 --port 8080

# Run unit tests
python test_bot.py

# Run replay harness tests
python run_harness.py

# Generate submission.jsonl
python generate_submission.py
```
