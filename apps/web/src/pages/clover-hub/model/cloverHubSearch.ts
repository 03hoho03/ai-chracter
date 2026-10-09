import { z } from "zod";

/** `/clover` 의 서치 파라미터.
 *
 * `paymentId`·`code` 는 결제창이 페이지를 떠났다가(모바일) 돌아올 때 포트원이 붙이는 것 중 화면이 읽는 둘이다. 결제
 * 결과를 따로 보여 줄 화면이 없어 허브가 그대로 받는다. 둘 다 문자열로 읽는다. 라우터가 쿼리 값을 JSON 으로 먼저 읽어
 * 숫자로만 된 값은 숫자로 오는데, `code` 가 숫자라고 버리면 실패한 결제를 성공으로 읽어 확정하러 간다 — 그래서 버리지
 * 않고 문자열로 되돌린다. 없으면 부재다.
 *
 * `product` 는 상품 안내 화면에서 고른 상품 키다. 허브가 그 상품의 구매 확인을 바로 연다. 어떤 키가 있는지는 가격
 * 응답이 정하므로 여기서는 문자열만 받고, 모르는 키는 허브가 무시한다. */
export const cloverHubSearchSchema = z.object({
  paymentId: z.coerce.string().optional().catch(undefined),
  code: z.coerce.string().optional().catch(undefined),
  product: z.string().optional().catch(undefined),
});

export type CloverHubSearch = z.infer<typeof cloverHubSearchSchema>;
