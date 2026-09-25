"""
Validates message structure, field completeness, taboo phrases,
URL restrictions, and conversation repetition.
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple


class OutputValidator:
    URL_REGEX = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
    NUMBER_REGEX = re.compile(r"\b\d+(?:[\.,]\d+)?%?|\b₹\s*\d+(?:[\.,]\d+)?")

    def validate(
        self,
        action: Dict[str, Any],
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
        previous_messages_in_conv: Optional[List[str]] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Validate composed message against challenge rules and evaluation rubric.
        Returns: (is_valid, list_of_errors)
        """
        errors = []

        # 1. Structural checks
        required_fields = ["body", "cta", "send_as", "suppression_key", "rationale"]
        for field in required_fields:
            if field not in action or action[field] is None:
                errors.append(f"missing_required_field: {field}")

        body = action.get("body", "").strip()
        if not body:
            errors.append("empty_body")
            return False, errors

        # 2. Strict URL Prohibition (Meta rejection penalty -3)
        if self.URL_REGEX.search(body):
            errors.append("url_in_body_prohibited")

        # 3. Check for leftover template placeholders
        if re.search(r"\{\{\d+\}\}|\[\w+\]|<[\w\s]+>", body):
            errors.append("unfilled_placeholders_in_body")

        # 4. send_as verification
        is_customer = trigger.get("scope") == "customer" or customer is not None
        expected_send_as = "merchant_on_behalf" if is_customer else "vera"
        if action.get("send_as") != expected_send_as:
            errors.append(f"send_as_mismatch (expected {expected_send_as}, got {action.get('send_as')})")

        # 5. suppression_key match
        expected_supp = trigger.get("suppression_key", "")
        if action.get("suppression_key") != expected_supp:
            errors.append(f"suppression_key_mismatch (expected {expected_supp}, got {action.get('suppression_key')})")

        # 6. Category taboo vocabulary check
        voice = category.get("voice", {})
        taboos = voice.get("vocab_taboo", [])
        body_lower = body.lower()
        for taboo in taboos:
            # Clean taboo strings like "FDA-approved (use only...)"
            clean_taboo = re.split(r"\(|\buse\b", taboo)[0].strip().lower()
            if clean_taboo and len(clean_taboo) > 2 and clean_taboo in body_lower:
                errors.append(f"taboo_word_used: '{clean_taboo}'")

        # 7. Anti-repetition check (same body verbatim sent previously in conversation)
        if previous_messages_in_conv:
            for prev_body in previous_messages_in_conv:
                if body.strip().lower() == prev_body.strip().lower():
                    errors.append("exact_duplicate_body_in_conversation")
                    break

        return len(errors) == 0, errors

    def clean_and_repair(
        self,
        action: Dict[str, Any],
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Removes prohibited URLs or taboo phrases if accidentally introduced.
        Ensures all contract fields are present.
        """
        body = action.get("body", "")
        # Remove any URLs
        body = self.URL_REGEX.sub("", body).strip()

        # Remove taboo words
        voice = category.get("voice", {})
        for taboo in voice.get("vocab_taboo", []):
            clean_taboo = re.split(r"\(|\buse\b", taboo)[0].strip()
            if clean_taboo and len(clean_taboo) > 2:
                pattern = re.compile(re.escape(clean_taboo), re.IGNORECASE)
                body = pattern.sub("", body).strip()

        # Clean double spaces
        body = re.sub(r"\s{2,}", " ", body)

        is_customer = trigger.get("scope") == "customer" or customer is not None
        action["body"] = body
        action["send_as"] = "merchant_on_behalf" if is_customer else "vera"
        action["suppression_key"] = trigger.get("suppression_key", "")
        if "cta" not in action or not action["cta"]:
            action["cta"] = "binary_yes_no"
        if "rationale" not in action or not action["rationale"]:
            action["rationale"] = f"Composed for {trigger.get('kind')} anchored on verifiable context facts."
        if "template_name" not in action:
            action["template_name"] = f"{action['send_as']}_{trigger.get('kind', 'generic')}_v1"
        if "template_params" not in action:
            action["template_params"] = [merchant.get("identity", {}).get("name", "")]

        return action
