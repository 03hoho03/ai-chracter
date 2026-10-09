import type { CloverProductItem } from "../api/useCloverPricingQuery";
import { formatCloverUnitPrice, getCloverBonusRate } from "../model/cloverProductValue";
import { CloverIcon } from "./CloverIcon";

/** 충전 상품 한 줄의 내용(이름 · 받는 클로버 · 가격). 상품 안내 표와 허브의 구매 버튼·구매 확인이 같은 줄을 쓴다 —
 * 껍데기(목록 행·버튼)는 호출부가 감싼다. 숫자는 전부 `GET /clover/pricing` 응답 그대로다.
 *
 * 보조 줄은 상품끼리 견줄 단서다. 왼쪽은 받는 양과 보너스율, 오른쪽은 가격 아래 클로버 한 개 값으로 양쪽에 나눠
 * 가장 좁은 소비처(390px 폭의 구매 확인 창)에서도 각 보조 줄이 한 줄에 든다. 숫자는 `tabular-nums` 라 다섯 행의
 * 자릿수가 세로로 맞는다. 강조 채움은 쓰지 않는다(큰 상품을 밀어 보이게 하는 배지는 이 시스템의 단일 솔리드 규칙과 부딪힌다). */
export function CloverProductLine({ product }: { product: CloverProductItem }) {
  const bonusRate = getCloverBonusRate(product);
  const unitPrice = formatCloverUnitPrice(product);

  return (
    <>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm font-medium text-foreground">{product.name}</span>
        <span className="inline-flex flex-wrap items-center gap-x-1 text-xs break-keep tabular-nums text-muted-foreground">
          <CloverIcon />
          클로버 {(product.paidAmount + product.bonusAmount).toLocaleString()}개
          {bonusRate !== null && <span>· 보너스 {bonusRate}%</span>}
        </span>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-0.5">
        <span className="text-sm font-semibold whitespace-nowrap tabular-nums text-foreground">
          {product.priceKrw.toLocaleString()}원
        </span>
        {unitPrice !== null && (
          <span className="text-xs whitespace-nowrap tabular-nums text-muted-foreground">개당 {unitPrice}원</span>
        )}
      </div>
    </>
  );
}
