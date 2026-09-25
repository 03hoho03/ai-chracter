import type { components } from "@ai-character-chat/api-types";

export const SIGNUP_METHOD_LABELS: Record<components["schemas"]["AdminUserDetailResponse"]["signupMethod"], string> = {
  google: "구글",
  email: "이메일",
};

/** BE `AdminActionType`(`db/models/moderation.py`의 `Literal` 19종)이 코드젠으로 넘어온 유니언이다. */
type AdminActionType = components["schemas"]["AdminUserActionLogItem"]["actionType"];

/** `satisfies Record<AdminActionType, string>`이라 BE에 조치 종류가 늘면 여기서 컴파일이 깨지고, 목록에
 * 없는 키(예전의 `restrict`·`reject` 같은 데드 키)는 초과 속성으로 거부된다 — 그래서 호출부는 원문
 * 폴백 없이 인덱싱한다. 조치 이력 표(`pages/user-detail`)는 대상 유저·작품이 있는 로그만 보여 주므로
 * 대상이 없는 운영 조치 5종(문의 답변·약관·공지·프롬프트 세트)은 실제로는 그 표에 나오지 않는다 — 그래도
 * 타입이 19종 전부를 요구하므로 라벨을 둔다. `content-*` 3종의 문구는 작품 상세의 조치 버튼·확인
 * 모달(`ContentActionPanel`·`ContentActionConfirmModal`)과 같은 말이고, 대상은 같은 행의 "대상 작품"
 * 칸이 보여 주므로 "작품"을 덧붙이지 않는다. */
export const ACTION_TYPE_LABELS = {
  "user-warn": "경고",
  "user-suspend": "정지",
  "user-unsuspend": "정지 해제",
  "user-rate-limit-exempt-on": "레이트리밋 면제",
  "user-rate-limit-exempt-off": "레이트리밋 면제 해제",
  // `admin/users.py`가 `body.amount > 0`으로 두 리터럴을 가른다.
  "user-clover-grant": "클로버 지급",
  "user-clover-revoke": "클로버 회수",
  "content-restrict": "이용제한 부과",
  "content-delete": "삭제",
  "content-lift": "이용제한 해제",
  // 문구는 신고 목록의 "반려"·이의제기 처리 버튼의 "인용"과 같은 말이다.
  "report-reject": "신고 반려",
  "appeal-accept": "이의제기 인용",
  "chat-view": "채팅 열람",
  "image-view": "이미지 열람",
  "inquiry-reply": "문의 답변",
  "legal-publish": "약관·정책 게시",
  "notice-publish": "공지 게시",
  "notice-unpublish": "공지 숨김",
  "prompt-set-publish": "프롬프트 세트 게시",
} satisfies Record<AdminActionType, string>;

/** 원장 행의 `kind` — `core/clover.py`의 `CloverKind` 10종이다(`mission_grant`·`expire_burn`
 * 2종은 나중에 더해졌다). `AdminCloverLedgerItem.kind`가 `Literal`이 아니라
 * `string`인 것은 의도다(모델이 `Text`라 값을 늘릴 때 마이그레이션도 FE 코드젠도 깨지지 않게 한
 * 것). 그래서 여기는 `Record<string, string>`이고, 모르는 값은 호출부가 원문 그대로 보여준다 —
 * 키를 빠뜨려도 컴파일이 못 잡는다(유니언으로 좁혀 강제하는 ACTION_TYPE_LABELS와 다르다).
 * `apps/web`의 동명 맵(`entities/clover/model/cloverKindLabel.ts`)과 별도 번들이라 공유하지 않는 것이 결정이고,
 * 문구는 그쪽과 맞춰 뒀다. */
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
