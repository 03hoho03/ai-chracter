import type { components } from "@ai-character-chat/api-types";

type PayoutStatus = components["schemas"]["CreatorPayoutPayoutView"]["status"];

/** 지급 신청 상태를 작가에게 보이는 말로. 운영자가 이체를 미뤄 두는 보류는 서버가 회원 응답에서 "처리 중"으로 접어
 * 보내 여기 오지 않는다. `Record` 라 회원 응답의 상태가 늘어 api-types 를 다시 만들면 타입 검사가 이 표에 라벨을
 * 채우라고 막는다. */
const PAYOUT_STATUS_LABELS: Record<PayoutStatus, string> = {
  requested: "처리 중",
  paid: "이체 완료",
  returned: "반려",
};

function isKnownPayoutStatus(status: string): status is PayoutStatus {
  return Object.hasOwn(PAYOUT_STATUS_LABELS, status);
}

/** 상태 라벨. 서버가 먼저 배포돼 이 번들이 모르는 상태가 오면 "처리 중"으로 읽는다 — 아직 끝나지 않은 지급으로 보는
 * 쪽이 빈 라벨이나 영문 값보다 덜 틀린다(끝난 상태를 새로 만들 일은 없다). */
export function formatPayoutStatus(status: string): string {
  return isKnownPayoutStatus(status) ? PAYOUT_STATUS_LABELS[status] : PAYOUT_STATUS_LABELS.requested;
}

/** 이체한 날(`YYYY-MM-DD`, 한국 날짜)을 `YYYY.MM.DD` 로. `new Date()` 로 읽으면 UTC 자정이 되어 한국보다 서쪽 시간대에서
 * 하루 앞 날짜가 찍히므로 글자만 바꾼다. */
export function formatTransferredOn(transferredOn: string): string {
  return transferredOn.replaceAll("-", ".");
}
