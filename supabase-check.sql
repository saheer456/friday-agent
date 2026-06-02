-- Check if tables exist and their columns
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('sessions', 'messages', 'session_files')
ORDER BY table_name, ordinal_position;

-- Check existing RLS policies
SELECT tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies
WHERE tablename IN ('sessions', 'messages', 'session_files')
ORDER BY tablename, policyname;

-- Check if Realtime publication includes these tables
SELECT DISTINCT tablename
FROM pg_publication_tables
WHERE pubname = 'supabase_realtime'
  AND tablename IN ('sessions', 'messages', 'session_files');
