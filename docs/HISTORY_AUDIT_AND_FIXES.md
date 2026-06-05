# Chat History — Audit, Fixes & Improvements

**Scope:** Sidebar session list, chat transcript loading, `/api/sessions*` endpoints, `chat_history.py` dual backend, Supabase schema/RLS, frontend `useChat` hook.  
**Date:** 2026-06-05  
**Status:** Updated 2026-06-05 — critical backend + frontend fixes applied (see §9). Remaining optional improvements below.

---

## Table of Contents

1. [Executive summary](#1-executive-summary)
2. [Critical — fix immediately](#2-critical--fix-immediately)
3. [Security risks](#3-security-risks)
4. [API & backend logic bugs](#4-api--backend-logic-bugs)
5. [Frontend issues (remaining)](#5-frontend-issues-remaining)
6. [Step-by-step fix guide](#6-step-by-step-fix-guide)
7. [Improvements roadmap](#7-improvements-roadmap)
8. [Test plan](#8-test-plan)

---

## 1. Executive summary

The history feature spans three layers:

| Layer | Files |
|-------|-------|
| UI | `Sidebar.tsx`, `ChatArea.tsx`, `useChat.ts` |
| API | `web/server.py` (session routes ~L781–863) |
| Storage | `backend/memory/chat_history.py`, `supabase-schema.sql` |

**Already fixed (this session):**
- Sidebar session rows stacking title + meta vertically
- Date separators using full `createdAt` instead of time-only `timestamp`
- Clearing messages + loading spinner on session switch
- Scroll position preservation when loading older messages (partial — see §5.3)

**Still broken or risky:**
- `web/server.py` is **staged for deletion** — app cannot start (`uvicorn web.server:app` fails)
- Supabase message queries return the **oldest** messages, not the **latest**
- Session APIs have **no ownership checks** (IDOR) when using the service-role key
- `create_session` API does not attach `user_id`
- Dual-write to SQLite **and** Supabase on every mutation even when Supabase is active

---

## 2. Critical — fix immediately

### C-1 — `web/server.py` deleted (deployment blocker)

**Symptom:** `start_web.bat`, `render.yaml`, and docs all run `uvicorn web.server:app`. The file is currently **staged for deletion** in git.

**Impact:** No API server → all history, chat, auth endpoints unreachable.

**Fix:**
```bash
git restore --staged web/server.py
git restore web/server.py
# Also restore static assets if needed:
git restore web/static/
```

Verify:
```bash
python -m uvicorn web.server:app --host 127.0.0.1 --port 8080
curl http://127.0.0.1:8080/api/system
```

---

### C-2 — Supabase `get_messages` returns wrong slice

**File:** `backend/memory/chat_history.py` → `_sb_get_messages`

**Bug:** Query uses `order("id", asc=True).limit(limit)` which returns the **first** N messages (oldest). SQLite correctly uses `ORDER BY id DESC LIMIT N` then reverses.

**Symptom:** Long conversations show ancient messages at the bottom; recent chat appears missing. Infinite scroll loads wrong batches.

**Fix:**
```python
async def _sb_get_messages(session_id: str, limit: int = 100, before_id: Optional[int] = None) -> List[Dict]:
    sb = await _sb_get_client()
    if sb is None:
        return []
    try:
        query = (
            sb.table("messages")
            .select("id, role, content, created_at")
            .eq("session_id", session_id)
            .order("id", desc=True)   # newest first
            .limit(limit)
        )
        if before_id is not None:
            query = query.lt("id", before_id)
        res = await query.execute()
        rows = res.data or []
        rows.reverse()               # chronological for UI
        return rows
    except Exception as e:
        logger.error(f"Supabase get_messages failed: {e}")
        return []
```

---

### C-3 — Dual-write to SQLite when Supabase is active

**File:** `backend/memory/chat_history.py`

**Bug:** Mutations use `if _use_supabase(): ...` then **always** call the SQLite helper:

```python
async def save_chat_message(...):
    if _use_supabase():
        await _sb_save_message(...)
    await _sq_save_message(...)   # ← runs even in Supabase mode
```

Affected: `save_chat_message`, `delete_session`, `update_session_title`, `clear_chat_history`, `associate_file_with_session`, `remove_file_from_session`.

**Impact:** Shadow copy in `data/memory_store.db`; wasted I/O; local file may contain all users' messages on a shared deploy host.

**Fix:** Use `if/else`, not `if` + unconditional second call:

```python
async def save_chat_message(session_id: str, role: str, content: str) -> None:
    if _use_supabase():
        await _sb_save_message(session_id, role, content)
    else:
        await _sq_save_message(session_id, role, content)
```

Apply the same pattern to all mutation helpers listed above.

---

## 3. Security risks

### S-1 — IDOR: no session ownership verification (High)

**Files:** `web/server.py` (all `/api/sessions/{session_id}/*` routes)

**Risk:** Backend uses `SUPABASE_KEY` (service role), which **bypasses RLS**. Routes accept any `session_id` UUID without checking it belongs to the authenticated user.

**Attack:** Authenticated user guesses/brute-forces another user's `session_id` → read, export, delete, or clear their history.

**Fix:** Add a helper and call it on every session-scoped route:

```python
async def _assert_session_owner(session_id: str, user: dict) -> None:
    from backend.memory import chat_history
    user_id = user.get("id") or user.get("sub")
    if not user_id:
        raise HTTPException(403, "User identity missing")
    if not await chat_history.session_belongs_to_user(session_id, user_id):
        raise HTTPException(404, "Session not found")
```

Implement `session_belongs_to_user` in `chat_history.py`:

```python
async def session_belongs_to_user(session_id: str, user_id: str) -> bool:
    if _use_supabase():
        sb = await _sb_get_client()
        res = await sb.table("sessions").select("id").eq("id", session_id).eq("user_id", user_id).limit(1).execute()
        return bool(res.data)
    # SQLite: no multi-user — allow only if single-tenant local dev
    return True
```

Wire into: `get_session_messages`, `update_session_title`, `delete_session`, `export_session`, `unlink_file`, `clear_history` (when `session_id` set), and validate `body.session_id` in `chat_stream`.

---

### S-2 — `POST /api/sessions` ignores `user_id` (High)

**File:** `web/server.py` L796–800

```python
sid = await chat_history.create_session(body.title)  # no user_id
```

**Impact:** New sessions may get `user_id = ''` (schema default). User cannot see them via RLS-filtered Realtime; list endpoint filters by `user_id` → sessions appear missing or belong to nobody.

**Fix:**
```python
@app.post("/api/sessions")
async def create_session(body: SessionCreateBody, _auth: dict = Depends(verify_auth)):
    user_id = _auth.get("id") or _auth.get("sub")
    sid = await chat_history.create_session(body.title, user_id=user_id)
    return {"ok": True, "id": sid, "title": body.title}
```

---

### S-3 — Inconsistent `user_id` extraction (Medium)

**File:** `web/server.py` L788

```python
user_id = _auth.get("id") or _auth.get("sub") or _auth.get("email", "").split("@")[0]
```

Supabase JWT user object uses `id` (UUID). Falling back to email prefix creates unstable, non-UUID identifiers that won't match `auth.uid()` in RLS or Realtime filters.

**Fix:** Use only `user.get("id")` (or `sub` for other JWT issuers). Reject requests without a proper UUID when Supabase auth is enabled.

---

### S-4 — Service role key in backend (Medium — by design, mitigate)

**File:** `backend/supabase_client.py`, `.env.example`

`SUPABASE_KEY` is documented as the **service role** key. This is required for server-side writes but bypasses RLS.

**Mitigation:**
- Never expose `SUPABASE_KEY` to the frontend (only `VITE_SUPABASE_ANON_KEY`)
- Enforce ownership checks in API layer (S-1)
- Consider a dedicated DB role with scoped grants instead of full service role

---

### S-5 — Session export has no rate limit (Low)

**Route:** `GET /api/sessions/{id}/export`

Unlike `/api/chat/stream` (30/min), export can be hammered to exfiltrate data.

**Fix:** Add `@limiter.limit("10/minute")` and ownership check (S-1).

---

### S-6 — SQLite local mode has no user isolation (Low — dev only)

**File:** `chat_history.py` → `_sq_get_sessions`

All local sessions are global. Acceptable for single-user dev; document that SQLite mode must not be used in multi-tenant production.

---

## 4. API & backend logic bugs

### A-1 — `list_sessions` auto-creates "Default Chat"

**File:** `web/server.py` L790–792

When a user has zero sessions, the API silently creates one. Combined with frontend `createSession()` on empty list, this can create **duplicate** empty sessions on first load.

**Fix:** Remove server-side auto-create; let the frontend own session creation (already does in `useChat` mount effect). Return `{"sessions": []}`.

---

### A-2 — In-memory brain history desync on clear

**File:** `web/server.py` `clear_history`, `brain.conversation_histories`

Clear wipes DB and optionally one in-memory session, but if `session_id` is omitted, in-memory dict is cleared while DB clear may be partial.

**Fix:** Always clear the specific `session_id` in `conversation_histories` when provided; call `brain.conversation_histories[session_id].clear()` not just `del`.

---

### A-3 — SQLite sessions missing `message_count` / `updated_at`

**File:** `_sq_get_sessions`

Returns only `id, title, created_at`. Sidebar meta (message count, "2h ago" from `updated_at`) is empty in local mode.

**Fix:** Add columns or compute via subquery:
```sql
SELECT s.id, s.title, s.created_at,
       (SELECT COUNT(*) FROM chat_history h WHERE h.session_id = s.id) AS message_count,
       COALESCE((SELECT MAX(created_at) FROM chat_history h WHERE h.session_id = s.id), s.created_at) AS updated_at
FROM chat_sessions s
ORDER BY updated_at DESC
```

---

### A-4 — `hasMore` pagination edge case (frontend + API)

**File:** `useChat.ts` L164

```typescript
setHasMoreMessages(dbIds.length >= 50);
```

If the final page has exactly 50 messages, UI shows "scroll for more" when there are none.

**Fix:**
```typescript
setHasMoreMessages(
  data.total != null
    ? messages.length + more.length < data.total
    : more.length >= 50
);
```
Track running total or compare against `data.total` from the load-more response (API should return `total` on every paginated call — it already does).

---

### A-5 — Message React keys inconsistent

**File:** `useChat.ts`

Initial load: `m-${sessionId}-${idx}`. Load more: `db-${m.id}`. Same DB row could get two keys if user reloads.

**Fix:** Always use `db-${m.id}` when `m.id` is numeric; fall back to generated id only for unsaved live messages.

---

### A-6 — `messages` table missing UPDATE RLS policy

**File:** `supabase-schema.sql`

Only SELECT, INSERT, DELETE policies exist. Not urgent if messages are immutable, but add explicit DENY or document immutability.

---

## 5. Frontend issues (remaining)

### F-1 — Scroll preservation races React render

**File:** `ChatArea.tsx`

`onLoadMore().finally()` adjusts scroll in `requestAnimationFrame`, but React state update from `setMessages` may not have flushed to DOM yet. Scroll jump can still occur.

**Fix:** Track `pendingScrollRestore` ref; apply in a `useLayoutEffect` when `messages.length` increases after a load-more:

```typescript
const pendingScrollRef = useRef<{ height: number; top: number } | null>(null);

useLayoutEffect(() => {
  const pending = pendingScrollRef.current;
  if (!pending || !chatRef.current) return;
  chatRef.current.scrollTop = chatRef.current.scrollHeight - pending.height + pending.top;
  pendingScrollRef.current = null;
}, [messages]);
```

---

### F-2 — Realtime list order drifts

**File:** `useChat.ts` Realtime handler

INSERT prepends to array; UPDATE does not re-sort by `updated_at`. Active session may not bubble to top when another tab sends messages.

**Fix:** After any Realtime event, re-sort:
```typescript
setSessions(prev => [...prev].sort((a, b) =>
  (b.updated_at || b.created_at || '').localeCompare(a.updated_at || a.created_at || '')
));
```

---

### F-3 — Realtime disabled during search never refetches

**File:** `useChat.ts` — `searchQueryRef.current` blocks Realtime while searching (correct), but clearing search only calls `onSearchSessions('')` from Sidebar — verify `fetchSessions('')` resets the ref and refetches. Currently works via `handleSearch` clear button; ensure Escape / empty debounce also resets `searchQueryRef`.

---

### F-4 — Export errors are silent

**File:** `Sidebar.tsx` `handleExportSession`

Non-OK responses fail silently (only `console.error`).

**Fix:** Show toast or `addSystemMessage` on failure; handle 404/403 distinctly.

---

### F-5 — No `isLoadingMore` state

Load-more and initial session load share `isLoadingSession` only for initial load. Sentinel shows static text during load-more (no spinner).

**Fix:** Add `isLoadingMore` in `useChat`; set true/false in `loadMoreMessages`; pass to `ChatArea`.

---

### F-6 — `createdAt` not passed for plan/greeting streaming updates

Plan cards and greeting messages use `as any` casts. Ensure `createdAt` is set on all message shapes for date separators.

---

## 6. Step-by-step fix guide

Recommended order:

| Step | Task | Effort |
|------|------|--------|
| 1 | Restore `web/server.py` | 5 min |
| 2 | Fix `_sb_get_messages` ordering | 15 min |
| 3 | Fix dual-write `if/else` in `chat_history.py` | 20 min |
| 4 | Add `session_belongs_to_user` + wire all session routes | 1–2 hr |
| 5 | Pass `user_id` on `POST /api/sessions` | 10 min |
| 6 | Remove server auto-create default session | 10 min |
| 7 | Frontend: stable message ids, `hasMore` fix, load-more spinner | 1 hr |
| 8 | SQLite: add `message_count` / `updated_at` to list query | 30 min |
| 9 | Run test plan (§8) | 30 min |

### Ownership helper — full API wiring checklist

- [ ] `GET /api/sessions/{id}/messages`
- [ ] `PUT /api/sessions/{id}`
- [ ] `DELETE /api/sessions/{id}`
- [ ] `GET /api/sessions/{id}/export`
- [ ] `DELETE /api/sessions/{id}/files/{filename}`
- [ ] `POST /api/clear?session_id=`
- [ ] `POST /api/chat/stream` — validate `body.session_id` belongs to user
- [ ] `POST /api/upload` — validate `session_id` form field

---

## 7. Improvements roadmap

### UX
- **Archive sessions** — `is_archived` exists in schema but no UI; add archive instead of hard delete
- **Full-text search across messages** — search currently only matches session titles
- **Session preview** — show last message snippet in sidebar (requires API change or denormalized column)
- **Keyboard shortcuts** — `Ctrl+K` search, `Ctrl+N` new chat
- **Optimistic UI** — rename/delete session with rollback on API failure

### Performance
- **Cursor-based pagination** — return `next_cursor` instead of relying on `min(id)` client-side
- **Debounce Realtime** — batch rapid INSERT/UPDATE events before re-sorting list
- **Message virtualisation** — `react-window` for 500+ message threads

### Reliability
- **Stale session guard** — if `activeSessionId` deleted via another tab (Realtime DELETE), auto-select next session
- **Offline queue** — queue outbound messages when backend unreachable; replay on reconnect
- **Conflict resolution** — if brain in-memory history and DB diverge, prefer DB on session load

### Observability
- **Structured logging** — log `session_id`, `user_id`, `message_count` on history operations
- **Metrics** — track p95 latency for `/api/sessions/*/messages`

### Schema
- Add `last_message_at` and `preview` columns on `sessions`, updated by trigger (avoids JOIN on list)
- Add `user_id` column to SQLite `chat_sessions` for future local multi-user

---

## 9. Fixes applied (2026-06-05)

| Issue | Fix |
|-------|-----|
| `web/server.py` deleted | Restored from git |
| New chats missing from sidebar | `POST /api/sessions` now passes `user_id`; orphan sessions (`user_id=''`) included in list + claimed on access |
| History not loading (Supabase) | `_sb_get_messages` now returns **latest** N messages (`ORDER BY id DESC`) |
| Dual-write SQLite + Supabase | Mutations use `if/else` — single backend only |
| Session IDOR | `ensure_session_access()` + `_assert_session_access()` on all session routes |
| Frontend new chat UX | Optimistic sidebar insert + error logging on failed API calls |
| Message keys / pagination | Stable `db-{id}` keys; `hasMore` uses `total` from API |

**Restart required:** `python -m uvicorn web.server:app --host 127.0.0.1 --port 8080` (or `start_web.bat`)

---

## 8. Test plan

### Manual

1. **Restore server** → app loads, login works, sidebar populates
2. **Long session (100+ messages)** → opening session shows *latest* messages at bottom, not oldest
3. **Scroll up** → older batch loads, scroll position stable, date labels correct
4. **Switch sessions** → no flash of wrong transcript; spinner then correct messages
5. **Create / rename / delete** → list updates; Realtime reflects in second browser tab
6. **Export** → downloads `.md` with correct content
7. **Two users** → user A cannot fetch user B's `session_id` (after S-1 fix → 404)

### API (curl)

```bash
# List sessions (requires auth)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/sessions

# Paginate messages
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8080/api/sessions/$SID/messages?limit=50&before_id=100"

# IDOR test (should 404 after fix)
curl -H "Authorization: Bearer $TOKEN_A" \
  "http://127.0.0.1:8080/api/sessions/$USER_B_SESSION_ID/messages"
```

### Automated (suggested)

```python
# tests/test_chat_history.py
async def test_sb_get_messages_returns_latest_not_oldest():
    ...

async def test_session_ownership_denied_for_other_user():
    ...
```

---

## Quick reference — file map

| Concern | Primary file |
|---------|--------------|
| Session list UI | `frontend/src/components/Sidebar/Sidebar.tsx` |
| Transcript + infinite scroll | `frontend/src/components/ChatArea/ChatArea.tsx` |
| Session state machine | `frontend/src/hooks/useChat.ts` |
| REST routes | `web/server.py` |
| DB abstraction | `backend/memory/chat_history.py` |
| RLS policies | `supabase-schema.sql` |
| In-memory turn history | `backend/brain.py` (`conversation_histories`) |

---

*Generated from code audit on branch `main`. Restore `web/server.py` before any production deploy.*
