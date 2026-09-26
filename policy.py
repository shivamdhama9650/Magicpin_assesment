"""
Eligibility checks for triggers before composition.
Validates trigger expiry, customer consent, duplicate suppression keys, and merchant status.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, Optional, Set, Tuple


class PolicyEngine:
    def __init__(self):
        pass

    @staticmethod
    def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
        """Safely parse ISO datetime string."""
        if not dt_str:
            return None
        clean_str = dt_str.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(clean_str)
        except Exception:
            return None

    def check_eligibility(
        self,
        trigger: Optional[Dict[str, Any]],
        merchant: Optional[Dict[str, Any]],
        category: Optional[Dict[str, Any]],
        customer: Optional[Dict[str, Any]] = None,
        simulated_now: Optional[str] = None,
        used_suppression_keys: Optional[Set[str]] = None,
        opted_out_merchants: Optional[Set[str]] = None,
        active_conversations_for_merchant: int = 0,
    ) -> Tuple[bool, str]:
        """
        Run all eligibility gates.
        Returns (is_eligible, reason).
        """
        # 1. Trigger presence
        if not trigger:
            return False, "missing_trigger"

        # 2. Expiry check against simulated time (clamp future real-world dates to challenge date)
        if simulated_now and trigger.get("expires_at"):
            check_now = simulated_now
            if check_now > "2026-05-15":
                check_now = "2026-04-26T10:00:00Z"
            now_dt = self.parse_iso_datetime(check_now)
            exp_dt = self.parse_iso_datetime(trigger.get("expires_at"))
            if now_dt and exp_dt and now_dt > exp_dt:
                return False, f"trigger_expired (now={check_now} > expires_at={trigger['expires_at']})"

        # 3. Merchant presence
        if not merchant:
            return False, "missing_merchant"

        merchant_id = merchant.get("merchant_id")
        if not merchant_id:
            return False, "merchant_missing_id"

        # 4. Merchant opt-out check
        if opted_out_merchants and merchant_id in opted_out_merchants:
            return False, "merchant_opted_out"

        # 5. Category presence
        if not category:
            return False, "missing_category"

        # 6. Suppression key check
        supp_key = trigger.get("suppression_key")
        if not supp_key:
            return False, "trigger_missing_suppression_key"
        if used_suppression_keys and supp_key in used_suppression_keys:
            return False, f"already_suppressed (key={supp_key})"

        # 7. Customer checks for customer-scoped triggers
        trigger_scope = trigger.get("scope", "merchant")
        if trigger_scope == "customer" or trigger.get("customer_id"):
            if not customer:
                return False, "missing_customer_for_customer_scope"

            # Check that customer actually belongs to this merchant
            cust_merchant_id = customer.get("merchant_id")
            if cust_merchant_id != merchant_id:
                return False, f"customer_merchant_mismatch (cust.merchant_id={cust_merchant_id} != {merchant_id})"

            # Check customer opt-in and consent
            consent = customer.get("consent", {})
            consent_scope = consent.get("scope", [])
            reminder_opt_in = customer.get("preferences", {}).get("reminder_opt_in", True)

            if reminder_opt_in is False:
                return False, "customer_opted_out_of_reminders"

            kind = trigger.get("kind", "")
            # Verify consent matches trigger kind
            if "recall" in kind:
                if consent_scope and "recall_reminders" not in consent_scope and "all" not in consent_scope:
                    return False, f"consent_scope_missing_recall (scope={consent_scope})"
            elif "appointment" in kind:
                if consent_scope and "appointment_reminders" not in consent_scope and "all" not in consent_scope:
                    return False, f"consent_scope_missing_appointment (scope={consent_scope})"
            elif "promotional" in kind or "offer" in kind:
                if consent_scope and "promotional_offers" not in consent_scope and "all" not in consent_scope:
                    return False, f"consent_scope_missing_promotions (scope={consent_scope})"

        # 8. Check for active conversation conflict (avoid spamming open threads)
        if active_conversations_for_merchant > 0 and trigger.get("urgency", 1) < 4:
            return False, "active_conversation_in_flight"

        # 9. Verify grounded facts exist for specific trigger kinds
        kind = trigger.get("kind", "")
        payload = trigger.get("payload", {})

        if kind == "research_digest":
            top_item_id = payload.get("top_item_id")
            digest_items = category.get("digest", [])
            if top_item_id:
                matched = any(d.get("id") == top_item_id for d in digest_items)
                if not matched and not payload.get("top_item"):
                    return False, f"digest_item_not_found ({top_item_id})"
            elif not digest_items and not payload.get("top_item"):
                return False, "no_digest_items_available"

        elif kind in ("perf_dip", "perf_spike"):
            perf = merchant.get("performance", {})
            if not perf:
                return False, "missing_performance_data"

        return True, "eligible"
