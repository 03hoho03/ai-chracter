/** 본인인증창이 페이지를 떠났다가(모바일) `/mypage` 로 돌아올 때 포트원이 붙이는 쿼리 중 이 화면이 읽는 것. */
export type IdentityRedirectSearch = {
  identityVerificationId?: string;
  code?: string;
};

/** - `none` — 인증에서 돌아온 것이 아니다.
 * - `complete` — 창이 성공으로 닫혔다. 서버에 결과 저장을 요청한다.
 * - `notCompleted` — 창이 실패 코드로 닫혔다(이용자 취소 포함). 인증 id 가 함께 와도 저장을 요청하지 않는다. */
export type IdentityRedirect =
  | { kind: "none" }
  | { kind: "complete"; identityVerificationId: string }
  | { kind: "notCompleted" };

export function resolveIdentityRedirect(search: IdentityRedirectSearch): IdentityRedirect {
  if (search.code !== undefined) return { kind: "notCompleted" };
  if (search.identityVerificationId) {
    return { kind: "complete", identityVerificationId: search.identityVerificationId };
  }
  return { kind: "none" };
}
