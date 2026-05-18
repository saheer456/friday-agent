# Fix Report (Current Codebase)

Date: 2026-05-18
Scope checked: `backend/`, `web/`, `frontend/`
Validation run: Python compile check and frontend production build.

## What Passed
- `python -m compileall backend web` completed successfully.
- `npm run build` in `frontend/` completed successfully.

## Working Errors and Logical Issues

### 1) Readiness endpoint always reports memory as ready
- File: `web/server.py`
- Problem: `_readiness_info()` returns `"memory_ready": True` unconditionally.
- Impact: UI and health consumers get false readiness signal even when memory initialization failed.
- Fix:
```python
# current
"memory_ready": True,

# fix
"memory_ready": _memory_ready,
```

### 2) Silent failure path when all providers fail streaming
- File: `backend/providers/manager.py`, `backend/brain.py`
- Problem: `ProviderManager.stream()` logs error when all providers fail but does not yield an error event. In `brain._iter_chat_turn()`, this can end the loop with no assistant text and no error.
- Impact: User can receive an empty response (appears like a freeze/no answer).
- Fix option A (preferred): Emit final error event from provider manager:
```python
# end of ProviderManager.stream()
yield {"type": "error", "error": f"All providers failed. Last error: {last_error or 'unknown'}"}
```
Then keep current brain error handling.
- Fix option B: Add a fallback error in `brain.py` when stream yields neither text/tool/error.

### 3) Conversation history mutations are not synchronized
- File: `backend/brain.py`, `web/server.py`
- Problem: `_history_lock = asyncio.Lock()` exists but is never used; multiple endpoints mutate `conversation_history` directly (`append`, slice trim, and `clear`).
- Impact: Concurrent requests can interleave updates, causing lost/garbled history state.
- Fix:
  - Add helper functions in `brain.py` (e.g., `append_history`, `trim_history`, `clear_history`) that always use `_history_lock`.
  - Update `/api/clear` to call an async safe clear function instead of direct `brain.conversation_history.clear()`.

### 4) Non-stream chat endpoint bypasses API key guard
- File: `web/server.py`
- Problem: `/api/chat/stream` requires `verify_api_key`, but `/api/chat` does not.
- Impact: In deployments with `FRIDAY_API_KEY` set, one chat endpoint is protected and the other is open.
- Fix:
```python
@app.post("/api/chat")
async def chat_once(body: ChatBody, _auth: None = Depends(verify_api_key)):
    ...
```

### 5) TTS queue can overlap audio playback
- File: `frontend/src/hooks/useVoice.ts`
- Problem: `queueTTS()` starts a new request/playback without stopping an already playing clip.
- Impact: Overlapping voice outputs and leaked object URLs in rapid multi-response flows.
- Fix:
  - Call `stopAudio()` at the start of `queueTTS()` before creating a new `AbortController`.
  - Keep current abort/onended cleanup behavior.

## Notes
- Most previously reported critical issues in older audit docs appear already fixed in the current code.
- Remaining issues above are active logic and behavior risks rather than syntax/build blockers.
