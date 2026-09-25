import { getRateLimitDetail } from "@/shared/api/rateLimit";
import { assertNever } from "@/shared/lib/assertNever";

/** auth 429(`window: "auth"`)만 좁힌 타입 — `getImageRateLimit`(`widgets/image-studio`)과 같은 이유로
 * 여기서도 투영이 필요하다: `code`·`window` 가드를 통과해도 TS는 `detail`(변수 전체)의 타입을 판별
 * 유니언처럼 좁혀 주지 않아(플랫 객체 타입이라 프로퍼티별 CFA 좁히기가 전체 타입에 반영되지 않는다 —
 * `imageRateLimitMessage.ts:15-18`과 동일 실측), 좁혀진 프로퍼티 값으로 리터럴을 다시 지어야 한다. */
export type AuthRateLimitDetail = {
  code: "AUTH_LIMIT" | "AUTH_COOLDOWN";
  retryAfterSeconds: number;
  window: "auth";
};

/** `getRateLimitDetail`이 주는 제네릭 `RateLimitDetail`에서 auth 429만 골라낸다(`entities/chat-room`의
 * `getChatRateLimit`, `widgets/image-studio`의 `getImageRateLimit`과 같은 자리 — "이 슬라이스가
 * auth 429만 받는다"는 화면 결정은 shared가 알 일이 아니다). */
export function getAuthRateLimit(error: unknown): AuthRateLimitDetail | undefined {
  const detail = getRateLimitDetail(error);
  if (detail === null || detail.window !== "auth") return undefined;
  if (detail.code !== "AUTH_LIMIT" && detail.code !== "AUTH_COOLDOWN") return undefined;
  return { code: detail.code, retryAfterSeconds: detail.retryAfterSeconds, window: detail.window };
}

/** auth 429 문구. 두 코드는 사용자가 할 일이 다르다 — `AUTH_LIMIT`(시간당 상한, ≤3600초)은 정말로
 * 한참 기다려야 하고, `AUTH_COOLDOWN`(인증코드 재전송 60초)은 이미 `EmailVerifyStep`이 초 단위로
 * 직접 카운트다운한다(그 컴포넌트의 원래 용도). 그래서 이 함수가 두 코드를 같은 모양으로
 * 억지로 맞추지 않는다(`imageRateLimitMessage.ts`가 `USER_LIMIT`/`QUEUE_FULL`을 가른 것과 같은 이유):
 *
 * - `AUTH_LIMIT` → **분 단위 정적 문구**. 1시간을 초 카운트다운으로 말하지 않는다 — `RateLimitNotice`가
 *   day 창(최대 86400초)에 타이머를 안 건 근거가 여기서도 그대로 참이다: 백그라운드 탭에서
 *   `setInterval`이 늦춰져 숫자가 실제와 어긋나고, "3542초"는 "약 60분"보다 덜 알려준다.
 * - `AUTH_COOLDOWN` → **숫자 없는 문구**. 60초는 짧아 초 카운트다운이 적절하지만, 그 카운트다운은
 *   `EmailVerifyStep`이 로컬 `setInterval`로 이미 소유하고 있다 — 이 함수가 호출된 순간의
 *   `retryAfterSeconds`를 정적 문자열에 구우면 다음 렌더부터 실제 값과 어긋난다(값을 "약속"할 수
 *   없다는 점에서 day 창과 같은 이유). 그래서 여기서는 숫자를 아예 말하지 않는다 — 이 분기는 주로
 *   `assertNever` 총망라를 지키기 위한 것이고, 실제 카운트다운 문구는 계속 컴포넌트가 조립한다.
 *
 * `AUTH_LIMIT`의 분 계산이 **올림**인 이유: 이 숫자는 대기 약속이라 내림 오차(89초를 "1분")가 그대로
 * 재실패가 된다(`imageRateLimitMessage.ts:16-18`의 근거와 동일 — auth의 상한 ≤3600은 이미지의
 * ≤7200보다 짧아 같은 규칙이 그대로 맞는다).
 *
 * 은닉 관련: 아래 세 문구 모두 "요청 횟수는 호출자 자신의 행동이다"만 말하고 계정 존재를
 * 암시하지 않는다. `그 계정으로는 …`·`등록된 이메일로 …`·`이미 보낸 메일이 {N}통 있어요` 같은 단정형
 * 문구는 여기서 금지고, BE가 IP 기준 429와 이메일 기준 429를 `retry_after = ip_retry_after or email_retry_after`로
 * 이미 한 숫자로 합쳐 주므로("이 기기에서"/"이 이메일로"를 구분하는 문구도 못 쓴다). */
export function formatAuthRateLimitMessage(
  detail: AuthRateLimitDetail,
  surface: "signup" | "password-reset" | "resend",
): string {
  switch (detail.code) {
    case "AUTH_LIMIT": {
      const minutes = Math.max(1, Math.ceil(detail.retryAfterSeconds / 60));
      switch (surface) {
        case "signup":
          return `가입 시도가 너무 많았어요 · 약 ${minutes}분 뒤에 다시 시도할 수 있어요`;
        case "password-reset":
          return `재설정 메일을 너무 많이 요청했어요 · 약 ${minutes}분 뒤에 다시 요청할 수 있어요`;
        case "resend":
          return `재전송은 약 ${minutes}분 뒤에 다시 할 수 있어요`;
        default:
          return assertNever(surface);
      }
    }
    case "AUTH_COOLDOWN":
      return "잠시 후 다시 보낼 수 있어요";
    default:
      return assertNever(detail.code);
  }
}
