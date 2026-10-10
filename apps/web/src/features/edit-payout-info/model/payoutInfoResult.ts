import { getCreatorPayoutErrorCode } from "@/entities/creator-payout";
import { isIdentityVerificationRequiredError } from "@/entities/identity";
import { isLegalReconsentRequiredError } from "@/entities/legal";
import { isSuspendedError, SUSPENDED_ERROR_MESSAGE } from "@/entities/session";

/** 지급 정보 저장 하나가 어떻게 끝났는지.
 *
 * - `saved` — 저장됐다(이전 정보는 서버가 새 판으로 대체한다).
 * - `invalid` — 서버가 형식을 받지 않았다. 화면 검증과 같은 기준이라 여기 오는 것은 드물다.
 * - `foreigner` — 외국인등록번호다. 지금은 내국인만 받으며 문의로 안내한다.
 * - `rrnMismatch` — 주민등록번호 앞자리(생년월일)가 본인인증한 생년월일과 다르다.
 * - `inProgress` — 처리 중인 지급이 있어 수취인을 바꿀 수 없다.
 * - `notApproved` — 정산 승인을 받은 적이 없다.
 * - `identityRequired`·`ageRestricted`·`suspended` — 지급을 받을 자격이 없다. 화면을 연 뒤 상태가 바뀐 경우다.
 * - `reconsentRequired` — 바뀐 약관에 다시 동의해야 한다. 전역 뮤테이션 처리가 재동의 모달을 띄운다.
 * - `unavailable` — 정산이나 지급이 꺼졌거나, 동의를 남길 처리방침 게시본이 없다.
 * - `failed` — 그 밖의 실패. */
export type PayoutInfoResult =
  | "saved"
  | "invalid"
  | "foreigner"
  | "rrnMismatch"
  | "inProgress"
  | "notApproved"
  | "identityRequired"
  | "ageRestricted"
  | "suspended"
  | "reconsentRequired"
  | "unavailable"
  | "failed";

export type PayoutInfoFailure = Exclude<PayoutInfoResult, "saved">;

export function toPayoutInfoFailure(error: unknown): PayoutInfoFailure {
  if (isIdentityVerificationRequiredError(error)) return "identityRequired";
  if (isLegalReconsentRequiredError(error)) return "reconsentRequired";
  if (isSuspendedError(error)) return "suspended";
  switch (getCreatorPayoutErrorCode(error)) {
    case "CREATOR_PAYOUT_INFO_INVALID":
      return "invalid";
    case "CREATOR_PAYOUT_FOREIGNER_UNSUPPORTED":
      return "foreigner";
    case "CREATOR_PAYOUT_RRN_MISMATCH":
      return "rrnMismatch";
    case "CREATOR_PAYOUT_IN_PROGRESS":
      return "inProgress";
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

/** 실패를 어느 칸 아래에 보일지. 주민등록번호 자체가 거절된 두 갈래는 그 칸에 붙여 고칠 곳을 가리키고, 나머지는 폼
 * 머리의 오류 상자에 둔다. */
export function toPayoutInfoFailureField(failure: PayoutInfoFailure): "rrn" | null {
  return failure === "foreigner" || failure === "rrnMismatch" ? "rrn" : null;
}

/** 실패 문장. 기다려서 풀리지 않는 거절에는 "다시 시도"를 말하지 않는다. 재동의는 모달이 대신 말한다. */
export const PAYOUT_INFO_MESSAGES = {
  invalid: "입력한 지급 정보의 형식이 맞지 않아요. 실명·주민등록번호·계좌번호를 확인해 주세요.",
  foreigner: "외국인등록번호로는 아직 지급 정보를 등록할 수 없어요. 문의하기로 알려 주세요.",
  rrnMismatch: "본인인증한 생년월일과 주민등록번호 앞자리가 달라요. 본인의 주민등록번호를 입력해 주세요.",
  inProgress: "처리 중인 지급이 있어 지금은 지급 정보를 바꿀 수 없어요. 처리가 끝난 뒤 바꿔 주세요.",
  notApproved: "정산 승인을 받은 적이 있어야 지급 정보를 등록할 수 있어요.",
  identityRequired: "지급 정보를 등록하려면 휴대폰 본인인증이 필요해요.",
  ageRestricted: "크리에이터 정산은 만 19세 이상만 이용할 수 있어요.",
  suspended: SUSPENDED_ERROR_MESSAGE,
  unavailable: "지금은 지급 정보를 등록할 수 없어요. 문제가 계속되면 문의해 주세요.",
  failed: "지급 정보를 저장하지 못했어요. 잠시 후 다시 시도해 주세요.",
} as const satisfies Record<Exclude<PayoutInfoFailure, "reconsentRequired">, string>;
