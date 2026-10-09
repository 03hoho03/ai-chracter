/** 노벨 탭·홈 노벨 섹션·노벨 가격 행을 보일지. 인증 없는 가격 응답(`GET /clover/pricing`)의 `novelPublicEnabled` 는 노벨이
 * 모두에게 열렸을 때만 참이고(미리보기 명단이 있는 동안은 거짓), 명단 회원에게는 `GET /me` 의 같은 이름 값이 참이다 — 둘 중
 * 하나라도 참이면 연다. 응답을 아직 못 받았거나 필드가 없는 옛 응답이면 그쪽은 닫힌 것으로 본다(웹과 API 는 따로 배포된다). */
export function isWebnovelOpen(pricingEnabled: boolean | undefined, sessionEnabled: boolean | undefined): boolean {
  return pricingEnabled === true || sessionEnabled === true;
}
