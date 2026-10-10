import type { components } from "@ai-character-chat/api-types";

import type { CreatorPayoutStatus } from "../api/keys";

/** 지급 상태. 보류는 탈퇴한 회원의 건에만 생긴다(등록된 정보로 이체할 수 없어 새 수취 정보를 기다리는 중). */
export const CREATOR_PAYOUT_STATUS_LABELS = {
  requested: "처리 중",
  held: "보류",
  paid: "지급 완료",
  returned: "반려",
} satisfies Record<CreatorPayoutStatus, string>;

export function isCreatorPayoutStatus(value: string): value is CreatorPayoutStatus {
  return Object.hasOwn(CREATOR_PAYOUT_STATUS_LABELS, value);
}

type ConfirmationKind = components["schemas"]["AdminUserCreatorPayoutConfirmation"]["kind"];

/** 확정 행의 종류. 소급은 첫 승인 때 지난 기간을 한 번에 확정한 행, 월 확정은 매달 배치가 만든 행이다. */
export const CREATOR_PAYOUT_CONFIRMATION_KIND_LABELS = {
  retro: "승인 소급",
  monthly: "월 확정",
} satisfies Record<ConfirmationKind, string>;

export type PayeeInfoViewReasonCategory = components["schemas"]["PayeeInfoViewReasonCategory"];

/** 지급 정보 원문 열람 사유 분류. 채팅 열람 사유(entities/admin-user)와 다른 enum 이다 — 지급 업무에서 원문을 여는 이유는
 * 이체 전 확인과 지급명세서 작성이 대부분이다. 회원 상세의 조치 이력 표에 채팅 열람 사유와 섞여 나오므로, 겹치는 값
 * (`legal-request`·`other`)은 채팅 열람과 라벨을 같게 둔다. */
export const PAYEE_INFO_VIEW_REASON_CATEGORY_LABELS = {
  "payout-processing": "지급 처리",
  "payout-statement": "지급명세서 작성",
  "legal-request": "법적 요청",
  other: "기타",
} satisfies Record<PayeeInfoViewReasonCategory, string>;

export function isPayeeInfoViewReasonCategory(value: string): value is PayeeInfoViewReasonCategory {
  return Object.hasOwn(PAYEE_INFO_VIEW_REASON_CATEGORY_LABELS, value);
}

/** 목록·선택지는 라벨 키에서 도출한다 — 사유가 늘면 라벨의 `satisfies` 가 컴파일 에러로 잡고 목록은 저절로 따라온다. */
export const PAYEE_INFO_VIEW_REASON_CATEGORY_VALUES = Object.keys(PAYEE_INFO_VIEW_REASON_CATEGORY_LABELS).filter(
  isPayeeInfoViewReasonCategory,
);

export const PAYEE_INFO_VIEW_REASON_CATEGORY_OPTIONS = PAYEE_INFO_VIEW_REASON_CATEGORY_VALUES.map((value) => ({
  value,
  label: PAYEE_INFO_VIEW_REASON_CATEGORY_LABELS[value],
}));

export type BankCode = components["schemas"]["AdminCreatorPayoutDetail"]["bankCode"];

/** 은행(금융결제원 3자리 코드 → 이름). 서버가 받는 코드 목록과 같아야 한다 — `satisfies` 라 서버 목록이 바뀌어 api-types 를
 * 다시 만들면 여기서 컴파일이 깨진다. 선택 목록은 이 순서대로 보인다(이용자가 많은 은행을 앞에). 웹의 지급 정보 입력과
 * 같은 이름·순서다(앱끼리 import 할 수 없어 따로 둔다). */
export const BANK_LABELS = {
  "004": "KB국민은행",
  "088": "신한은행",
  "020": "우리은행",
  "081": "하나은행",
  "011": "NH농협은행",
  "012": "지역 농·축협",
  "003": "IBK기업은행",
  "090": "카카오뱅크",
  "092": "토스뱅크",
  "089": "케이뱅크",
  "071": "우체국",
  "045": "새마을금고",
  "048": "신협",
  "007": "수협은행",
  "002": "KDB산업은행",
  "023": "SC제일은행",
  "027": "한국씨티은행",
  "031": "iM뱅크(대구은행)",
  "032": "부산은행",
  "039": "경남은행",
  "034": "광주은행",
  "037": "전북은행",
  "035": "제주은행",
  "050": "저축은행",
  "064": "산림조합",
} satisfies Record<BankCode, string>;

export function isBankCode(value: string): value is BankCode {
  return Object.hasOwn(BANK_LABELS, value);
}

export const BANK_OPTIONS = Object.keys(BANK_LABELS)
  .filter(isBankCode)
  .map((value) => ({ value, label: BANK_LABELS[value] }));
