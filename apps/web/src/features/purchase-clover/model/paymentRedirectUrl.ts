/** 결제창이 페이지를 떠났다가(모바일) 돌아올 주소. 충전 화면이 받은 복귀 주소(`returnTo`)를 함께 실어야 돌아온 뒤에도
 * "대화로 돌아가기"가 갈 곳을 안다 — 결제창은 이 주소에 결제 결과 쿼리만 덧붙인다. 복귀 주소는 충전 화면이 이미 검사한
 * 값만 받는다. */
export function buildPaymentRedirectUrl(origin: string, returnTo: string | undefined): string {
  const url = new URL("/clover", origin);
  if (returnTo !== undefined) url.searchParams.set("returnTo", returnTo);
  return url.toString();
}
