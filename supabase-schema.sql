-- ──────────────────────────────────────────────
-- FRIDAY Supabase Schema — safe to run repeatedly
-- ──────────────────────────────────────────────

-- 1. SESSIONS
CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    user_id        TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    message_count  INTEGER DEFAULT 0,
    is_archived    BOOLEAN DEFAULT FALSE
);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT '';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS message_count INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC);

-- 2. MESSAGES
CREATE TABLE IF NOT EXISTS messages (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS session_id TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS role TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS content TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

-- 3. SESSION FILES
CREATE TABLE IF NOT EXISTS session_files (
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (session_id, filename)
);
ALTER TABLE session_files ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMPTZ DEFAULT NOW();

-- 4. ROW LEVEL SECURITY
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_files ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN DROP POLICY IF EXISTS sessions_select_own ON sessions; CREATE POLICY sessions_select_own ON sessions FOR SELECT USING (user_id = auth.uid()::text); END $$;
DO $$ BEGIN DROP POLICY IF EXISTS sessions_insert_own ON sessions; CREATE POLICY sessions_insert_own ON sessions FOR INSERT WITH CHECK (user_id = auth.uid()::text); END $$;
DO $$ BEGIN DROP POLICY IF EXISTS sessions_update_own ON sessions; CREATE POLICY sessions_update_own ON sessions FOR UPDATE USING (user_id = auth.uid()::text); END $$;
DO $$ BEGIN DROP POLICY IF EXISTS sessions_delete_own ON sessions; CREATE POLICY sessions_delete_own ON sessions FOR DELETE USING (user_id = auth.uid()::text); END $$;

DO $$ BEGIN DROP POLICY IF EXISTS messages_select_own ON messages; CREATE POLICY messages_select_own ON messages FOR SELECT USING (EXISTS (SELECT 1 FROM sessions WHERE sessions.id = messages.session_id AND sessions.user_id = auth.uid()::text)); END $$;
DO $$ BEGIN DROP POLICY IF EXISTS messages_insert_own ON messages; CREATE POLICY messages_insert_own ON messages FOR INSERT WITH CHECK (EXISTS (SELECT 1 FROM sessions WHERE sessions.id = messages.session_id AND sessions.user_id = auth.uid()::text)); END $$;
DO $$ BEGIN DROP POLICY IF EXISTS messages_delete_own ON messages; CREATE POLICY messages_delete_own ON messages FOR DELETE USING (EXISTS (SELECT 1 FROM sessions WHERE sessions.id = messages.session_id AND sessions.user_id = auth.uid()::text)); END $$;

DO $$ BEGIN DROP POLICY IF EXISTS session_files_select_own ON session_files; CREATE POLICY session_files_select_own ON session_files FOR SELECT USING (EXISTS (SELECT 1 FROM sessions WHERE sessions.id = session_files.session_id AND sessions.user_id = auth.uid()::text)); END $$;
DO $$ BEGIN DROP POLICY IF EXISTS session_files_insert_own ON session_files; CREATE POLICY session_files_insert_own ON session_files FOR INSERT WITH CHECK (EXISTS (SELECT 1 FROM sessions WHERE sessions.id = session_files.session_id AND sessions.user_id = auth.uid()::text)); END $$;
DO $$ BEGIN DROP POLICY IF EXISTS session_files_delete_own ON session_files; CREATE POLICY session_files_delete_own ON session_files FOR DELETE USING (EXISTS (SELECT 1 FROM sessions WHERE sessions.id = session_files.session_id AND sessions.user_id = auth.uid()::text)); END $$;

-- 5. REALTIME PUBLICATION
ALTER PUBLICATION supabase_realtime ADD TABLE sessions;

-- 6. MESSAGE_COUNT TRIGGER
CREATE OR REPLACE FUNCTION update_session_message_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE sessions SET message_count = message_count + 1, updated_at = NOW() WHERE id = NEW.session_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE sessions SET message_count = GREATEST(message_count - 1, 0), updated_at = NOW() WHERE id = OLD.session_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
DROP TRIGGER IF EXISTS trg_update_session_message_count ON messages;
CREATE TRIGGER trg_update_session_message_count
AFTER INSERT OR DELETE ON messages
FOR EACH ROW EXECUTE FUNCTION update_session_message_count();
