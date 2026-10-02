import { isSuspendedError, SUSPENDED_ERROR_MESSAGE, type AuthFormErrorBanner } from "@/entities/session";
import { isApiError } from "@/shared/api/client";

const REREGISTRATION_BLOCKED_MESSAGE =
  "탈퇴 후 1년이 지나지 않은 이메일이라 다시 가입할 수 없어요. 탈퇴일로부터 1년이 지나면 다시 가입할 수 있어요.";

const EMAIL_ALREADY_REGISTERED_MESSAGE = "이미 가입된 이메일이에요. 처음 가입한 방법으로 로그인해주세요.";

/** code를 모르는 409(백엔드가 새 code를 더했는데 여기 아직 없을 때)의 폴백. 두 409를 함께 덮는 문장이라
 * 어느 쪽이어도 거짓이 되지 않는다 — 일반 오류 토스트로 떨어뜨리면 "다시 시도"가 풀리지 않는 실패를 숨긴다. */
const UNKNOWN_CONFLICT_MESSAGE =
  "이미 가입됐거나 탈퇴 후 1년이 지나지 않은 이메일이라 가입할 수 없어요. 처음 가입한 방법으로 로그인해주세요.";

/** 409의 `detail.code` → 문구. 같은 409가 "탈퇴 1년 이내"와 "그사이 같은 이메일이 가입됨"이라는 다른 사정을
 * 함께 나타내므로 status가 아니라 code로 가른다. */
const CONFLICT_MESSAGE_BY_CODE: Record<string, string> = {
  REREGISTRATION_BLOCKED: REREGISTRATION_BLOCKED_MESSAGE,
  EMAIL_ALREADY_REGISTERED: EMAIL_ALREADY_REGISTERED_MESSAGE,
};

/** 소셜 온보딩(`POST /auth/onboarding/{provider}`) 실패 → 배너. 판별할 수 없는 실패는 `undefined`이고
 * 호출부가 기존 fallback(toast)으로 보낸다.
 *
 * 409는 `detail.code`로, 나머지는 status로 가른다. 예외는 403 하나(`isSuspendedError`) — 정지가 아닌 403을
 * 정지로 읽지 않기 위해서다. 탈퇴 1년 제한은 제공자가 아니라 이메일 기준이라 "이메일" 문구가 두 제공자에
 * 모두 맞는다.
 *
 * 어느 문구도 "잠시 후 다시 시도"라고 하지 않는다 — 400은 가입 대기 쿠키가 이미 없고(만료·다른 브라우저),
 * 409는 탈퇴일로부터 1년(BE `_reregistration_blocked`)이 지나야 풀리거나 다른 방법으로 로그인해야 한다.
 * 소셜 가입은 로그인 화면의 소셜 버튼에서 다시 시작되므로 세 실패 모두 그리로 보낸다. */
export function getOnboardingErrorBanner(error: unknown): AuthFormErrorBanner | undefined {
  if (!isApiError(error)) return undefined;
  if (error.status === 400) {
    return { message: "인증이 만료되었어요. 처음부터 다시 시도해주세요.", shouldShowLoginLink: true };
  }
  if (error.status === 409) {
    const code = error.detail && typeof error.detail === "object" ? error.detail.code : undefined;
    const message = typeof code === "string" ? CONFLICT_MESSAGE_BY_CODE[code] : undefined;
    return { message: message ?? UNKNOWN_CONFLICT_MESSAGE, shouldShowLoginLink: true };
  }
  if (isSuspendedError(error)) return { message: SUSPENDED_ERROR_MESSAGE, shouldShowLoginLink: true };
  return undefined;
}
