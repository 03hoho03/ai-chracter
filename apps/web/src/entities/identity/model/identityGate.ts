import { isApiError } from "@/shared/api/client";

/** 본인인증을 하지 않아 막혔다는 403. 채팅·미리보기(가진 클로버도 없을 때)·미션·주문이 같은 코드를 쓴다.
 *
 * `detail` 이 객체인지부터 본다 — 정지 403 은 `detail` 이 문자열이고, 재동의·소설화 403 도 같은 상태 코드라 코드까지
 * 맞아야 이 안내를 띄운다. 코드를 보지 않으면 재동의 403 에 본인인증 안내가 나가 이용자가 엉뚱한 일을 하러 간다.
 *
 * "이 회원이 지금 게이트에 걸리는가"는 여기서 판정하지 않는다 — 서버가 라우트 게이트와 같은 함수로 계산한
 * `GET /me` 의 `identityGated` 를 그대로 쓴다(스위치·인증 여부만으로 판정하면 레이트리밋 면제 회원을 잘못 잠근다). */
export function isIdentityVerificationRequiredError(error: unknown): boolean {
  if (!isApiError(error) || error.status !== 403) return false;
  if (!error.detail || typeof error.detail !== "object") return false;
  return error.detail.code === "IDENTITY_VERIFICATION_REQUIRED";
}
