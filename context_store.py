"""
In-memory store for category, merchant, customer, and trigger contexts.
Handles version tracking, deduplication, and atomic updates.
"""

from __future__ import annotations
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


class ContextStore:
    def __init__(self):
        self._lock = threading.RLock()
        # Key: (scope, context_id) -> {"version": int, "payload": dict, "stored_at": str, "delivered_at": str}
        self._store: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def push(
        self,
        scope: str,
        context_id: str,
        version: int,
        payload: Dict[str, Any],
        delivered_at: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], int]:
        """
        Store a context record.
        Returns: (accepted, response_dict, http_status_code)
        
        Rules:
        - Scope must be one of: "category", "merchant", "customer", "trigger"
        - If current_version > version: rejected with 409 stale_version
        - If current_version == version: idempotent no-op, accepted with 200
        - If higher version or new: accepted with 200, replaces old payload atomically
        """
        valid_scopes = {"category", "merchant", "customer", "trigger"}
        if scope not in valid_scopes:
            return (
                False,
                {"accepted": False, "reason": "invalid_scope", "details": f"Scope must be one of {valid_scopes}"},
                400,
            )

        with self._lock:
            key = (scope, context_id)
            current = self._store.get(key)

            if current is not None and current["version"] > version:
                return (
                    False,
                    {
                        "accepted": False,
                        "reason": "stale_version",
                        "current_version": current["version"],
                        "details": f"Stored version {current['version']} is > provided version {version}",
                    },
                    409,
                )

            stored_at = datetime.utcnow().isoformat() + "Z"
            if current is not None and current["version"] == version:
                # Idempotent no-op per challenge testing brief §2.1
                return (
                    True,
                    {
                        "accepted": True,
                        "ack_id": f"ack_{context_id}_v{version}",
                        "stored_at": current.get("stored_at", stored_at),
                        "idempotent": True,
                    },
                    200,
                )
            self._store[key] = {
                "version": version,
                "payload": payload,
                "stored_at": stored_at,
                "delivered_at": delivered_at or stored_at,
            }

            return (
                True,
                {
                    "accepted": True,
                    "ack_id": f"ack_{context_id}_v{version}",
                    "stored_at": stored_at,
                },
                200,
            )

    def get(self, scope: str, context_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest payload for (scope, context_id)."""
        with self._lock:
            record = self._store.get((scope, context_id))
            return record["payload"] if record else None

    def get_version(self, scope: str, context_id: str) -> Optional[int]:
        """Get the current version for (scope, context_id)."""
        with self._lock:
            record = self._store.get((scope, context_id))
            return record["version"] if record else None

    def get_category(self, slug: str) -> Optional[Dict[str, Any]]:
        return self.get("category", slug)

    def get_merchant(self, merchant_id: str) -> Optional[Dict[str, Any]]:
        return self.get("merchant", merchant_id)

    def get_customer(self, customer_id: str) -> Optional[Dict[str, Any]]:
        return self.get("customer", customer_id)

    def get_trigger(self, trigger_id: str) -> Optional[Dict[str, Any]]:
        return self.get("trigger", trigger_id)

    def counts_by_scope(self) -> Dict[str, int]:
        """Return counts of each scope loaded."""
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        with self._lock:
            for (scope, _), _ in self._store.items():
                if scope in counts:
                    counts[scope] += 1
        return counts

    def clear(self):
        """Clear all stored contexts."""
        with self._lock:
            self._store.clear()

    def load_from_directory(self, base_dir: str):
        """Load seed or expanded JSON files from disk into the store."""
        import os
        import json
        from pathlib import Path

        p = Path(base_dir)
        # Categories
        cat_dir = p / "categories"
        if cat_dir.exists():
            for f in cat_dir.glob("*.json"):
                try:
                    with open(f, encoding="utf-8") as fp:
                        data = json.load(fp)
                        slug = data.get("slug", f.stem)
                        self.push("category", slug, 1, data)
                except Exception as e:
                    print(f"Error loading category {f}: {e}")

        # Merchants
        m_dir = p / "merchants"
        if m_dir.exists():
            for f in m_dir.glob("*.json"):
                try:
                    with open(f, encoding="utf-8") as fp:
                        data = json.load(fp)
                        mid = data.get("merchant_id", f.stem)
                        self.push("merchant", mid, 1, data)
                except Exception as e:
                    print(f"Error loading merchant {f}: {e}")
        elif (p / "merchants_seed.json").exists():
            with open(p / "merchants_seed.json", encoding="utf-8") as fp:
                for m in json.load(fp).get("merchants", []):
                    self.push("merchant", m["merchant_id"], 1, m)

        # Customers
        c_dir = p / "customers"
        if c_dir.exists():
            for f in c_dir.glob("*.json"):
                try:
                    with open(f, encoding="utf-8") as fp:
                        data = json.load(fp)
                        cid = data.get("customer_id", f.stem)
                        self.push("customer", cid, 1, data)
                except Exception as e:
                    print(f"Error loading customer {f}: {e}")
        elif (p / "customers_seed.json").exists():
            with open(p / "customers_seed.json", encoding="utf-8") as fp:
                for c in json.load(fp).get("customers", []):
                    self.push("customer", c["customer_id"], 1, c)

        # Triggers
        t_dir = p / "triggers"
        if t_dir.exists():
            for f in t_dir.glob("*.json"):
                try:
                    with open(f, encoding="utf-8") as fp:
                        data = json.load(fp)
                        tid = data.get("id", f.stem)
                        self.push("trigger", tid, 1, data)
                except Exception as e:
                    print(f"Error loading trigger {f}: {e}")
        elif (p / "triggers_seed.json").exists():
            with open(p / "triggers_seed.json", encoding="utf-8") as fp:
                for t in json.load(fp).get("triggers", []):
                    self.push("trigger", t["id"], 1, t)
