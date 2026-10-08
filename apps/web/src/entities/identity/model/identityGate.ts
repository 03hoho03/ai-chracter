import type { components } from "@ai-character-chat/api-types";

import { isApiError } from "@/shared/api/client";

type IdentityGateFields = Pick<components["schemas"]["MeResponse"], "identityGateEnabled" | "identityVerified">;

/** 본인인증을 하지 않아 막혔다는 403. 채팅·미리보기(가진 클로버도 없을 때)·출석·미션·주문이 같은 코드를 쓴다.
 *
 * `detail` 이 객체인지부터 본다 — 정지 403 은 `detail` 이 문자열이고, 재동의·소설화 403 도 같은 상태 코드라 코드까지
 * 맞아야 이 안내를 띄운다. 코드를 보지 않으면 재동의 403 에 본인인증 안내가 나가 이용자가 엉뚱한 일을 하러 간다. */
export function isIdentityVerificationRequiredError(error: unknown): boolean {
  if (!isApiError(error) || error.status !== 403) return false;
  if (!error.detail || typeof error.detail !== "object") return false;
  return error.detail.code === "IDENTITY_VERIFICATION_REQUIRED";
}

/** 이 회원이 본인인증 게이트에 걸려 있는가 — 게이트 스위치가 켜졌고 아직 인증하지 않았다.
 *
 * 서버의 판정은 레이트리밋 면제 회원을 통과시키지만 `GET /me` 에는 면제 여부가 없어 이 값은 면제 회원도 걸린 것으로
 * 본다. 면제는 운영·테스트 계정뿐이라 그 계정에 안내가 더 보이는 데 그친다. 서버가 판정해 준 값이 있는 자리
 * (`attendanceClaimable`)는 그 값이 먼저다. */
export function isIdentityGated(me: IdentityGateFields): boolean {
  return me.identityGateEnabled && !me.identityVerified;
}
