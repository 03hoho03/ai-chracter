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
  "user-rate-limit-exempt-on": "레이트리밋 면제",
  "user-rate-limit-exempt-off": "레이트리밋 면제 해제",
  // clover-goal-prompt.md CL-16 — `admin/users.py`가 `body.amount > 0`으로 두 리터럴을 가른다.
  // 🔴 이 `Record<string, string>`은 타입 강제 밖이라 키를 빠뜨려도 컴파일이 통과하고, 그때
  // 조치 이력 표에 영문 액션 타입이 그대로 찍힌다(호출부의 `?? log.actionType` 폴백).
  // 값은 BE 리터럴과 글자 단위로 대조했다.
  "user-clover-grant": "클로버 지급",
  "user-clover-revoke": "클로버 회수",
  restrict: "이용제한 부과",
  delete: "삭제",
  "lift-restriction": "이용제한 해제",
  reject: "반려",
  "chat-view": "채팅 열람",
  "image-view": "이미지 열람",
};

/** 원장 행의 `kind` — `core/clover.py`의 `CloverKind` 10종이다(clover-page-goal-prompt.md CE-10이
 * `mission_grant`·`expire_burn` 2종을 더했다). `AdminCloverLedgerItem.kind`가 `Literal`이 아니라
 * `string`인 것은 의도다(모델이 `Text`라 값을 늘릴 때 마이그레이션도 FE 코드젠도 깨지지 않게 한
 * 것). 그래서 여기도 `Record<string, string>`이고, 모르는 값은 호출부가 원문 그대로 보여준다 —
 * ACTION_TYPE_LABELS와 같은 관례이자 같은 약점이다. `apps/web`의 동명 맵
 * (`entities/clover/model/cloverKindLabel.ts`)과 별도 번들이라 공유하지 않는 것이 결정이고
 * (CE-23), 문구는 그쪽과 맞춰 뒀다. */
export const CLOVER_KIND_LABELS: Record<string, string> = {
  admin_grant: "운영자 지급",
  admin_revoke: "운영자 회수",
  attendance_grant: "출석 지급",
  mission_grant: "미션 보상",
  chat_spend: "채팅 사용",
  image_spend: "이미지 사용",
  chat_refund: "채팅 환불",
  image_refund: "이미지 환불",
  expire_burn: "유효기간 소멸",
  withdrawal_burn: "탈퇴 소멸",
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
