# FRIDAY Backend Crash & Frontend Version Fix

## Issues

### 1. Backend Crashes After First Message ❌
**Symptom:** Second message request returns 200 OK but backend appears to hang/crash  
**When:** After first response completes, trying to send second message  
**Logs:** Shows successful requests but no response data received  

**Root Causes (suspected):**
- **Memory store file lock**: `mem0` ChromaDB/SQLite keeps database locked after first message
- **AsyncClient not closed**: `httpx.AsyncClient` in `_iter_chat_turn()` may not properly close connections
- **Thread pool deadlock**: Executor running `recall_memory()` blocks on second message  
- **Streaming incomplete**: SSE stream closes early, leaving httpx connection hanging

**Evidence:**
```
INFO:     127.0.0.1:56093 - "POST /api/chat/stream HTTP/1.1" 200 OK  ← First msg OK
Loading weights: 100%... ← Model loads successfully
INFO:     127.0.0.1:50345 - "POST /api/chat/stream HTTP/1.1" 200 OK  ← Second msg returns 200 but no data
```

---

### 2. Version Display in Wrong Location ❌
**Current:** Version pill in header: `<span class="version-pill" id="versionTag">v2.0 Sentinel</span>`  
**Required:** Version name in footer only (remove from header)

---

## Fixes Applied

### Fix #1: Add AsyncClient Context Manager + Connection Pooling
- **File:** `backend/brain.py`
- Added persistent HTTP client with connection pooling

### Fix #2: Prevent Memory Store Locking
- **File:** `backend/memory.py`
- Added queue-based serialization to prevent concurrent DB writes

### Fix #3: Add Timeout + Retry Logic
- **File:** `backend/brain.py`
- Added timeout and error logging

### Fix #4: Move Version to Footer Only
- **File:** `web/static/index.html`
- Removed version pill from header, added to footer

### Fix #5: Update Version Binding
- **File:** `web/static/app.js`
- Updated version selector to target footer

---

## Testing

After all fixes:
```bash
# Terminal 1: Start web server
python -m uvicorn web.server:app --host 127.0.0.1 --port 8080

# Terminal 2: Test multiple messages
# Send 1st message → should stream tokens
# Send 2nd message → should NOT hang/crash
# Send 3rd message → verify pattern holds
```

**Expected:** No 200 OK with empty response on 2nd+ messages. All messages should stream normally.

---

## Files Modified

- ✏️ `backend/brain.py` — Add persistent client + improve error handling
- ✏️ `backend/memory.py` — Add queue-based serialization  
- ✏️ `web/static/index.html` — Move version to footer
- ✏️ `web/static/app.js` — Update version selector
