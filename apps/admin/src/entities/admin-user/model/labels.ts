import type { components } from "@ai-character-chat/api-types";

export const SIGNUP_METHOD_LABELS: Record<components["schemas"]["AdminUserDetailResponse"]["signupMethod"], string> = {
  kakao: "카카오",
  google: "구글",
  email: "이메일",
};

/** BE `AdminActionType`이 코드젠으로 넘어온 유니언이다. */
type AdminActionType = components["schemas"]["AdminUserActionLogItem"]["actionType"];

/** `satisfies Record<AdminActionType, string>`이라 BE에 조치 종류가 늘면 여기서 컴파일이 깨지고, 목록에
 * 없는 키(예전의 `restrict`·`reject` 같은 데드 키)는 초과 속성으로 거부된다 — 그래서 호출부는 원문
 * 폴백 없이 인덱싱한다. 조치 이력 표(`pages/user-detail`)는 대상 유저·작품이 있는 로그만 보여 주므로
 * 대상이 없는 운영 조치 5종(문의 답변·약관·공지·프롬프트 세트)은 실제로는 그 표에 나오지 않는다 — 그래도
 * 타입이 모든 조치의 라벨을 요구한다. `content-*` 3종의 문구는 작품 상세의 조치 버튼·확인
 * 모달(`ContentActionPanel`·`ContentActionConfirmModal`)과 같은 말이고, 대상은 같은 행의 "대상 작품"
 * 칸이 보여 주므로 "작품"을 덧붙이지 않는다. */
export const ACTION_TYPE_LABELS = {
  "user-warn": "경고",
  "user-suspend": "정지",
  "user-unsuspend": "정지 해제",
  "user-rate-limit-exempt-on": "레이트리밋 면제",
  "user-rate-limit-exempt-off": "레이트리밋 면제 해제",
  "user-beta-on": "베타 지정",
  "user-beta-off": "베타 해제",
  // `admin/users.py`가 `body.amount > 0`으로 두 리터럴을 가른다.
  "user-clover-grant": "클로버 지급",
  "user-clover-revoke": "클로버 회수",
  "user-creator-payout-approve": "크리에이터 정산 승인",
  "user-creator-payout-reject": "크리에이터 정산 거절",
  "user-creator-payout-revoke": "크리에이터 정산 승인 취소",
  "user-payment-refund": "결제 환불",
  "user-novelize-on": "소설화 허용",
  "user-novelize-off": "소설화 회수",
  "user-chat-premium-models-on": "채팅 상위 모델 허용",
  "user-chat-premium-models-off": "채팅 상위 모델 회수",
  "user-novelize-premium-models-on": "소설화 상위 모델 허용",
  "user-novelize-premium-models-off": "소설화 상위 모델 회수",
  "content-restrict": "이용제한 부과",
  "content-delete": "삭제",
  "content-lift": "이용제한 해제",
  // 문구는 신고 목록의 "반려"·이의제기 처리 버튼의 "인용"과 같은 말이다.
  "report-reject": "신고 반려",
  "comment-hide": "댓글 운영 숨김",
  "comment-restore": "댓글 운영 숨김 해제",
  "comment-report-reject": "댓글 신고 반려",
  // 채팅 응답 신고 처리 로그는 대상 유저가 **신고를 낸 사람**이다(방이 지워져도 누구의 신고였는지
  // 남기려고). 그래서 신고자의 조치 이력 표에 이 행이 뜨는데, "반려"만 적으면 그 유저가 제재받은
  // 것처럼 읽힌다 — 이 유저가 낸 신고를 처리했다는 뜻이 문구에서 바로 읽히게 한다.
  "chat-report-resolve": "본인이 낸 채팅 신고 처리완료",
  "chat-report-reject": "본인이 낸 채팅 신고 반려",
  "appeal-accept": "이의제기 인용",
  "chat-view": "채팅 열람",
  "image-view": "이미지 열람",
  // 작가의 조치 이력 표는 서버가 이 둘을 빼고 준다(제재 기록을 밀어내지 않게) — 타입이 모든 조치의 라벨을 요구해
  // 둔다. 문구는 작품 상세의 지정·해제 버튼과 같은 말이다.
  "home-curation-set": "홈 큐레이션 지정",
  "home-curation-clear": "홈 큐레이션 해제",
  "home-novel-curation-set": "홈 노벨 지정",
  "home-novel-curation-clear": "홈 노벨 해제",
  // 노벨 조치의 대상 유저는 게시자, 노벨 댓글 조치의 대상 유저는 댓글 작성자다(그 회원의 조치 이력 표에 뜬다).
  "novel-restrict": "노벨 이용제한",
  "novel-lift": "노벨 이용제한 해제",
  "novel-report-reject": "노벨 신고 반려",
  "novel-comment-hide": "노벨 댓글 운영 숨김",
  "novel-comment-restore": "노벨 댓글 운영 숨김 해제",
  "novel-comment-delete": "노벨 댓글 운영 삭제",
  "novel-comment-report-reject": "노벨 댓글 신고 반려",
  "inquiry-reply": "문의 답변",
  "legal-publish": "약관·정책 게시",
  "notice-publish": "공지 게시",
  "notice-unpublish": "공지 숨김",
  "prompt-set-publish": "프롬프트 세트 게시",
} satisfies Record<AdminActionType, string>;

/** 원장 행의 `kind` — `core/clover.py`의 `CloverKind` 18종이다(`mission_grant`·`expire_burn`
 * 2종과 소설화의 `novelize_spend`·`novelize_refund` 2종, 결제의 `purchase_*` 4종, 노벨의 `novel_read_spend`·`novel_read_refund` 2종은 나중에 더해졌다). `AdminCloverLedgerItem.kind`가 `Literal`이 아니라
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
  novelize_spend: "소설 사용",
  chat_refund: "채팅 환불",
  image_refund: "이미지 환불",
  novelize_refund: "소설 환불",
  expire_burn: "유효기간 소멸",
  withdrawal_burn: "탈퇴 소멸",
  purchase_paid: "클로버 구매",
  purchase_bonus: "구매 보너스",
  purchase_revoke: "구매 취소 회수",
  purchase_restore: "구매 회수 복원",
  novel_read_spend: "노벨 소장",
  novel_read_refund: "노벨 삭제 환급",
};

type PaymentStatus = components["schemas"]["AdminUserPaymentItem"]["status"];

/** 주문 상태 — BE `PaymentStatus` 유니언이라 `satisfies`가 빠진 키·데드 키를 컴파일에서 잡는다(ACTION_TYPE_LABELS와
 * 같은 관례). 취소는 어드민 환불과 포트원 콘솔 취소를 가리지 않고 같은 말이다 — 경로는 조치 이력이 보여 준다.
 * `owner_withdrawn`은 지급 뒤 주문자가 탈퇴한 결제라 환불 버튼을 두지 않는다(콘솔 취소만 서버가 맞춘다). */
export const PAYMENT_STATUS_LABELS = {
  pending: "결제 대기",
  paid: "결제 완료",
  failed: "결제 실패",
  mismatch: "검증 불일치",
  owner_withdrawn: "주문자 탈퇴",
  cancelled: "전액 취소",
  partially_cancelled: "부분 취소",
} satisfies Record<PaymentStatus, string>;

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
