import { isCloverInsufficient } from "../model/cloverBalanceDisplay";

import { CloverBalance } from "./CloverBalance";

type CloverSpendSummaryProps = {
  /** 이번 한 번에 빠질 클로버. 서버가 준 단가를 그대로 받는다. */
  cost: number;
  /** 남은 클로버. 아직 못 받았으면 `undefined` — 그때는 잔액 없이 금액만 말한다(동의 자체는 막지 않는다). */
  balance: number | undefined;
};

/** 클로버를 쓰는 확인 단계의 금액 줄: "클로버 N개를 써요 · 남은 클로버 M". 잔액이 이번 금액에 못 미치면 확정
 * 전에 문장으로 한 번 더 알린다 — 잔량 숫자의 "부족해요"만으로는 누르면 어떻게 되는지가 없다.
 *
 * 경고는 `text-foreground` 문장이고 색 채움이 없다. 같은 확인 단계에 실행 버튼이 `primary` 솔리드로 있어(화면당
 * 하나) 경고까지 채우면 무엇을 눌러야 하는지가 흐려지고, 부족한 잔량 숫자는 이미 `CloverBalance` 가 잉크와
 * 글자로 표시한다. 버튼은 막지 않는다 — 다른 탭에서 클로버를 받았을 수 있어 화면의 잔액이 낡았을 수 있고,
 * 정말 모자라면 서버가 차감 없이 거절한다. */
export function CloverSpendSummary({ cost, balance }: CloverSpendSummaryProps) {
  const isInsufficient = balance !== undefined && isCloverInsufficient(balance, cost);

  return (
    <div className="flex flex-col gap-1.5">
      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm text-muted-foreground break-keep">
        <span>
          클로버 <span className="font-semibold text-foreground tabular-nums">{cost.toLocaleString()}</span>개를 써요
        </span>
        {balance !== undefined && (
          <>
            <span aria-hidden>·</span>
            <span className="inline-flex items-center gap-1.5">
              남은 클로버
              <CloverBalance balance={balance} isInsufficient={isInsufficient} />
            </span>
          </>
        )}
      </p>
      {isInsufficient && (
        <p className="text-sm text-foreground break-keep">
          클로버가 모자라 지금은 진행할 수 없어요. 클로버를 채운 뒤 다시 해주세요.
        </p>
      )}
    </div>
  );
}
