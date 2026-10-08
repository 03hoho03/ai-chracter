import { createFileRoute } from "@tanstack/react-router";

import { CloverPricingPage } from "@/pages/clover-pricing";

/** 공개 라우트 — 형제 `clover.index.tsx`(허브)와 달리 `beforeLoad: requireSession`이 없다. 결제하기 전에 상품과
 * 환불 조건을 로그인 없이 볼 수 있어야 한다. 부모 `clover.tsx` 레이아웃이 없어 허브의 가드가 여기 걸리지 않는다. */
export const Route = createFileRoute("/clover/pricing")({
  component: CloverPricingPage,
});
