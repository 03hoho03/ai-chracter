import type { components } from "@ai-character-chat/api-types";

export const SIGNUP_METHOD_LABELS: Record<components["schemas"]["AdminUserDetailResponse"]["signupMethod"], string> = {
  google: "구글",
  email: "이메일",
};

/** `AdminUserActionLogItem.actionType`은 enum이 아니라 자유 문자열이다(user-warn/user-suspend/
 * user-unsuspend/restrict/delete/lift-restriction/reject 등, 작품 직접 조치와 유저 조치가 같은
 * 로그 테이블을 쓴다). 여기 없는 값은 호출부가 원문 그대로 보여준다(Record<string,string> 인덱싱은
 * noUncheckedIndexedAccess로 `string | undefined`라 `??` 폴백이 강제된다). */
export const ACTION_TYPE_LABELS: Record<string, string> = {
  "user-warn": "경고",
  "user-suspend": "정지",
  "user-unsuspend": "정지 해제",
  restrict: "이용제한 부과",
  delete: "삭제",
  "lift-restriction": "이용제한 해제",
  reject: "반려",
  "chat-view": "채팅 열람",
};

export type ChatViewReasonCategory = components["schemas"]["ChatViewReasonCategory"];

/** 신고 사유(5종, entities/report의 REPORT_REASON_LABELS)와는 다른 enum이다 — 채팅 열람은
 * "왜 이 대화를 봐야 했는가"를 남기는 별도 사유 체계다. `pages/chat-messages`(열람 사유 다이얼로그)와
 * `pages/user-detail`(조치 이력 표, AdminActionLog.reason_category에 이 4종이 섞여 들어옴) 둘 다
 * 이 라벨을 쓴다 — pages 간 직접 import는 FSD 역방향이라 여기 entities로 내려 공유한다. */
export const CHAT_VIEW_REASON_CATEGORY_LABELS: Record<ChatViewReasonCategory, string> = {
  "report-investigation": "신고 조사",
  "appeal-review": "이의제기 검토",
  "legal-request": "법적 요청",
  other: "기타",
};

export function isChatViewReasonCategory(value: string): value is ChatViewReasonCategory {
  return value in CHAT_VIEW_REASON_CATEGORY_LABELS;
}

/** 사유가 늘면 `CHAT_VIEW_REASON_CATEGORY_LABELS`(Record)가 컴파일 에러로 잡는다 — 목록·옵션을
 * 손으로 또 적으면 그 강제가 목록에는 걸리지 않아 새 사유가 조용히 빠진다. 그래서 둘 다 키에서
 * 도출한다(entities/report의 REPORT_REASON_VALUES와 동형). */
export const CHAT_VIEW_REASON_CATEGORY_VALUES = Object.keys(CHAT_VIEW_REASON_CATEGORY_LABELS).filter(
  isChatViewReasonCategory,
);

export const CHAT_VIEW_REASON_CATEGORY_OPTIONS = CHAT_VIEW_REASON_CATEGORY_VALUES.map((value) => ({
  value,
  label: CHAT_VIEW_REASON_CATEGORY_LABELS[value],
}));
