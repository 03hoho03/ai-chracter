import { z } from "zod";

import { parseReturnTo } from "./returnTo";

/** `/clover` 의 서치 파라미터.
 *
 * `paymentId`·`code` 는 결제창이 페이지를 떠났다가(모바일) 돌아올 때 포트원이 붙이는 것 중 화면이 읽는 둘이다. 결제
 * 결과를 따로 보여 줄 화면이 없어 허브가 그대로 받는다. 둘 다 문자열로 읽는다. 라우터가 쿼리 값을 JSON 으로 먼저 읽어
 * 숫자로만 된 값은 숫자로 오는데, `code` 가 숫자라고 버리면 실패한 결제를 성공으로 읽어 확정하러 간다 — 그래서 버리지
 * 않고 문자열로 되돌린다. 없으면 부재다.
 *
 * `product` 는 주소에 담겨 온 상품 키다(로그인하러 갔다 돌아온 상품 행, 옛 상품 안내 주소). 살 수 있으면 그 상품의
 * 구매 확인을 바로 연다. 어떤 키가 있는지는 상품 응답이 정하므로 여기서는 문자열만 받고, 모르는 키는 화면이 판매하지
 * 않는다고 알린다.
 *
 * `returnTo` 는 충전하러 온 화면(채팅 방 등)의 주소다. 이 사이트 안의 경로만 받고(`parseReturnTo`), 어긋나면 부재로
 * 접는다 — 링크를 그리지 않을 뿐 화면은 그대로 열린다. 로그인 왕복은 지금 주소를 통째로 싣는다. 결제창 왕복은 돌아올
 * 주소에 쿼리를 싣지 않아 이 파라미터 없이 돌아오고, 그때의 복귀 주소는 탭 저장소가 나른다(`resolveHubReturnTo`). */
export const cloverHubSearchSchema = z.object({
  paymentId: z.coerce.string().optional().catch(undefined),
  code: z.coerce.string().optional().catch(undefined),
  product: z.string().optional().catch(undefined),
  returnTo: z
    .string()
    .refine((value) => parseReturnTo(value) !== undefined)
    .optional()
    .catch(undefined),
});

export type CloverHubSearch = z.infer<typeof cloverHubSearchSchema>;
