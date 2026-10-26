import { createFileRoute, redirect } from "@tanstack/react-router";

import { cloverPricingRedirectSearchSchema, toCloverHubSearch } from "@/pages/clover-hub";

/** 옛 상품 안내 주소. 그 화면은 클로버 충전 화면(`/clover`)으로 합쳐졌고, 이 주소는 링크·검색 결과·북마크로 남아 있어
 * 충전 화면으로 넘긴다(고른 상품 `?product=` 는 그대로 가져간다). `replace` 라 뒤로가기가 이 주소로 돌아와 다시 넘기는
 * 고리를 만들지 않는다. 파일을 지우면 이 주소가 404 가 되므로 넘기기 위해 남긴다(워커의 알려진 경로 목록도 같다). */
export const Route = createFileRoute("/clover/pricing")({
  validateSearch: cloverPricingRedirectSearchSchema,
  // `throw: true` 는 라우터가 넘기기 객체를 대신 던지게 한다(라우터가 잡아 이동시키는 정상 흐름이다).
  beforeLoad: ({ search }) => {
    redirect({ to: "/clover", search: toCloverHubSearch(search), replace: true, throw: true });
  },
});
