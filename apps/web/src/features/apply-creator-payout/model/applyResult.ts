import { isIdentityVerificationRequiredError } from "@/entities/identity";
import { isLegalReconsentRequiredError } from "@/entities/legal";
import { isSuspendedError, SUSPENDED_ERROR_MESSAGE } from "@/entities/session";
import { isApiError } from "@/shared/api/client";

/** 정산 신청 하나가 어떻게 끝났는지.
 *
 * - `applied` — 접수됐다(대기 중).
 * - `identityRequired`·`ageRestricted`·`noPublishedWork`·`suspended` — 신청 자격이 없다. 화면이 미리 보인 자격과 같은
 *   판정이라, 여기 오는 것은 화면을 연 뒤 상태가 바뀐 경우다.
 * - `alreadyApplied` — 대기·승인 중인 신청이 이미 있다(다른 창에서 먼저 신청했다).
 * - `reconsentRequired` — 바뀐 약관에 다시 동의해야 한다. 전역 뮤테이션 처리가 세션을 다시 읽어 재동의 모달이 뜨므로
 *   이 자리에는 아무것도 말하지 않는다.
 * - `unavailable` — 정산이 꺼졌거나, 동의를 남길 처리방침 게시본이 없다.
 * - `failed` — 그 밖의 실패. */
export type ApplyResult =
  | "applied"
  | "identityRequired"
  | "ageRestricted"
  | "noPublishedWork"
  | "alreadyApplied"
  | "suspended"
  | "reconsentRequired"
  | "unavailable"
  | "failed";

/** 신청 실패를 결과 갈래로. 본인인증·재동의·정지는 상태 코드가 모두 403 이라 코드(정지는 문자열 detail)까지 보는 기존
 * 판정을 그대로 쓴다. */
export function toApplyFailure(error: unknown): Exclude<ApplyResult, "applied"> {
  if (isIdentityVerificationRequiredError(error)) return "identityRequired";
  if (isLegalReconsentRequiredError(error)) return "reconsentRequired";
  if (isSuspendedError(error)) return "suspended";
  const code = isApiError(error) && error.detail && typeof error.detail === "object" ? error.detail.code : undefined;
  switch (code) {
    case "CREATOR_PAYOUT_AGE_RESTRICTED":
      return "ageRestricted";
    case "CREATOR_PAYOUT_NO_PUBLISHED_WORK":
      return "noPublishedWork";
    case "CREATOR_PAYOUT_ALREADY_APPLIED":
      return "alreadyApplied";
    case "CREATOR_PAYOUT_UNAVAILABLE":
      return "unavailable";
    default:
      return "failed";
  }
}

/** 신청 버튼 아래 남기는 문장. 기다려서 풀리지 않는 거절(자격·정지)에는 "다시 시도"를 말하지 않는다. 재동의는 모달이
 * 대신 말하므로 문장이 없다. */
export const APPLY_MESSAGES = {
  applied: "정산을 신청했어요. 검토 결과는 이 화면에서 확인할 수 있어요.",
  identityRequired: "정산을 신청하려면 휴대폰 본인인증이 필요해요.",
  ageRestricted: "크리에이터 정산은 만 19세 이상만 신청할 수 있어요.",
  noPublishedWork: "발행한 작품이 있어야 신청할 수 있어요.",
  alreadyApplied: "이미 신청한 정산이 있어요.",
  suspended: SUSPENDED_ERROR_MESSAGE,
  unavailable: "지금은 정산을 신청할 수 없어요. 문제가 계속되면 문의해 주세요.",
  failed: "신청하지 못했어요. 잠시 후 다시 시도해 주세요.",
} as const satisfies Record<Exclude<ApplyResult, "reconsentRequired">, string>;
