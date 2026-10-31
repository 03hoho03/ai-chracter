import type { components } from "@ai-character-chat/api-types";

/** BE 의 호출 위치 목록이 코드젠으로 넘어온 유니언이다(배정 표 응답의 호출 칸이 이 타입을 쓴다). */
export type LlmCallSite = components["schemas"]["AdminPromptRouteCall"]["callSite"];

/** 운영자가 읽는 호출 위치 이름. `satisfies Record<LlmCallSite, string>` 이라 BE 에 호출 위치가 늘면 api-types 를 다시 만드는
 * 순간 여기서 컴파일이 깨진다 — 문자열 키 사전으로 두었을 때는 새 호출 위치가 사용량 화면에서 조용히 원문으로만 보였다. */
export const CALL_SITE_LABELS = {
  chat_generate: "채팅 생성",
  chat_stat_judgment: "채팅 스탯 판정",
  chat_ending_judgment: "채팅 엔딩 판정",
  chat_situational_image: "상황 이미지 판정",
  chat_media_book_image: "미디어 북 칸 판정",
  chat_memory_summary: "기억 요약",
  chat_memory_episode: "장면 기억 추출",
  chat_memory_fact: "사실 기억 추출",
  chat_memory_impression: "기억 인상",
  chat_scene_judgment: "채팅 장면 헤더 판정",
  preview_generate: "미리보기 생성",
  preview_stat_judgment: "미리보기 스탯 판정",
  preview_ending_judgment: "미리보기 엔딩 판정",
  preview_media_book_image: "미리보기 미디어 북 판정",
  preview_scene_judgment: "미리보기 장면 헤더 판정",
  publish_filter_character: "발행 심사(캐릭터)",
  publish_filter_story: "발행 심사(스토리)",
  seed_story_generate: "시드 스토리 생성",
  seed_similarity_review: "시드 유사도 심사",
  novelize_boundary: "소설 장 경계 제안",
  // 장 생성과 재생성이 같은 호출 위치를 쓴다.
  novelize_chapter: "소설 장 생성",
  // 한 범위 문단 수정과 여러 문단 수정이 같은 호출 위치를 쓴다(묶음 재검사만 따로).
  novelize_revise: "소설 문단 수정",
  novelize_revise_recheck: "소설 묶음 재검사",
  novelize_outline: "소설 전체 구성안",
  novelize_episode_outline: "소설 장면 구성안",
  novel_publish_screen: "노벨 공개 심사(텍스트)",
  novel_illustration_screen: "노벨 공개 심사(삽화)",
  replay_generate: "리플레이 생성(측정)",
  novel_bible_extract_events: "정본 기억 사건 추출",
  novel_bible_extract_facts: "정본 기억 사실 추출",
  novel_bible_extract_knowledge: "정본 기억 지식 추출",
  novel_bible_judge: "정본 기억 모호 판정",
} satisfies Record<LlmCallSite, string>;

export function isLlmCallSite(value: string): value is LlmCallSite {
  return value in CALL_SITE_LABELS;
}

/** 사용량 기록의 호출 위치는 DB 에 남은 옛 값일 수 있는 문자열이라, 모르는 값이면 없음을 돌려 호출부가 원문을 보이게 한다. */
export function callSiteLabel(value: string): string | undefined {
  return isLlmCallSite(value) ? CALL_SITE_LABELS[value] : undefined;
}
