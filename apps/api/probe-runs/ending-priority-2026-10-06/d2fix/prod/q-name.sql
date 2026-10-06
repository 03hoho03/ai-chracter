\set ON_ERROR_STOP on
\pset pager off
BEGIN READ ONLY;
SHOW transaction_read_only;
SELECT r.persona_id, p.name AS persona_name FROM chat_rooms r LEFT JOIN user_personas p ON p.id=r.persona_id WHERE r.id='b3bdf6d4-afee-4d01-8576-a07fcf4ccd48';
SELECT content_version_id, quote_literal(default_user_name) FROM story_version_details WHERE content_version_id='3895ffe1-e4a3-4b8b-9099-3349287794bc';
ROLLBACK;
