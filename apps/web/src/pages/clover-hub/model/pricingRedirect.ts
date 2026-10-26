import { z } from "zod";

/** 옛 상품 안내 주소(`/clover/pricing`)의 서치 파라미터. 그 화면은 충전 화면(`/clover`)으로 합쳐졌고, 옛 주소는 링크·
 * 검색 결과·북마크로 남아 있어 충전 화면으로 넘긴다. 넘길 때 가져가는 것은 고른 상품 키(`product`) 하나다 — 그 밖의
 * 파라미터는 옛 화면이 읽지 않던 것이다. 모양이 어긋난 값은 페이지를 죽이지 않고 부재로 접는다. */
export const cloverPricingRedirectSearchSchema = z.object({
  product: z.string().optional().catch(undefined),
});

export type CloverPricingRedirectSearch = z.infer<typeof cloverPricingRedirectSearchSchema>;

/** 충전 화면으로 넘길 서치 파라미터. 상품 키가 없으면 빈 서치다(`?product=undefined` 를 싣지 않는다). */
export function toCloverHubSearch(search: CloverPricingRedirectSearch): { product?: string } {
  return search.product === undefined ? {} : { product: search.product };
}
