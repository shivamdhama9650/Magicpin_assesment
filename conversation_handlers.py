"""
Multi-turn response handler for merchant and customer interactions.
"""

from __future__ import annotations
from typing import Any, Dict
from conversation_manager import ConversationManager, ConversationState


_manager = ConversationManager()


def respond(state: ConversationState, merchant_message: str) -> Dict[str, Any]:
    """
    Given the conversation state so far + the merchant's latest message,
    produce the reply action.
    """
    turn_number = len(state.turns) + 1
    return _manager.handle_reply(
        conversation_id=state.conversation_id,
        merchant_id=state.merchant_id,
        customer_id=state.customer_id,
        from_role="merchant",
        message=merchant_message,
        turn_number=turn_number,
    )
