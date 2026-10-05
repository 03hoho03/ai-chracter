-- 복제 충실도 대조용 지문: 조감독 v5 와 프롬프트 세트 3개의 모든 행·모든 열을 (테이블, 행 키, 열, md5(값)) 로 뽑는다.
-- 운영과 격리 DB 에 이 파일을 글자 그대로 똑같이 돌리고 두 출력을 기계적으로 비교한다.
-- 값은 jsonb_each_text 의 텍스트(문자열 열은 원문 그대로)를 md5 한다. 시각 열이 세션 시간대에 따라
-- 다르게 찍히지 않도록 TimeZone 을 UTC 로 고정한다. 읽기 전용 트랜잭션 안에서만 돈다.
\set ON_ERROR_STOP on
\pset format unaligned
\pset tuples_only on
\pset fieldsep '\t'
\pset pager off
SET TimeZone = 'UTC';
BEGIN READ ONLY;
SELECT 'fp_meta', current_setting('transaction_read_only'), current_setting('TimeZone'), current_setting('server_version');
WITH
ss AS (SELECT id FROM starting_setups WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'),
en AS (SELECT id FROM endings WHERE starting_setup_id IN (SELECT id FROM ss)),
gr AS (SELECT id FROM ending_rule_groups WHERE ending_id IN (SELECT id FROM en)),
sets AS (SELECT unnest(ARRAY['7e6b6119-bc9c-4746-aecb-18cd5ee67c4f', '3b80a001-83b1-4828-990c-9a94d3bcf61f',
                             'db13f4b4-8ac7-4351-87df-030d24ed5d5b']::uuid[]) AS id),
r AS (
  SELECT 'contents' AS tbl, t.id::text AS rid, to_jsonb(t) AS j FROM contents t WHERE t.id = 'f27bd660-1bb0-4f23-8212-755d440da457'
  -- 장르는 격리 DB 의 같은 이름 장르로 바뀌므로 id 대신 이름을 대조한다.
  UNION ALL SELECT 'contents.genre', c.id::text, jsonb_build_object('genre_name', g.name)
    FROM contents c JOIN genres g ON g.id = c.genre_id WHERE c.id = 'f27bd660-1bb0-4f23-8212-755d440da457'
  UNION ALL SELECT 'content_versions', t.id::text, to_jsonb(t) FROM content_versions t WHERE t.id = '73cf197c-a8a4-4629-af9b-34029cba4127'
  UNION ALL SELECT 'story_version_details', t.content_version_id::text, to_jsonb(t) FROM story_version_details t
    WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'
  UNION ALL SELECT 'starting_setups', t.id::text, to_jsonb(t) FROM starting_setups t WHERE t.id IN (SELECT id FROM ss)
  UNION ALL SELECT 'stat_defs', t.id::text, to_jsonb(t) FROM stat_defs t WHERE t.starting_setup_id IN (SELECT id FROM ss)
  UNION ALL SELECT 'endings', t.id::text, to_jsonb(t) FROM endings t WHERE t.id IN (SELECT id FROM en)
  UNION ALL SELECT 'ending_rule_groups', t.id::text, to_jsonb(t) FROM ending_rule_groups t WHERE t.id IN (SELECT id FROM gr)
  UNION ALL SELECT 'ending_rules', t.id::text, to_jsonb(t) FROM ending_rules t
    WHERE t.ending_id IN (SELECT id FROM en) OR t.rule_group_id IN (SELECT id FROM gr)
  UNION ALL SELECT 'keyword_notes', t.id::text, to_jsonb(t) FROM keyword_notes t WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'
  UNION ALL SELECT 'shortcuts', t.id::text, to_jsonb(t) FROM shortcuts t WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'
  UNION ALL SELECT 'situation_notes', t.id::text, to_jsonb(t) FROM situation_notes t WHERE t.starting_setup_id IN (SELECT id FROM ss)
  UNION ALL SELECT 'media_book_people', t.id::text, to_jsonb(t) FROM media_book_people t WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'
  UNION ALL SELECT 'media_book_scenes', t.id::text, to_jsonb(t) FROM media_book_scenes t WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'
  UNION ALL SELECT 'media_book_cells', t.id::text, to_jsonb(t) FROM media_book_cells t WHERE t.content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'
  UNION ALL SELECT 'assets', t.id::text, to_jsonb(t) FROM assets t WHERE t.id IN (
    SELECT thumbnail_asset_id FROM story_version_details WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'
    UNION SELECT image_asset_id FROM media_book_cells WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127'
    UNION SELECT blurred_asset_id FROM media_book_cells WHERE content_version_id = '73cf197c-a8a4-4629-af9b-34029cba4127')
  UNION ALL SELECT 'prompt_sets', t.id::text, to_jsonb(t) FROM prompt_sets t WHERE t.id IN (SELECT id FROM sets)
  UNION ALL SELECT 'prompt_sections', t.id::text, to_jsonb(t) FROM prompt_sections t WHERE t.prompt_set_id IN (SELECT id FROM sets)
)
SELECT 'fp', r.tbl, r.rid, e.key, coalesce(md5(e.value), '<null>')
FROM r, jsonb_each_text(r.j) AS e(key, value)
ORDER BY r.tbl, r.rid, e.key;
ROLLBACK;
