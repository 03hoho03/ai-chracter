import type { CloverProductItem } from "../api/useCloverPricingQuery";
import { getCloverBonusRate } from "../model/cloverProductValue";
import { CloverIcon } from "./CloverIcon";

/** 충전 상품 한 줄의 내용(이름 · 받는 클로버 · 가격). 상품 안내 표와 허브의 구매 버튼·구매 확인이 같은 줄을 쓴다 —
 * 껍데기(목록 행·버튼)는 호출부가 감싼다. 숫자는 전부 `GET /clover/pricing` 응답 그대로다.
 *
 * 왼쪽 보조 줄(받는 양과 보너스율)이 상품끼리 견줄 단서다. 가격은 오른쪽 끝에 한 줄로 두고 왼쪽 두 줄의 가운데에
 * 맞춘다(껍데기가 `items-center`). 숫자는 `tabular-nums` 라 다섯 행의 자릿수가 세로로 맞는다. 강조 채움은 쓰지
 * 않는다(큰 상품을 밀어 보이게 하는 배지는 이 시스템의 단일 솔리드 규칙과 부딪힌다). */
export function CloverProductLine({ product }: { product: CloverProductItem }) {
  const bonusRate = getCloverBonusRate(product);

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
      <span className="shrink-0 text-sm font-semibold whitespace-nowrap tabular-nums text-foreground">
        {product.priceKrw.toLocaleString()}원
      </span>
    </>
  );
}
