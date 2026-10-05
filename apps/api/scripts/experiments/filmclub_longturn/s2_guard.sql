-- 수정판 버전을 만들고 요약 문안 세트를 게시하는 동안 다른 행이 안 바뀌었는지 보는 지문.
-- 복제 작품(모든 버전)의 행과, 기준 시각 :'since' 뒤에 만들어진 프롬프트 세트·대화방은 뺀다.
-- 복제 작품 자체와 복제 v5 는 fingerprint.sql 이 따로 본다. 실행 전후 출력이 같아야 한다.
-- 사용: psql -v since='<UTC 시각>' -f s2_guard.sql
\set ON_ERROR_STOP on
\pset format unaligned
\pset tuples_only on
\pset fieldsep '\t'
SET TimeZone = 'UTC';
BEGIN READ ONLY;
WITH
rv AS (SELECT id FROM content_versions WHERE content_id = 'f27bd660-1bb0-4f23-8212-755d440da457'),
rs AS (SELECT id FROM starting_setups WHERE content_version_id IN (SELECT id FROM rv)),
re AS (SELECT id FROM endings WHERE starting_setup_id IN (SELECT id FROM rs)),
old_sets AS (SELECT id FROM prompt_sets WHERE created_at < :'since'),
old_rooms AS (SELECT id FROM chat_rooms WHERE created_at < :'since')
SELECT 'contents', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM contents t
  WHERE id <> 'f27bd660-1bb0-4f23-8212-755d440da457'
UNION ALL SELECT 'content_versions', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM content_versions t
  WHERE id NOT IN (SELECT id FROM rv)
UNION ALL SELECT 'story_version_details', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY content_version_id))
  FROM story_version_details t WHERE content_version_id NOT IN (SELECT id FROM rv)
UNION ALL SELECT 'starting_setups', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM starting_setups t
  WHERE id NOT IN (SELECT id FROM rs)
UNION ALL SELECT 'stat_defs', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM stat_defs t
  WHERE starting_setup_id NOT IN (SELECT id FROM rs)
UNION ALL SELECT 'endings', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM endings t
  WHERE id NOT IN (SELECT id FROM re)
UNION ALL SELECT 'ending_rule_groups', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM ending_rule_groups t
  WHERE ending_id NOT IN (SELECT id FROM re)
UNION ALL SELECT 'ending_rules', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM ending_rules t
  WHERE ending_id IS NULL OR ending_id NOT IN (SELECT id FROM re)
UNION ALL SELECT 'situation_notes', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM situation_notes t
  WHERE starting_setup_id NOT IN (SELECT id FROM rs)
UNION ALL SELECT 'keyword_notes', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM keyword_notes t
  WHERE content_version_id NOT IN (SELECT id FROM rv)
UNION ALL SELECT 'shortcuts', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM shortcuts t
  WHERE content_version_id NOT IN (SELECT id FROM rv)
UNION ALL SELECT 'media_book_people', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM media_book_people t
  WHERE content_version_id NOT IN (SELECT id FROM rv)
UNION ALL SELECT 'media_book_scenes', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM media_book_scenes t
  WHERE content_version_id NOT IN (SELECT id FROM rv)
UNION ALL SELECT 'media_book_cells', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM media_book_cells t
  WHERE content_version_id NOT IN (SELECT id FROM rv)
UNION ALL SELECT 'assets', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM assets t
UNION ALL SELECT 'prompt_sets', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM prompt_sets t
  WHERE id IN (SELECT id FROM old_sets)
UNION ALL SELECT 'prompt_sections', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM prompt_sections t
  WHERE prompt_set_id IN (SELECT id FROM old_sets)
UNION ALL SELECT 'chat_rooms', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM chat_rooms t
  WHERE id IN (SELECT id FROM old_rooms)
UNION ALL SELECT 'chat_messages', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM chat_messages t
  WHERE chat_room_id IN (SELECT id FROM old_rooms)
UNION ALL SELECT 'users', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM users t;
ROLLBACK;
