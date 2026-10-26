/** 결제창이 페이지를 떠났다가(모바일) 돌아올 주소. 쿼리 없는 충전 화면 주소다 — 결제창이 여기에 결제 결과 쿼리를
 * 덧붙이는데, 쿼리가 이미 있을 때 덧붙이는 방식을 확정할 수 없어 결과 쿼리가 앞 값에 먹힐 수 있다. 충전하러 온 화면의
 * 주소는 쿼리 대신 탭 저장소로 나른다(`rememberPaymentReturnTo`). */
export function buildPaymentRedirectUrl(origin: string): string {
  return new URL("/clover", origin).toString();
}
