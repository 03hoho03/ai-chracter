-- 복제 행을 뺀 나머지(시드·마이그레이션 행)의 테이블별 행 수와 내용 md5. 넣기 전후로 같아야 한다.
SET TimeZone = 'UTC';
WITH new_ids AS (SELECT unnest(ARRAY['f27bd660-1bb0-4f23-8212-755d440da457','73cf197c-a8a4-4629-af9b-34029cba4127',
  '4f446070-dc83-416a-b53d-3f43546ac15c','4da67d2d-bb07-44d8-b307-0e790bab03e3','d22ab240-0abb-46bf-b12c-0d638563f0b1']::uuid[]) id)
SELECT 'contents', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM contents t WHERE id NOT IN (SELECT id FROM new_ids)
UNION ALL SELECT 'content_versions', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM content_versions t WHERE content_id NOT IN (SELECT id FROM new_ids)
UNION ALL SELECT 'starting_setups', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM starting_setups t WHERE content_version_id NOT IN (SELECT id FROM new_ids)
UNION ALL SELECT 'media_book_cells', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM media_book_cells t WHERE content_version_id NOT IN (SELECT id FROM new_ids)
UNION ALL SELECT 'assets', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM assets t WHERE id NOT IN (
  SELECT image_asset_id FROM media_book_cells WHERE content_version_id IN (SELECT id FROM new_ids)
  UNION SELECT blurred_asset_id FROM media_book_cells WHERE content_version_id IN (SELECT id FROM new_ids)
  UNION SELECT thumbnail_asset_id FROM story_version_details WHERE content_version_id IN (SELECT id FROM new_ids))
UNION ALL SELECT 'prompt_sets', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM prompt_sets t WHERE id NOT IN (SELECT id FROM new_ids)
UNION ALL SELECT 'prompt_sections', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM prompt_sections t WHERE prompt_set_id NOT IN (SELECT id FROM new_ids)
UNION ALL SELECT 'users', count(*), md5(string_agg(to_jsonb(t)::text, '' ORDER BY id)) FROM users t;
