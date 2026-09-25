#!/usr/bin/env python3
"""
CLI utility for testing, inspecting contexts, and running offline benchmarks.
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from context_store import ContextStore
from bot import compose


def main():
    parser = argparse.ArgumentParser(description="Vera Assistant CLI Tool")
    subparsers = parser.add_subparsers(dest="command")

    # Command: compose
    comp_parser = subparsers.add_parser("compose", help="Compose outbound message for given merchant and trigger")
    comp_parser.add_argument("--merchant", "-m", required=True, help="Merchant ID")
    comp_parser.add_argument("--trigger", "-t", required=True, help="Trigger ID")
    comp_parser.add_argument("--customer", "-c", default=None, help="Customer ID (optional)")

    # Command: stats
    subparsers.add_parser("stats", help="Show counts of loaded contexts")

    # Command: run-tests
    subparsers.add_parser("test", help="Run the unit test suite")

    args = parser.parse_args()

    store = ContextStore()
    dataset_dir = Path("expanded") if Path("expanded").exists() else Path("dataset")
    store.load_from_directory(str(dataset_dir))

    if args.command == "stats":
        counts = store.counts_by_scope()
        print(f"Loaded from '{dataset_dir}':")
        for scope, count in counts.items():
            print(f"  - {scope:10}: {count}")

    elif args.command == "compose":
        trigger = store.get_trigger(args.trigger)
        if not trigger:
            print(f"Error: Trigger '{args.trigger}' not found.")
            sys.exit(1)

        merchant = store.get_merchant(args.merchant)
        if not merchant:
            print(f"Error: Merchant '{args.merchant}' not found.")
            sys.exit(1)

        cat_slug = merchant.get("category_slug")
        category = store.get_category(cat_slug)
        if not category:
            print(f"Error: Category '{cat_slug}' not found.")
            sys.exit(1)

        customer = store.get_customer(args.customer) if args.customer else None

        result = compose(category, merchant, trigger, customer)
        print("\n" + "=" * 60)
        print(f"COMPOSED OUTBOUND MESSAGE ({result['send_as']})")
        print("=" * 60)
        print(f"Body:\n{result['body']}\n")
        print(f"CTA:             {result['cta']}")
        print(f"Suppression Key: {result['suppression_key']}")
        print(f"Rationale:       {result['rationale']}")
        print("=" * 60)

    elif args.command == "test":
        import subprocess
        subprocess.run([sys.executable, "test_bot.py"])

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
