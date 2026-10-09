import { isApiError } from "@/shared/api/client";

/** 본인인증 시도 하나가 어떻게 끝났는지. 마이페이지 섹션(PC)과 리다이렉트 복귀(모바일)가 같은 어휘로 안내한다.
 *
 * - `verified` — 서버가 결과를 저장했다.
 * - `redirecting` — 인증창이 페이지를 떠난다. 돌아오면 리다이렉트 처리가 이어받는다.
 * - `notice` — 그 밖. `tone` 이 `neutral` 이면 실패가 아니다(창을 닫았다·이미 인증했다). `reload` 면 새로고침만이
 *   길이다(인증창 SDK 를 못 불러왔다). */
export type IdentityResult =
  | { kind: "verified" }
  | { kind: "redirecting" }
  | { kind: "notice"; tone: "neutral" | "error"; message: string; reload?: boolean };

export const IDENTITY_VERIFIED_MESSAGE = "본인인증을 마쳤어요.";

const GENERIC_MESSAGE = "본인인증을 마치지 못했어요. 잠시 후 다시 시도해 주세요.";

export const IDENTITY_NOT_COMPLETED: IdentityResult = {
  kind: "notice",
  tone: "neutral",
  message: "본인인증이 완료되지 않았어요.",
};

export const IDENTITY_SDK_UNAVAILABLE: IdentityResult = {
  kind: "notice",
  tone: "error",
  message: "본인인증 창을 불러오지 못했어요. 페이지를 새로고침한 뒤 다시 시도해 주세요.",
  reload: true,
};

export const IDENTITY_REQUEST_FAILED: IdentityResult = {
  kind: "notice",
  tone: "error",
  message: "본인인증을 시작하지 못했어요. 문제가 계속되면 문의해 주세요.",
};

/** 서버 거절을 안내로. 서버의 `detail` 문구는 보이지 않고 코드로 가른다.
 *
 * 14세 미만·CI 없음·생년월일 없음은 서버가 **아무것도 저장하지 않은** 거절이라 그 사실을 함께 말한다. */
export function toIdentityErrorResult(error: unknown): IdentityResult {
  const code = isApiError(error) && error.detail && typeof error.detail === "object" ? error.detail.code : undefined;
  switch (code) {
    case "IDENTITY_ALREADY_VERIFIED":
      return { kind: "notice", tone: "neutral", message: "이미 본인인증을 마친 계정이에요." };
    case "IDENTITY_UNDER_MINIMUM_AGE":
      return {
        kind: "notice",
        tone: "error",
        message: "만 14세 미만은 본인인증을 할 수 없어요. 인증 정보는 저장하지 않았어요.",
      };
    case "IDENTITY_ALREADY_USED":
      return {
        kind: "notice",
        tone: "error",
        message: "다른 계정에서 이미 본인인증한 정보예요. 한 사람은 한 계정에서만 인증할 수 있어요.",
      };
    case "IDENTITY_CI_MISSING":
    case "IDENTITY_BIRTH_DATE_MISSING":
      return {
        kind: "notice",
        tone: "error",
        message: "인증 결과에 필요한 정보가 없어 인증을 마치지 못했어요. 인증 정보는 저장하지 않았어요. 계속되면 문의해 주세요.",
      };
    case "IDENTITY_VERIFICATION_NOT_VERIFIED":
      return IDENTITY_NOT_COMPLETED;
    case "IDENTITY_VERIFICATION_NOT_FOUND":
      return { kind: "notice", tone: "error", message: "인증 요청이 만료됐어요. 처음부터 다시 시도해 주세요." };
    case "IDENTITY_VERIFICATION_UNAVAILABLE":
      return { kind: "notice", tone: "error", message: "지금은 본인인증을 할 수 없어요." };
    default:
      return { kind: "notice", tone: "error", message: GENERIC_MESSAGE };
  }
}
