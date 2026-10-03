import { isApiError } from "@/shared/api/client";

import { isSituationNoteStatNotFoundError, SITUATION_NOTE_STAT_NOT_FOUND_MESSAGE } from "./situationNoteErrors";

// 서버가 칸 자리 경합에 돌려주는 409 의 `detail.code`. 응답에 실리는 실제 식별자다.
const POSITION_TAKEN_CODE = "MEDIA_BOOK_CELL_POSITION_TAKEN";
// 엔딩 규칙이 같은 시작설정에 없는 스탯을 가리킬 때 서버가 초안 저장에 돌려주는 422 의 `detail.code`. 응답에 실리는 실제 식별자다.
const ENDING_RULE_STAT_NOT_FOUND_CODE = "ENDING_RULE_STAT_NOT_FOUND";

/**
 * 다른 창(또는 기기)이 같은 인물 × 장면 자리에 먼저 새 칸을 저장해, 이 화면의 저장이 거절된 경우의 안내. 이 화면의
 * 폼에는 여전히 그 자리의 다른 칸이 들어 있어 기다려도 풀리지 않는다 — 새로고침해 저장된 쪽을 불러와야 한다.
 */
export const MEDIA_BOOK_POSITION_TAKEN_MESSAGE =
  "다른 창에서 같은 미디어 북 칸에 먼저 이미지를 넣어 저장이 멈췄어요. 새로고침하면 저장된 내용을 불러와요(이 창에서 그 뒤에 고친 내용은 사라져요).";

export function isMediaBookPositionTakenError(error: unknown): boolean {
  if (!isApiError(error) || error.status !== 409) return false;
  return typeof error.detail === "object" && error.detail.code === POSITION_TAKEN_CODE;
}

/**
 * 서버가 저장 본문을 검증에서 거절한(422) 경우의 안내. 같은 값으로는 몇 번을 다시 보내도 거절되므로 기다리라고
 * 하지 않고 줄이라고 말한다. 422 본문에서는 어느 항목이 넘쳤는지 화면이 가려낼 수 없어(필드 오류가 이름만 남고
 * 위치는 버려진다) 항목을 짚지 않는다.
 */
export const STORY_SAVE_LIMIT_MESSAGE =
  "글자 수나 개수 제한을 넘은 항목이 있어 저장하지 못했어요. 입력한 내용은 그대로 있으니 긴 글이나 많이 추가한 항목을 줄여주세요.";

/**
 * 엔딩 규칙이 지워진 스탯을 가리켜 저장이 거절된 경우의 안내. 같은 422 라도 글자 수 문제가 아니므로 줄이라고 하지 않고
 * 고칠 자리(엔딩 탭)를 짚는다. 이 화면에서 스탯을 지우면 그 규칙도 함께 지워지므로, 이 문구는 그 처리 전에 저장된 초안이나
 * 다른 기기에서 고친 초안에서만 보인다. 그런 규칙 줄은 스탯 칸에 '지워진 스탯'이
 * 보이므로 문구도 그 이름으로 가리킨다.
 */
export const ENDING_RULE_STAT_NOT_FOUND_MESSAGE =
  "지워진 스탯을 쓰는 엔딩 조건이 있어 저장하지 못했어요. 입력한 내용은 그대로 있으니 엔딩 탭에서 ‘지워진 스탯’ 조건을 지우거나 다른 스탯으로 바꿔주세요.";

export function isEndingRuleStatNotFoundError(error: unknown): boolean {
  if (!isApiError(error) || error.status !== 422) return false;
  return typeof error.detail === "object" && error.detail.code === ENDING_RULE_STAT_NOT_FOUND_CODE;
}

/** 스토리 저장 실패 토스트 문구 — 자동저장과 임시저장 버튼이 함께 쓴다. 따로 안내할 이유가 없으면 undefined(호출부의 기본 문구). */
export function storyAutosaveErrorMessage(error: unknown): string | undefined {
  if (isMediaBookPositionTakenError(error)) return MEDIA_BOOK_POSITION_TAKEN_MESSAGE;
  if (isEndingRuleStatNotFoundError(error)) return ENDING_RULE_STAT_NOT_FOUND_MESSAGE;
  if (isSituationNoteStatNotFoundError(error)) return SITUATION_NOTE_STAT_NOT_FOUND_MESSAGE;
  if (isApiError(error) && error.status === 422) return STORY_SAVE_LIMIT_MESSAGE;
  return undefined;
}
