import type { CloverProductItem } from "../api/useCloverPricingQuery";
import { CloverIcon } from "./CloverIcon";

/** 충전 상품 한 줄의 내용(이름 · 받는 클로버 · 가격). 상품 안내 표와 허브의 구매 버튼·구매 확인이 같은 줄을 쓴다 —
 * 껍데기(목록 행·버튼)는 호출부가 감싼다. 숫자는 전부 `GET /clover/pricing` 응답 그대로다. */
export function CloverProductLine({ product }: { product: CloverProductItem }) {
  return (
    <>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm font-medium text-foreground">{product.name}</span>
        <span className="inline-flex flex-wrap items-center gap-x-1 text-xs break-keep text-muted-foreground">
          <CloverIcon />
          클로버 {(product.paidAmount + product.bonusAmount).toLocaleString()}개
          {product.bonusAmount > 0 && <span>(보너스 {product.bonusAmount.toLocaleString()} 포함)</span>}
        </span>
      </div>
      <span className="shrink-0 text-sm font-semibold whitespace-nowrap tabular-nums text-foreground">
        {product.priceKrw.toLocaleString()}원
      </span>
    </>
  );
}
