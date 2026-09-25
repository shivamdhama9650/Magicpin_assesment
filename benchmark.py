"""
Performance and Compliance Benchmark Suite for Vera Assistant.
Runs offline evaluation against test pairs and verifies:
- P50, P95, and P99 latency
- Zero URL occurrences (Meta rejection prevention)
- Zero taboo vocabulary occurrences
- Anti-loop auto-reply detection
- Immediate action mode on commitments
"""

import time
import json
import re
from pathlib import Path
from context_store import ContextStore
from composer import Composer
from conversation_manager import ConversationManager
from validator import OutputValidator

TABOO_WORDS = [
    "delighted", "thrilled", "dive deep", "game-changer",
    "synergy", "paradigm", "testament", "revolutionize"
]

URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def run_benchmark():
    print("=" * 65)
    print(" VERA SYSTEM BENCHMARK & COMPLIANCE EVALUATION")
    print("=" * 65)

    store = ContextStore()
    dataset_dir = "expanded" if Path("expanded").exists() else "dataset"
    store.load_from_directory(dataset_dir)
    composer = Composer()
    validator = OutputValidator()
    conv_mgr = ConversationManager()

    # 1. Test Pairs Benchmark
    test_pairs_path = Path(dataset_dir) / "test_pairs.json"
    if not test_pairs_path.exists():
        print(f"[!] {test_pairs_path} not found. Skipping test pairs.")
        return

    with open(test_pairs_path, encoding="utf-8") as f:
        data = json.load(f)
        pairs = data.get("pairs", data) if isinstance(data, dict) else data

    latencies = []
    taboo_violations = 0
    url_violations = 0
    schema_failures = 0
    total_pairs = len(pairs)

    print(f"\n[*] Evaluating {total_pairs} canonical test pairs from {dataset_dir}...")

    for pair in pairs:
        merchant = store.get_merchant(pair.get("merchant_id", "")) or {}
        category_slug = merchant.get("category_slug", "dentists")
        category = store.get_category(category_slug) or {}
        trigger = store.get_trigger(pair.get("trigger_id", "")) or {}
        customer = store.get_customer(pair.get("customer_id", "")) if pair.get("customer_id") else None

        t0 = time.perf_counter()
        result = composer.compose(category, merchant, trigger, customer)
        latencies.append((time.perf_counter() - t0) * 1000)

        # Validate
        valid, _ = validator.validate(result, category, merchant, trigger, customer)
        if not valid:
            schema_failures += 1

        body = result.get("body", "")
        # URL check
        if URL_PATTERN.search(body):
            url_violations += 1

        # Taboo check
        lower_body = body.lower()
        if any(w in lower_body for w in TABOO_WORDS):
            taboo_violations += 1

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]

    # 2. State Machine Heuristics
    print("[*] Evaluating multi-turn state machine behavior...")

    # Test Auto-reply turn 1 -> wait (14400)
    r1 = conv_mgr.handle_reply(
        conversation_id="bench_auto_1",
        merchant_id="m_001_drmeera_dentist_delhi",
        customer_id=None,
        from_role="merchant",
        message="Thank you for contacting us! We will get back to you shortly.",
        turn_number=2,
    )
    auto_reply_turn1_pass = (r1.get("action") == "wait" and r1.get("wait_seconds") == 14400)

    # Test Auto-reply turn 2 -> wait (86400)
    r2 = conv_mgr.handle_reply(
        conversation_id="bench_auto_1",
        merchant_id="m_001_drmeera_dentist_delhi",
        customer_id=None,
        from_role="merchant",
        message="Thank you for contacting us! We will get back to you shortly.",
        turn_number=3,
    )
    auto_reply_turn2_pass = (r2.get("action") == "wait" and r2.get("wait_seconds") == 86400)

    # Test Auto-reply turn 3+ -> end
    r3 = conv_mgr.handle_reply(
        conversation_id="bench_auto_1",
        merchant_id="m_001_drmeera_dentist_delhi",
        customer_id=None,
        from_role="merchant",
        message="Thank you for contacting us! We will get back to you shortly.",
        turn_number=4,
    )
    auto_reply_turn3_pass = (r3.get("action") == "end")

    # Test Commitment immediate action mode
    r3 = conv_mgr.handle_reply(
        conversation_id="bench_comm_1",
        merchant_id="m_001_drmeera_dentist_delhi",
        customer_id=None,
        from_role="merchant",
        message="Sounds great, let's proceed with this.",
        turn_number=2,
    )
    commitment_pass = (r3.get("action") == "send" and "?" not in r3.get("body", "")[-50:])

    # Print Summary Table
    print("\n" + "-" * 65)
    print(" BENCHMARK RESULTS SUMMARY")
    print("-" * 65)
    print(f" Total Compositions Evaluated : {total_pairs}")
    print(f" P50 Latency                  : {p50:.3f} ms")
    print(f" P95 Latency                  : {p95:.3f} ms")
    print(f" P99 Latency                  : {p99:.3f} ms")
    print(f" URL Violations (Target 0)    : {url_violations}")
    print(f" Taboo Words (Target 0)       : {taboo_violations}")
    print(f" Schema Conformance           : {100.0 * (total_pairs - schema_failures) / total_pairs:.1f}%")
    print(f" Auto-reply Loop Breaker      : {'PASS' if auto_reply_turn1_pass and auto_reply_turn2_pass and auto_reply_turn3_pass else 'FAIL'}")
    print(f" Commitment Action Mode       : {'PASS' if commitment_pass else 'FAIL'}")
    print("-" * 65)

    all_passed = (
        url_violations == 0
        and taboo_violations == 0
        and schema_failures == 0
        and auto_reply_turn1_pass
        and auto_reply_turn2_pass
        and auto_reply_turn3_pass
        and commitment_pass
    )
    if all_passed:
        print("[SUCCESS] All system benchmarks and compliance checks passed.\n")
    else:
        print("[WARNING] One or more compliance thresholds failed.\n")


if __name__ == "__main__":
    run_benchmark()
