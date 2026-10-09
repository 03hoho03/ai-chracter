import type { MeResponse } from "@/entities/session";

/** 허브 구매 섹션에 무엇을 둘지.
 *
 * 살 수 있는지는 서버가 주문 생성과 같은 함수로 판정해 `GET /me` 의 `purchaseBlockReason` 에 싣는다 — 허브가 따로
 * 판정하면 인증된 미성년이 이름·휴대폰·동의를 다 채운 뒤에야 나이 거절을 받는다. 결제 스위치는 회원과 무관해 가격
 * 응답의 `paymentsEnabled` 로 먼저 본다. 세션을 아직 못 읽었으면 살 수 있다고 보지 않는다(본인인증 안내). */
export type PurchaseSection = "disabled" | "identityRequired" | "ageRestricted" | "products";

export function getPurchaseSection(
  paymentsEnabled: boolean,
  me: Pick<MeResponse, "purchaseBlockReason"> | undefined,
): PurchaseSection {
  if (!paymentsEnabled) return "disabled";
  if (me === undefined) return "identityRequired";
  switch (me.purchaseBlockReason) {
    case "identity_required":
      return "identityRequired";
    case "age_restricted":
      return "ageRestricted";
    case null:
      return "products";
  }
}
