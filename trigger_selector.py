"""
Selects and ranks eligible triggers for each merchant during tick cycles.
Limits outreach to one priority action per merchant, up to 20 total actions.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple
from context_store import ContextStore
from policy import PolicyEngine


class TriggerSelector:
    def __init__(self, policy: Optional[PolicyEngine] = None):
        self.policy = policy or PolicyEngine()

    def select_triggers_for_tick(
        self,
        store: ContextStore,
        available_trigger_ids: List[str],
        simulated_now: Optional[str],
        used_suppression_keys: Set[str],
        opted_out_merchants: Set[str],
        active_conversations: Dict[str, Any],
        max_actions: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Takes list of trigger IDs from /v1/tick.
        Returns a list of resolved dicts:
        {
            "trigger": trigger_dict,
            "merchant": merchant_dict,
            "category": category_dict,
            "customer": customer_dict_or_None,
            "plan": plan_dict
        }
        At most 1 opportunity per merchant.
        Capped at max_actions (20).
        """
        # 1. Resolve and filter eligible triggers
        eligible_candidates: List[Dict[str, Any]] = []

        for tid in available_trigger_ids:
            trigger = store.get_trigger(tid)
            if not trigger:
                continue

            merchant_id = trigger.get("merchant_id")
            if not merchant_id:
                continue

            merchant = store.get_merchant(merchant_id)
            if not merchant:
                continue

            category_slug = merchant.get("category_slug")
            category = store.get_category(category_slug) if category_slug else None
            if not category:
                continue

            customer_id = trigger.get("customer_id")
            customer = store.get_customer(customer_id) if customer_id else None

            # Count active conversations for this merchant
            merchant_active_convs = 0
            for conv in active_conversations.values():
                c_mid = conv.merchant_id if hasattr(conv, "merchant_id") else conv.get("merchant_id")
                c_state = getattr(conv, "state", None) or (conv.get("state") if isinstance(conv, dict) else None)
                is_closed = (c_state == "closed")
                if c_mid == merchant_id and not is_closed:
                    merchant_active_convs += 1

            is_eligible, reason = self.policy.check_eligibility(
                trigger=trigger,
                merchant=merchant,
                category=category,
                customer=customer,
                simulated_now=simulated_now,
                used_suppression_keys=used_suppression_keys,
                opted_out_merchants=opted_out_merchants,
                active_conversations_for_merchant=merchant_active_convs,
            )

            if is_eligible:
                score = self._compute_ranking_score(trigger, merchant, category, customer)
                eligible_candidates.append({
                    "trigger": trigger,
                    "merchant": merchant,
                    "category": category,
                    "customer": customer,
                    "score": score,
                    "merchant_id": merchant_id,
                })

        # 2. Group by merchant and pick highest scoring trigger per merchant
        by_merchant: Dict[str, Dict[str, Any]] = {}
        for candidate in eligible_candidates:
            mid = candidate["merchant_id"]
            if mid not in by_merchant or candidate["score"] > by_merchant[mid]["score"]:
                by_merchant[mid] = candidate

        # 3. Sort merchants by trigger score descending and cap at max_actions
        sorted_candidates = sorted(by_merchant.values(), key=lambda x: x["score"], reverse=True)
        selected = sorted_candidates[:max_actions]

        # 4. Attach a compact internal plan to each selected opportunity
        for item in selected:
            item["plan"] = self._create_composer_plan(
                item["trigger"], item["merchant"], item["category"], item["customer"]
            )

        return selected

    def _compute_ranking_score(
        self,
        trigger: Dict[str, Any],
        merchant: Dict[str, Any],
        category: Dict[str, Any],
        customer: Optional[Dict[str, Any]],
    ) -> float:
        """
        Rank candidate triggers:
        Base: urgency (1-5) * 10
        Boost: signal matching (+5 to +15)
        Boost: active customer relationship (+8)
        Boost: verified active offer (+5)
        """
        urgency = trigger.get("urgency", 1)
        score = float(urgency) * 10.0

        kind = trigger.get("kind", "")
        signals = merchant.get("signals", [])

        # High priority for active planning or explicit intents
        if kind == "active_planning_intent":
            score += 25.0

        # Customer recalls and followups
        if kind in ("recall_due", "trial_followup", "appointment_tomorrow", "chronic_refill_due"):
            score += 15.0

        # Signal alignment
        if "ctr_below_peer_median" in signals and kind in ("research_digest", "perf_spike", "perf_dip"):
            score += 8.0
        if "stale_posts" in str(signals) and kind in ("curious_ask_due", "festival_upcoming"):
            score += 7.0
        if "high_risk_adult_cohort" in signals and kind == "research_digest":
            score += 10.0

        # Merchant offers available
        active_offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
        if active_offers:
            score += 5.0

        # Recency/freshness
        if trigger.get("source") == "internal":
            score += 3.0

        return score

    def _create_composer_plan(
        self,
        trigger: Dict[str, Any],
        merchant: Dict[str, Any],
        category: Dict[str, Any],
        customer: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Create a compact internal plan to focus generation:
        { "goal": "...", "facts": [...], "language": "...", "recipient": "..." }
        """
        is_customer = trigger.get("scope") == "customer" or customer is not None
        recipient = "customer" if is_customer else "merchant"
        send_as = "merchant_on_behalf" if is_customer else "vera"

        # Determine language preference
        if is_customer and customer:
            lang = customer.get("identity", {}).get("language_pref", "hi-en mix")
        else:
            langs = merchant.get("identity", {}).get("languages", ["en", "hi"])
            lang = "hi-en mix" if "hi" in langs else langs[0]

        kind = trigger.get("kind", "")
        return {
            "goal": f"engage {recipient} for {kind}",
            "kind": kind,
            "recipient": recipient,
            "send_as": send_as,
            "language": lang,
            "suppression_key": trigger.get("suppression_key", ""),
        }
