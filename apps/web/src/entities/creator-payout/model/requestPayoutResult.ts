import { isIdentityVerificationRequiredError } from "@/entities/identity/@x/creator-payout";
import { isLegalReconsentRequiredError } from "@/entities/legal/@x/creator-payout";
import { isSuspendedError, SUSPENDED_ERROR_MESSAGE } from "@/entities/session/@x/creator-payout";

import { getCreatorPayoutErrorCode } from "./creatorPayoutError";

/** 지급 신청 하나가 어떻게 끝났는지. 정산 화면과 탈퇴 확인이 같은 갈래를 쓴다.
 *
 * - `requested` — 접수됐다(확정 잔액 전액).
 * - `infoRequired` — 지급 정보를 등록하지 않았다.
 * - `infoUnreadable` — 등록한 지급 정보를 서버가 읽지 못한다. 운영자도 이체할 수 없어 다시 입력해야 풀린다.
 * - `inProgress` — 처리 중인 지급이 이미 있다(다른 창에서 먼저 신청했다).
 * - `nothingToPay` — 확정 잔액이 0 이하다.
 * - `belowMinimum` — 잔액이 최소 지급액보다 적다(탈퇴 확인 밖의 신청).
 * - `notApproved` — 정산 승인을 받은 적이 없다.
 * - `identityRequired`·`ageRestricted`·`suspended` — 지급을 받을 자격이 없다. 화면을 연 뒤 상태가 바뀐 경우다.
 * - `reconsentRequired` — 바뀐 약관에 다시 동의해야 한다. 전역 뮤테이션 처리가 재동의 모달을 띄우므로 이 자리에는
 *   아무것도 말하지 않는다.
 * - `unavailable` — 정산이나 지급이 꺼졌거나, 처리방침 게시본이 없다.
 * - `failed` — 그 밖의 실패. */
export type RequestPayoutResult =
  | "requested"
  | "infoRequired"
  | "infoUnreadable"
  | "inProgress"
  | "nothingToPay"
  | "belowMinimum"
  | "notApproved"
  | "identityRequired"
  | "ageRestricted"
  | "suspended"
  | "reconsentRequired"
  | "unavailable"
  | "failed";

export type RequestPayoutFailure = Exclude<RequestPayoutResult, "requested">;

/** 신청 실패를 결과 갈래로. 본인인증·재동의·정지는 상태 코드가 모두 403 이라 코드(정지는 문자열 detail)까지 보는 기존
 * 판정을 쓴다. */
export function toRequestPayoutFailure(error: unknown): RequestPayoutFailure {
  if (isIdentityVerificationRequiredError(error)) return "identityRequired";
  if (isLegalReconsentRequiredError(error)) return "reconsentRequired";
  if (isSuspendedError(error)) return "suspended";
  switch (getCreatorPayoutErrorCode(error)) {
    case "CREATOR_PAYOUT_INFO_REQUIRED":
      return "infoRequired";
    case "CREATOR_PAYOUT_INFO_UNREADABLE":
      return "infoUnreadable";
    case "CREATOR_PAYOUT_IN_PROGRESS":
      return "inProgress";
    case "CREATOR_PAYOUT_NOTHING_TO_PAY":
      return "nothingToPay";
    case "CREATOR_PAYOUT_BELOW_MINIMUM":
      return "belowMinimum";
    case "CREATOR_PAYOUT_NOT_APPROVED":
      return "notApproved";
    case "CREATOR_PAYOUT_AGE_RESTRICTED":
      return "ageRestricted";
    case "CREATOR_PAYOUT_UNAVAILABLE":
      return "unavailable";
    default:
      return "failed";
  }
}

/** 신청 버튼 아래 남기는 문장. 기다려서 풀리지 않는 거절에는 "다시 시도"를 말하지 않는다. 재동의는 모달이 대신 말한다.
 * 신청은 결과와 무관하게 정산 요약을 다시 읽으므로, 잔액·지급 정보가 낡아 생긴 거절은 화면이 곧 맞는 안내로 바뀐다. */
export const REQUEST_PAYOUT_MESSAGES = {
  infoRequired: "지급 정보를 먼저 등록해 주세요.",
  infoUnreadable: "등록한 지급 정보를 읽을 수 없어요. 지급 정보를 다시 입력하면 신청할 수 있어요.",
  inProgress: "처리 중인 지급 신청이 있어요. 처리가 끝나면 다시 신청할 수 있어요.",
  nothingToPay: "신청할 수 있는 적립금이 없어요.",
  belowMinimum: "적립금이 최소 지급액보다 적어 아직 신청할 수 없어요.",
  notApproved: "정산 승인을 받은 적이 있어야 지급을 신청할 수 있어요.",
  identityRequired: "지급을 신청하려면 휴대폰 본인인증이 필요해요.",
  ageRestricted: "크리에이터 정산은 만 19세 이상만 이용할 수 있어요.",
  suspended: SUSPENDED_ERROR_MESSAGE,
  unavailable: "지금은 지급을 신청할 수 없어요. 문제가 계속되면 문의해 주세요.",
  failed: "지급을 신청하지 못했어요. 잠시 후 다시 시도해 주세요.",
} as const satisfies Record<Exclude<RequestPayoutFailure, "reconsentRequired">, string>;
