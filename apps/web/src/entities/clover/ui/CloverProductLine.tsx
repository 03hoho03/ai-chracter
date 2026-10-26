import type { CloverProductOffer } from "../api/useCloverProductsQuery";
import { describeCloverProductLine } from "../model/cloverProductLine";
import { CloverIcon } from "./CloverIcon";

/** 충전 상품 한 줄의 내용. 허브의 상품 행(누르는 버튼·로그인 링크·누를 수 없는 정보 행)과 구매 확인 다이얼로그의 상품
 * 요약이 같은 줄을 쓴다 — 껍데기(목록 행·버튼)는 호출부가 감싸고, 이 줄은 남은 폭을 다 쓴다(`flex-1`).
 *
 * 첫 줄은 이름과 가격을 양 끝에 둔다. 둘째 줄 "유료 N + 보너스 M = 총 T" 는 카드 안쪽 전체 폭을 쓴다 — 가격 칸과 한
 * 줄을 나누면 좁은 화면에서 식이 먼저 접힌다. 식은 세 조각(`[유료 N]` `[+ 보너스 M]` `[= 총 T]`)을 각각 줄바꿈 없이
 * 두고 조각 사이에서만 접혀, 좁으면 숫자 중간이 아니라 기호 앞에서 줄이 바뀐다. 상품끼리 견줄 값인 "총 T" 만 밝은
 * 잉크다. 숫자는 `tabular-nums` 라 행끼리 자릿수가 세로로 맞는다. 강조 채움·배지는 쓰지 않는다(큰 상품을 밀어 보이게
 * 하는 표시는 이 시스템의 단일 솔리드 규칙과 부딪힌다).
 *
 * 보이는 식은 기호를 읽지 않게 화면 읽기 프로그램에서 숨기고 같은 사실을 문장으로 읽힌다. 상품 이름과 가격은 보이는
 * 글자 그대로 접근 이름 앞에 남는다(보이는 라벨이 이름에 들어가야 음성 입력이 그 이름으로 누른다). */
export function CloverProductLine({ product }: { product: CloverProductOffer }) {
  const line = describeCloverProductLine(product);

  return (
    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
      <span className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 text-sm font-medium break-keep text-foreground">{product.name}</span>
        <span className="shrink-0 text-sm font-semibold whitespace-nowrap tabular-nums text-foreground">
          {product.priceKrw.toLocaleString()}원
        </span>
      </span>
      <span aria-hidden className="flex flex-wrap items-center gap-x-1 text-xs tabular-nums text-muted-foreground">
        <span className="inline-flex items-center gap-1 whitespace-nowrap">
          <CloverIcon />
          유료 {line.paid}
        </span>
        <span className="whitespace-nowrap">+ 보너스 {line.bonus}</span>
        <span className="whitespace-nowrap">
          = <span className="font-medium text-foreground">총 {line.total}</span>
        </span>
      </span>
      <span className="sr-only">{line.spoken}</span>
    </span>
  );
}
