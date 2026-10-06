\set ON_ERROR_STOP on
\pset pager off
BEGIN READ ONLY;
SHOW transaction_read_only;
SELECT id, lane, version, status, published_at FROM prompt_sets WHERE id='3dd9a35e-dd33-4526-8584-585e057a6058';
SELECT id, lane, version, status, published_at FROM prompt_sets WHERE status='active' OR published_at > now() - interval '2 days' ORDER BY published_at;
\pset format unaligned
SELECT '#### '||channel||'|'||scope||'|'||slot||'|'||variant||'|'||"order"||'|'||md5(body), body FROM prompt_sections WHERE prompt_set_id='3dd9a35e-dd33-4526-8584-585e057a6058' AND channel='stat_judgment' ORDER BY "order", slot, variant;
SELECT '#### stat|'||d.name||'|'||d.entity_id||'|'||d.min_value||'|'||d.max_value||'|'||d.initial_value||'|'||coalesce(d.max_change_per_turn::text,'-')||'|'||d.change_direction||'|'||coalesce(d.per_turn_delta::text,'-')||'|'||d."order", d.description FROM stat_defs d JOIN starting_setups ss ON ss.id=d.starting_setup_id WHERE ss.content_version_id='3895ffe1-e4a3-4b8b-9099-3349287794bc' ORDER BY d."order";
ROLLBACK;
