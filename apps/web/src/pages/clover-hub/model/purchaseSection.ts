import type { MeResponse } from "@/entities/session";

/** 상품 행을 어떤 모양으로 그릴지 — 누르면 무슨 일이 일어나는가.
 *
 * - `pending` — 세션을 아직 묻는 중이다. 행 모양이 세션에 따라 갈리므로 행을 그리지 않는다(스켈레톤).
 * - `guest` — 로그인하지 않았다. 행은 로그인으로 가는 링크이고, 로그인한 뒤 그 상품의 결제로 돌아온다.
 * - `products` — 살 수 있다. 행은 구매 확인을 여는 버튼이다.
 * - `disabled`·`identityRequired`·`ageRestricted` — 지금 살 수 없다. 행은 누를 수 없는 정보다(할 수 없는 동작을
 *   약속하지 않는다). 이유는 구매 조건 자리가 말한다.
 *
 * 결제 스위치는 회원과 무관해 상품 응답의 `paymentsEnabled` 로 먼저 본다 — 꺼져 있으면 로그인 여부를 묻지 않는다.
 * 살 수 있는지는 서버가 주문 생성과 같은 함수로 판정해 `GET /me` 의 `purchaseBlockReason` 에 싣는다 — 화면이 따로
 * 판정하면 인증된 미성년이 이름·휴대폰·동의를 다 채운 뒤에야 나이 거절을 받는다. */
export type PurchaseSection = "pending" | "guest" | "disabled" | "identityRequired" | "ageRestricted" | "products";

type PurchaseViewer =
  | { kind: "pending" }
  | { kind: "guest" }
  | { kind: "member"; me: Pick<MeResponse, "purchaseBlockReason"> };

export function getPurchaseSection(paymentsEnabled: boolean, viewer: PurchaseViewer): PurchaseSection {
  if (!paymentsEnabled) return "disabled";
  switch (viewer.kind) {
    case "pending":
      return "pending";
    case "guest":
      return "guest";
    case "member":
      switch (viewer.me.purchaseBlockReason) {
        case "identity_required":
          return "identityRequired";
        case "age_restricted":
          return "ageRestricted";
        case null:
          return "products";
      }
  }
}
