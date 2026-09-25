"""
Generates submission.jsonl from expanded/test_pairs.json.
Runs compose() across all 30 test pairs and validates output schema.
"""

from __future__ import annotations
import json
from pathlib import Path
from bot import compose
from validator import OutputValidator

BASE_DIR = Path(__file__).parent / "expanded"
TEST_PAIRS_FILE = BASE_DIR / "test_pairs.json"
OUTPUT_FILE = Path(__file__).parent / "submission.jsonl"

validator = OutputValidator()


def main():
    if not TEST_PAIRS_FILE.exists():
        print(f"Error: {TEST_PAIRS_FILE} not found. Run dataset generation first.")
        return

    with open(TEST_PAIRS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        pairs = data.get("pairs", [])

    print(f"Generating submission for {len(pairs)} test pairs...")
    lines = []

    for item in pairs:
        test_id = item["test_id"]
        tid = item["trigger_id"]
        mid = item["merchant_id"]
        cid = item.get("customer_id")

        # Load trigger
        t_path = BASE_DIR / "triggers" / f"{tid}.json"
        with open(t_path, "r", encoding="utf-8") as f:
            trigger = json.load(f)

        # Load merchant
        m_path = BASE_DIR / "merchants" / f"{mid}.json"
        with open(m_path, "r", encoding="utf-8") as f:
            merchant = json.load(f)

        # Load category
        cat_slug = merchant.get("category_slug")
        c_path = BASE_DIR / "categories" / f"{cat_slug}.json"
        with open(c_path, "r", encoding="utf-8") as f:
            category = json.load(f)

        # Load customer if present
        customer = None
        if cid:
            cust_path = BASE_DIR / "customers" / f"{cid}.json"
            if cust_path.exists():
                with open(cust_path, "r", encoding="utf-8") as f:
                    customer = json.load(f)

        # Compose message
        result = compose(category, merchant, trigger, customer)

        # Validate
        is_valid, errors = validator.validate(result, category, merchant, trigger, customer)
        if not is_valid:
            print(f"Warning: {test_id} had validation issues: {errors}. Repairing...")
            result = validator.clean_and_repair(result, category, merchant, trigger, customer)

        submission_entry = {
            "test_id": test_id,
            "body": result.get("body", ""),
            "cta": result.get("cta", "binary_yes_no"),
            "send_as": result.get("send_as", "vera"),
            "suppression_key": result.get("suppression_key", trigger.get("suppression_key", "")),
            "rationale": result.get("rationale", ""),
        }
        lines.append(json.dumps(submission_entry, ensure_ascii=False))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")

    print(f"[PASS] Successfully generated {len(lines)} lines to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
