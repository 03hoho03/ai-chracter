/** `apps/api/src/api/chat/prompt_builder.py`의 `ALLOWED_PLACEHOLDERS`를 그대로 옮긴 표시용
 * 힌트다. 실제 검증은 게시 시점에 서버가 하므로 이 목록은
 * 어드민이 body를 쓰는 동안 뭘 쓸 수 있는지 미리 보여주는 것뿐이다 — 서버 목록이 바뀌면 이
 * 파일도 함께 옮긴다. 튜플 키(`channel`, `slot`) 대신 `"channel:slot"` 문자열로 키를 만든다. */
const ALLOWED_PLACEHOLDERS: Record<string, readonly string[]> = {
  "system:self_definition": [],
  "system:rule_response_format": [],
  "system:rule_user_agency": [],
  "system:rule_open_turn": [],
  "system:rule_rating": [],
  "system:template_instruction": [],
  "system:priority_tail": [],
  "generation:character_prompt": ["character_prompt"],
  "generation:base_content": ["setting_text", "custom_prompt"],
  "generation:example_dialogues": ["example_lines"],
  "generation:rules": ["rules"],
  "generation:user_goal": ["user_goal"],
  "generation:development_examples": ["example_lines"],
  "generation:prologue": ["prologue"],
  "generation:user_persona": ["user_persona"],
  "generation:memory_note": ["memory_note"],
  "generation:memory_summary": ["memory_summary"],
  "generation:history": ["history_lines"],
  "generation:keyword_notes": ["keyword_note_lines"],
  "generation:situation_notes": ["situation_note_lines"],
  "generation:shortcut_prompt": ["shortcut_prompt"],
  "generation:final_frame": ["user_label", "user_message", "assistant_label"],
  "stat_judgment:stat_defs_intro": ["stat_lines"],
  "stat_judgment:turn_context": ["user_label", "user_message", "assistant_label", "assistant_message"],
  "stat_judgment:judgment_instruction": [],
  "ending_judgment:memory_summary": ["memory_summary"],
  "ending_judgment:history_header": [],
  "ending_judgment:turn_context": ["turn_lines"],
  "ending_judgment:criteria": ["judgment_prompt"],
  "memory_summary:instruction": [],
  "memory_summary:previous_summary": ["previous_summary"],
  "memory_summary:turn_context": ["turn_lines"],
  "image_judgment:image_list_intro": ["image_lines"],
  "image_judgment:turn_context": ["turn_lines"],
  "image_judgment:judgment_instruction": [],
  "publish_filter:intro_instruction": [],
  "publish_filter:image_list": ["image_lines"],
  "publish_filter:verdict_instruction": [],
};

export function allowedPlaceholdersFor(channel: string, slot: string): readonly string[] {
  return ALLOWED_PLACEHOLDERS[`${channel}:${slot}`] ?? [];
}
