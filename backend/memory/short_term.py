from collections import deque
from typing import List, Dict

# Maintain the last 20 exchanges
_context_buffer: deque = deque(maxlen=20)

def add_exchange(user_msg: str, ai_response: str) -> None:
    """Add a user message and assistant response to the rolling buffer."""
    if not user_msg or not ai_response:
        return
    _context_buffer.append({"role": "user", "content": user_msg[:500]})
    _context_buffer.append({"role": "assistant", "content": ai_response[:500]})

def get_recent_context() -> List[Dict[str, str]]:
    """Retrieve the recent conversation context."""
    return list(_context_buffer)

def clear_buffer() -> None:
    """Clear the short-term memory buffer."""
    _context_buffer.clear()
