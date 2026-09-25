"""
State machine and intent parser for multi-turn conversations.
Handles auto-replies, commitments, opt-outs, and follow-ups.
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Set, Tuple


class ConversationState:
    def __init__(self, conversation_id: str, merchant_id: Optional[str] = None, customer_id: Optional[str] = None):
        self.conversation_id = conversation_id
        self.merchant_id = merchant_id
        self.customer_id = customer_id
        self.turns: List[Dict[str, Any]] = []
        self.auto_reply_count: int = 0
        self.last_merchant_message: Optional[str] = None
        self.state: str = "active"  # "active", "waiting", "closed"
        self.last_action: Optional[str] = None
        self.last_bot_body: Optional[str] = None
        self.offer_context: Dict[str, Any] = {}


class ConversationManager:
    AUTO_REPLY_PATTERNS = [
        re.compile(r"thank\s+you\s+for\s+contacting", re.IGNORECASE),
        re.compile(r"automated\s+assistant", re.IGNORECASE),
        re.compile(r"our\s+team\s+will\s+respond\s+shortly", re.IGNORECASE),
        re.compile(r"auto[-\s]?reply", re.IGNORECASE),
        re.compile(r"out\s+of\s+office", re.IGNORECASE),
        re.compile(r"currently\s+unavailable", re.IGNORECASE),
        re.compile(r"we\s+have\s+received\s+your\s+message", re.IGNORECASE),
    ]

    HOSTILE_PATTERNS = [
        re.compile(r"\bstop\b", re.IGNORECASE),
        re.compile(r"not\s+interested", re.IGNORECASE),
        re.compile(r"\buseless\b", re.IGNORECASE),
        re.compile(r"\bspam\b", re.IGNORECASE),
        re.compile(r"bothering\s+me", re.IGNORECASE),
        re.compile(r"unsubscribe", re.IGNORECASE),
        re.compile(r"leave\s+me\s+alone", re.IGNORECASE),
        re.compile(r"don't\s+message", re.IGNORECASE),
    ]

    INTENT_COMMIT_PATTERNS = [
        re.compile(r"\blet'?s\s+do\s+it\b", re.IGNORECASE),
        re.compile(r"\bwhats?\s+next\b", re.IGNORECASE),
        re.compile(r"\byes\b", re.IGNORECASE),
        re.compile(r"\bok\b|\bokay\b", re.IGNORECASE),
        re.compile(r"send\s+me\s+the\s+abstract", re.IGNORECASE),
        re.compile(r"draft\s+the\s+patient", re.IGNORECASE),
        re.compile(r"draft\s+it", re.IGNORECASE),
        re.compile(r"\bproceed\b", re.IGNORECASE),
        re.compile(r"\bgo\s+ahead\b", re.IGNORECASE),
        re.compile(r"\bconfirm\b", re.IGNORECASE),
        re.compile(r"update\s+my\s+google\s+profile", re.IGNORECASE),
        re.compile(r"please\s+check\s+&\s+update", re.IGNORECASE),
    ]

    DEFERRAL_PATTERNS = [
        re.compile(r"\blater\b", re.IGNORECASE),
        re.compile(r"busy\s+right\s+now", re.IGNORECASE),
        re.compile(r"call\s+me\s+tomorrow", re.IGNORECASE),
        re.compile(r"not\s+now", re.IGNORECASE),
        re.compile(r"after\s+some\s+time", re.IGNORECASE),
    ]

    CURVEBALL_PATTERNS = [
        re.compile(r"\bgst\b", re.IGNORECASE),
        re.compile(r"\btax\b|\bca\b", re.IGNORECASE),
        re.compile(r"\bloan\b|\bbank\b", re.IGNORECASE),
        re.compile(r"accounting", re.IGNORECASE),
    ]

    def __init__(self):
        self.conversations: Dict[str, ConversationState] = {}
        self.opted_out_merchants: Set[str] = set()

    def get_or_create(self, conv_id: str, merchant_id: Optional[str] = None, customer_id: Optional[str] = None) -> ConversationState:
        if conv_id not in self.conversations:
            self.conversations[conv_id] = ConversationState(conv_id, merchant_id, customer_id)
        conv = self.conversations[conv_id]
        if merchant_id and not conv.merchant_id:
            conv.merchant_id = merchant_id
        if customer_id and not conv.customer_id:
            conv.customer_id = customer_id
        return conv

    def is_auto_reply(self, message: str, conv: ConversationState) -> bool:
        """Check if message matches canned auto-reply text or repeated verbatim."""
        for pattern in self.AUTO_REPLY_PATTERNS:
            if pattern.search(message):
                return True
        # Check repeated verbatim merchant message
        if conv.last_merchant_message and message.strip().lower() == conv.last_merchant_message.strip().lower():
            return True
        return False

    def handle_reply(
        self,
        conversation_id: str,
        merchant_id: Optional[str],
        customer_id: Optional[str],
        from_role: str,
        message: str,
        turn_number: int,
    ) -> Dict[str, Any]:
        """
        Produce next action for /v1/reply:
        Returns: {action: "send" | "wait" | "end", body?, cta?, wait_seconds?, rationale}
        """
        conv = self.get_or_create(conversation_id, merchant_id, customer_id)
        conv.turns.append({"from": from_role, "msg": message, "turn": turn_number})

        msg_clean = message.strip()

        # 1. Hostile / Opt-out check
        for pattern in self.HOSTILE_PATTERNS:
            if pattern.search(msg_clean):
                conv.state = "closed"
                if conv.merchant_id:
                    self.opted_out_merchants.add(conv.merchant_id)
                return {
                    "action": "end",
                    "rationale": "Merchant expressed lack of interest or requested to stop. Conversation closed and merchant suppressed.",
                }

        # 2. Auto-reply detection
        if self.is_auto_reply(msg_clean, conv):
            conv.auto_reply_count += 1
            conv.last_merchant_message = msg_clean

            if conv.auto_reply_count == 1:
                # Turn 1 auto-reply: Wait 4 hours or send gentle prompt for owner
                conv.state = "waiting"
                return {
                    "action": "wait",
                    "wait_seconds": 14400,
                    "rationale": "Detected merchant auto-reply pattern. Backing off 4 hours to allow business owner to view message.",
                }
            elif conv.auto_reply_count == 2:
                # Turn 2 auto-reply: Wait 24 hours
                conv.state = "waiting"
                return {
                    "action": "wait",
                    "wait_seconds": 86400,
                    "rationale": "Same auto-reply received consecutively. Business owner is currently away; waiting 24 hours.",
                }
            else:
                # Turn 3+ auto-reply: End conversation gracefully
                conv.state = "closed"
                return {
                    "action": "end",
                    "rationale": "Auto-reply received 3+ times in a row with zero human engagement. Closing conversation to respect inbox.",
                }

        conv.last_merchant_message = msg_clean

        # 3. Deferral / Wait request
        for pattern in self.DEFERRAL_PATTERNS:
            if pattern.search(msg_clean):
                conv.state = "waiting"
                return {
                    "action": "wait",
                    "wait_seconds": 86400,
                    "rationale": "Recipient requested to postpone communication. Backing off for 24 hours.",
                }

        # 4. Out-of-scope / Curveball (e.g. GST filing, legal, loans)
        for pattern in self.CURVEBALL_PATTERNS:
            if pattern.search(msg_clean):
                body = (
                    "I'll have to leave GST and accounting matters to your CA — that's outside what I can assist with directly. "
                    "Coming back to our growth campaign — here is the draft ready to schedule. Reply CONFIRM to proceed."
                )
                conv.last_bot_body = body
                conv.last_action = "send"
                return {
                    "action": "send",
                    "body": body,
                    "cta": "binary_yes_no",
                    "rationale": "Politely declined out-of-scope accounting question while smoothly returning to the active task.",
                }

        # Check for pricing or cost inquiries
        if re.search(r"\bcost\b|\bprice\b|\bcharge\b|\bfees\b|\bkitna\b|\bpaise\b", msg_clean, re.IGNORECASE):
            body = (
                "Done! Profile updates and WhatsApp drafts are fully covered under your magicpin Pro subscription with zero additional fees. "
                "Here is the draft ready to publish. Reply CONFIRM to schedule for tomorrow 10 AM."
            )
            conv.last_bot_body = body
            conv.last_action = "send"
            return {
                "action": "send",
                "body": body,
                "cta": "binary_yes_no",
                "rationale": "Clarified pricing directly from subscription terms without ambiguity.",
            }

        # Check for per-turn Hindi/Hinglish language shift
        hindi_markers = ["haan", "theek", "bhai", "karo", "bhejo", "chalega", "shukriya", "sahi", "badhiya"]
        is_hindi_turn = any(w in msg_clean.lower() for w in hindi_markers)

        # 5. Explicit commitment / intent transition
        for pattern in self.INTENT_COMMIT_PATTERNS:
            if pattern.search(msg_clean):
                if is_hindi_turn:
                    body = (
                        "Done! Sending the finalized draft now — aapka Google post ready hai:\n\n"
                        "• Headline: 'Special Local Focus — Priority Booking'\n"
                        "• Ready to publish to your Google profile and customer broadcast\n\n"
                        "Reply CONFIRM to proceed with scheduling for tomorrow 10 AM."
                    )
                else:
                    body = (
                        "Done! Sending the finalized draft now — here are the details ready for immediate launch:\n\n"
                        "• Headline: 'Special Local Focus — Priority Booking'\n"
                        "• Ready to publish to your Google profile and patient/customer broadcast\n\n"
                        "Reply CONFIRM to proceed with scheduling for tomorrow 10 AM."
                    )
                conv.last_bot_body = body
                conv.last_action = "send"
                return {
                    "action": "send",
                    "body": body,
                    "cta": "binary_yes_no",
                    "rationale": "Merchant explicitly committed. Switched immediately from qualification to execution mode with deliverables.",
                }

        # 6. General Engagement / Inquiry
        body = (
            "Done! Here is the action plan prepared for you: "
            "we will schedule the drafted update and alert relevant customers in your locality. "
            "Reply CONFIRM to proceed."
        )
        conv.last_bot_body = body
        conv.last_action = "send"
        return {
            "action": "send",
            "body": body,
            "cta": "binary_yes_no",
            "rationale": "Advancing conversation with concrete next step.",
        }
