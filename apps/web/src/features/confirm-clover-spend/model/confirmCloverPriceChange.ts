import type { QueryClient } from "@tanstack/react-query";

import { getCloverPriceChangedCost, isCloverPriceChangedError, refetchCloverPricing } from "@/entities/clover";
import type { CloverSpendConfirmOutcome } from "@/entities/clover";

/** 가격이 바뀌었다는 409 를 받아, 가격표를 다시 받고 새 금액으로 한 번 묻는다.
 *
 * 저절로 다시 보내지 않는다 — 사용자가 본 적 없는 가격으로 깎지 않으려고 서버가 멈춘 것이라, 새 가격을 보여 주고 고르게
 * 하는 것이 이 거절의 목적이다. 확인하면 `retry` 를 돌려주고, 호출부가 같은 내용을 다시 보낼 때 캐시에 들어온 새 가격표의
 * 버전을 싣는다.
 *
 * 가격표를 다시 받지 못하면 묻지 않고 `unhandled` 다 — 옛 버전으로 다시 보내면 같은 409 를 받을 뿐이라 확인이 헛것이 된다.
 * `ask` 는 지금 금액(모르면 undefined)을 받아 사용자의 답을 돌려준다(모달은 호출하는 훅이 넘긴다 — 순수 함수로 두어
 * `QueryClient` 만으로 시험한다). */
export async function confirmCloverPriceChange(
  queryClient: QueryClient,
  error: unknown,
  ask: (currentCost: number | undefined) => Promise<boolean>,
): Promise<CloverSpendConfirmOutcome> {
  if (!isCloverPriceChangedError(error)) return "unhandled";
  try {
    await refetchCloverPricing(queryClient);
  } catch {
    return "unhandled";
  }
  return (await ask(getCloverPriceChangedCost(error))) ? "retry" : "declined";
}
