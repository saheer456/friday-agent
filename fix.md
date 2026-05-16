# Tool Calling Loop — Fixes Implemented

## Problem

The LLM tool calling loop in `brain.py:_iter_chat_turn()` could enter runaway loops, making excessive API calls, wasting tokens, and eventually returning errors or truncating mid-response.

## Root Causes

| # | Issue | Location |
|---|-------|----------|
| 1 | Loop detection only caught exact arg matches | `call_sig = f"{fn_name}({fn_args})"` |
| 2 | No total tool call limit per turn | `max_tool_rounds = 10` but each round can have multiple calls |
| 3 | No consecutive failure tracking | Errors kept triggering more tool calls |
| 4 | No per-turn timeout | User waited 2-5 minutes before loop exited |
| 5 | Tool results not size-limited | 10KB+ outputs bloated context |
| 6 | No argument validation | Malformed JSON args caused cascading errors |

## Fixes Implemented

All fixes are in `backend/brain.py:_iter_chat_turn()`.

### Fix 1: Per-turn tool call limit
```python
max_total_tool_calls = 15  # Hard cap on total tool calls per user turn
tool_call_count = 0
```
Each tool call increments the counter. When it exceeds 15, a forced stop message is injected telling the LLM to provide its final answer.

### Fix 2: Consecutive failure tracking
```python
consecutive_failures = 0
```
After each tool execution, checks if the result contains an error. If 3+ consecutive tools fail, the loop injects a stop message and skips further tool calls.

### Fix 3: Per-turn timeout
```python
turn_timeout = 60.0  # 60 seconds max per user turn
turn_start = time.monotonic()
```
At the top of each round, checks elapsed time. If >60 seconds, yields an error message and breaks the loop.

### Fix 4: Size-limit tool results
```python
max_tool_result_chars = 4000
```
After tool execution, truncates results to 4000 chars with a `... [output truncated]` suffix. Prevents context window bloat.

### Fix 5: Fuzzy loop detection
```python
tool_name_counts: dict[str, int] = {}
```
Tracks how many times each tool function name is called in a single turn. If any tool is called 4+ times, the loop is detected and stopped. This catches loops where the same tool is called with different arguments.

### Fix 6: Argument validation
```python
try:
    json.loads(fn_args) if isinstance(fn_args, str) else fn_args
except (json.JSONDecodeError, TypeError):
    # Inject error message, skip execution
```
Validates tool call arguments before execution. Malformed JSON is caught early and reported as an error to the LLM.

## Safety Layer Summary

| Layer | Trigger | Action |
|-------|---------|--------|
| Total call limit | >15 tool calls in one turn | Force final answer |
| Per-function limit | Same tool called 4+ times | Force final answer |
| Exact duplicate | Same tool + same args twice | Skip + warn LLM |
| Consecutive failures | 3 tool calls fail in a row | Force final answer |
| Timeout | >60 seconds elapsed | Break loop + yield error |
| Result size | Tool output >4000 chars | Truncate with notice |
| Arg validation | Invalid JSON args | Skip + report error |

## Testing

### Test scenarios to verify:
1. **Normal tool usage** — Single tool call should work as before
2. **Multiple tools in one turn** — Up to 15 calls should work normally
3. **Same tool repeated** — 4th call of same tool name should trigger loop detection
4. **Exact duplicate call** — Same tool + same args should be skipped
5. **Failing tools** — 3 consecutive failures should force final answer
6. **Large output** — Tool returning >4000 chars should be truncated
7. **Malformed args** — Invalid JSON should be caught before execution
8. **Timeout** — Long-running tool chains should exit after 60 seconds

### Manual test commands:
```bash
# Start server
start_web.bat

# Test normal chat
curl -X POST http://127.0.0.1:8080/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the weather today?", "voice_mode": false}'

# Test with tools (if Google credentials configured)
curl -X POST http://127.0.0.1:8080/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "List my upcoming calendar events", "voice_mode": false}'
```

## Files Changed

| File | Lines Added | Lines Removed | Description |
|------|-------------|---------------|-------------|
| `backend/brain.py` | ~45 | ~8 | All 6 safety fixes in `_iter_chat_turn()` |

## No Breaking Changes

All fixes are additive safety rails. Normal tool usage (1-3 calls per turn, no errors) behaves identically. The fixes only activate when something goes wrong.
