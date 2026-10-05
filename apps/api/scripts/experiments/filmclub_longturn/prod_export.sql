-- 운영 조감독 발행본 v5 와 활성 프롬프트 세트 3개를 테이블별 JSON 한 줄씩으로 내보낸다.
-- 운영에서는 읽기만 한다: 접속 세션을 default_transaction_read_only=on 으로 열고(PGOPTIONS),
-- 이 파일도 BEGIN READ ONLY … ROLLBACK 으로 감싼다. users 행은 내보내지 않는다.
-- 출력 한 줄 = "<태그>\t<JSON>". JSON 은 줄바꿈을 이스케이프하므로 한 행이 한 줄이다.
\set ON_ERROR_STOP on
\pset format unaligned
\pset tuples_only on
\pset fieldsep '\t'
\pset pager off
SET TimeZone = 'UTC';
BEGIN READ ONLY;

SELECT 'check', json_build_object(
  'default_transaction_read_only', current_setting('default_transaction_read_only'),
  'transaction_read_only', current_setting('transaction_read_only'),
  'alembic_version', (SELECT version_num FROM alembic_version),
  'now', now(),
  'content', (SELECT json_build_object(
      'current_published_version_id', current_published_version_id,
      'has_unpublished_changes', has_unpublished_changes,
      'visibility', visibility, 'moderation_status', moderation_status,
      'restricted_by_suspension', restricted_by_suspension)
    FROM contents WHERE id = 'f27bd660-1bb0-4f23-8212-755d440da457'),
  'versions', (SELECT json_agg(json_build_object('id', id, 'version_number', version_number,
      'published_at', published_at) ORDER BY created_at)
    FROM content_versions WHERE content_id = 'f27bd660-1bb0-4f23-8212-755d440da457'),
  'active_sets', (SELECT json_object_agg(lane, json_build_object('id', id, 'version', version,
      'published_at', published_at))
    FROM (SELECT DISTINCT ON (lane) lane, id, version, published_at FROM prompt_sets
          WHERE status = 'published' ORDER BY lane, published_at DESC) s)
);

-- 아래 버전·세트 id 는 위 check 줄로 현행값과 같음을 확인한 뒤에만 격리 DB 에 넣는다.
SELECT 'contents', coalesce(json_agg(t ORDER BY t.id), '[]') FROM contents t
  WHERE t.id = 'f27bd660-1bb0-4f23-8212-755d440da457';
SELECT 'genre_name', coalesce(json_agg(json_build_object('genre_id', g.id, 'name', g.name)), '[]')
  FROM genres g JOIN contents c ON c.genre_id = g.id WHERE c.id = 'f27bd660-1bb0-4f23-8212-755d440da457';
SELECT 'content_versions', coalesce(json_agg(t ORDER BY t.id), '[]') FROM content_versions t
  WHERE t.id = '73cf197c-a8a4-4629-af9b-34029cba4127';
SELECT 'story_version_details', coalesce(json_agg(t), '[]') FROM story_version_details t
  WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127';
SELECT 'starting_setups', coalesce(json_agg(t ORDER BY t."order", t.id), '[]') FROM starting_setups t
  WHERE t.id IN (SELECT id FROM starting_setups WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127');
SELECT 'stat_defs', coalesce(json_agg(t ORDER BY t."order", t.id), '[]') FROM stat_defs t
  WHERE t.starting_setup_id IN (SELECT id FROM starting_setups WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127');
SELECT 'endings', coalesce(json_agg(t ORDER BY t."order", t.id), '[]') FROM endings t
  WHERE t.id IN (SELECT id FROM endings WHERE starting_setup_id IN (SELECT id FROM starting_setups WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'));
SELECT 'ending_rule_groups', coalesce(json_agg(t ORDER BY t."order", t.id), '[]') FROM ending_rule_groups t
  WHERE t.id IN (SELECT id FROM ending_rule_groups WHERE ending_id IN (SELECT id FROM endings WHERE starting_setup_id IN (SELECT id FROM starting_setups WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127')));
SELECT 'ending_rules', coalesce(json_agg(t ORDER BY t.ending_id, t."order", t.id), '[]') FROM ending_rules t
  WHERE t.ending_id IN (SELECT id FROM endings WHERE starting_setup_id IN (SELECT id FROM starting_setups WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127')) OR t.rule_group_id IN (SELECT id FROM ending_rule_groups WHERE ending_id IN (SELECT id FROM endings WHERE starting_setup_id IN (SELECT id FROM starting_setups WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127')));
SELECT 'keyword_notes', coalesce(json_agg(t ORDER BY t."order", t.id), '[]') FROM keyword_notes t
  WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127';
SELECT 'shortcuts', coalesce(json_agg(t ORDER BY t.id), '[]') FROM shortcuts t
  WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127';
SELECT 'situation_notes', coalesce(json_agg(t ORDER BY t."order", t.id), '[]') FROM situation_notes t
  WHERE t.starting_setup_id IN (SELECT id FROM starting_setups WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127');
SELECT 'media_book_people', coalesce(json_agg(t ORDER BY t."order", t.id), '[]') FROM media_book_people t
  WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127';
SELECT 'media_book_scenes', coalesce(json_agg(t ORDER BY t."order", t.id), '[]') FROM media_book_scenes t
  WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127';
SELECT 'media_book_cells', coalesce(json_agg(t ORDER BY t.id), '[]') FROM media_book_cells t
  WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127';
-- 버전·세트 id 는 위 check 줄로 현행값과 같음을 확인한 뒤에만 격리 DB 에 넣는다.
-- 자산은 이 버전이 가리키는 것만: 대표 이미지 + 칸 원본 + 칸 블러.
SELECT 'assets', coalesce(json_agg(t ORDER BY t.id), '[]') FROM assets t WHERE t.id IN (
  SELECT thumbnail_asset_id FROM story_version_details WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'
  UNION SELECT image_asset_id FROM media_book_cells WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'
  UNION SELECT blurred_asset_id FROM media_book_cells WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127');
SELECT 'prompt_sets', coalesce(json_agg(t ORDER BY t.lane), '[]') FROM prompt_sets t WHERE t.id IN (
  '4f446070-dc83-416a-b53d-3f43546ac15c', '4da67d2d-bb07-44d8-b307-0e790bab03e3', 'd22ab240-0abb-46bf-b12c-0d638563f0b1');
SELECT 'prompt_sections', coalesce(json_agg(t ORDER BY t.prompt_set_id, t.channel, t."order", t.variant, t.id), '[]')
  FROM prompt_sections t WHERE t.prompt_set_id IN (
  '4f446070-dc83-416a-b53d-3f43546ac15c', '4da67d2d-bb07-44d8-b307-0e790bab03e3', 'd22ab240-0abb-46bf-b12c-0d638563f0b1');

ROLLBACK;
SELECT 'after', json_build_object('default_transaction_read_only', current_setting('default_transaction_read_only'));
