import { SOCIAL_PROVIDER_LABELS, SUSPENDED_ERROR_MESSAGE, type SocialProvider } from "@/entities/session";
import { assertNever } from "@/shared/lib/assertNever";

/** 소셜 로그인 콜백이 실패하면 백엔드가 `/login?error=<code>`로 돌려보낸다. 이 코드는 OpenAPI에 실리지 않아
 * codegen으로 따라오지 않으므로, 백엔드가 내는 목록을 여기 손으로 맞춘다. 목록에 없는 코드는 라우트 서치
 * 스키마가 `UNKNOWN_LOGIN_ERROR`로 접어 일반 오류 문구를 띄운다 — 그래서 새 코드를 여기 빠뜨리면 사용자는
 * 엉뚱한 "일시적인 오류"를 보게 되고, 아래 `switch`의 `assertNever`와 테스트가 목록·문구의 짝을 지킨다. */
export const LOGIN_ERROR_CODES = [
  "google_state",
  "kakao_state",
  "google_cancelled",
  "kakao_cancelled",
  "google_failed",
  "kakao_failed",
  "kakao_email_required",
  "kakao_email_taken",
  "google_email_taken",
  "account_deleted",
  "account_suspended",
  "account_age_restricted",
] as const;

export type LoginErrorCode = (typeof LOGIN_ERROR_CODES)[number];

/** 목록 밖의 `error` 값(백엔드가 새 코드를 더했는데 아직 여기 없거나, 손으로 고친 주소)을 접는 값. */
export const UNKNOWN_LOGIN_ERROR = "unknown";

export type LoginErrorParam = LoginErrorCode | typeof UNKNOWN_LOGIN_ERROR;

/** `*_email_taken`과 함께 오는 `method` — 같은 이메일이 이미 어느 방법으로 가입돼 있는지. */
export const SIGNUP_METHODS = ["email", "google", "kakao"] as const;

export type SignupMethod = (typeof SIGNUP_METHODS)[number];

export const GENERIC_LOGIN_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

// 만 14세 미만은 해결책이 없는 상태다 — "인증하면
// 된다"처럼 읽히는 문구를 주지 않는다.
export const MINIMUM_AGE_ERROR_MESSAGE = "만 14세 미만은 이용할 수 없는 서비스예요.";

/** 같은 이메일이 이미 다른 방법으로 가입돼 있다는 안내. 계정을 자동으로 잇지 않으므로 "그 방법으로 로그인"이
 * 유일한 출구라, 문구가 그 방법의 이름을 정확히 말해야 한다. `method`가 시도한 제공자와 같으면 같은 제공자의
 * **다른** 계정이 그 이메일을 쓰고 있다는 뜻이다. */
function emailTakenMessage(attempted: SocialProvider, method: SignupMethod | undefined): string {
  if (method === undefined) return "이미 가입된 이메일이에요. 처음 가입한 방법으로 로그인해주세요.";
  if (method === "email") return "이미 이메일·비밀번호로 가입된 계정이 있어요. 이메일과 비밀번호로 로그인해주세요.";
  const label = SOCIAL_PROVIDER_LABELS[method];
  if (method === attempted) {
    return `이미 다른 ${label}계정으로 가입된 이메일이에요. 그 ${label}계정으로 로그인해주세요.`;
  }
  return `이미 ${label}로 가입된 이메일이에요. ${label} 로그인을 이용해주세요.`;
}

/** 리다이렉트 오류 코드 → 배너 문구. `null`은 "배너를 띄우지 않는다"이다.
 *
 * `*_cancelled`가 `null`인 이유: 사용자가 제공자 동의 화면에서 **스스로** 취소하고 돌아온 것이라 고칠 것도
 * 알릴 것도 없다. 이 화면의 배너는 빨간 틴트 + `role="alert"`라 무엇을 띄우든 "실패했다"로 읽히고, 조용한
 * 회색 문장을 따로 만들어도 방금 자기가 한 일을 되읽히는 것뿐이다. 돌아온 화면에 로그인 버튼이 그대로 있어
 * 다시 시도할 길도 이미 열려 있다. */
export function getLoginErrorMessage(code: LoginErrorParam, method?: SignupMethod): string | null {
  switch (code) {
    case "google_state":
    case "kakao_state":
      return `${SOCIAL_PROVIDER_LABELS[code === "google_state" ? "google" : "kakao"]} 로그인 요청이 만료되었어요. 다시 시도해주세요.`;
    case "google_cancelled":
    case "kakao_cancelled":
      return null;
    case "google_failed":
    case "kakao_failed":
      return `${SOCIAL_PROVIDER_LABELS[code === "google_failed" ? "google" : "kakao"]} 로그인 중 문제가 생겼어요. 잠시 후 다시 시도해주세요.`;
    case "kakao_email_required":
      return "카카오계정에 인증된 이메일이 있어야 가입할 수 있어요. 카카오계정 설정에서 이메일을 등록하고 인증한 뒤 다시 시도해주세요.";
    case "kakao_email_taken":
      return emailTakenMessage("kakao", method);
    case "google_email_taken":
      return emailTakenMessage("google", method);
    case "account_suspended":
      return SUSPENDED_ERROR_MESSAGE;
    case "account_deleted":
      return "탈퇴한 계정이에요.";
    case "account_age_restricted":
      return MINIMUM_AGE_ERROR_MESSAGE;
    case UNKNOWN_LOGIN_ERROR:
      return GENERIC_LOGIN_ERROR_MESSAGE;
    default:
      return assertNever(code);
  }
}
