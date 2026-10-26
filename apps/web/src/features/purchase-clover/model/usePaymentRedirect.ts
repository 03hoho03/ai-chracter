import { useEffect, useRef } from "react";

import { useCompletePaymentMutation } from "../api/useCompletePaymentMutation";
import { resolvePaymentRedirect, type PaymentRedirectSearch } from "./paymentRedirect";
import { toSettledPurchase, type SettledPurchase } from "./settledPurchase";

/** 결제창이 페이지를 떠났다가 충전 화면으로 돌아왔을 때(모바일) 쿼리를 읽어 확정을 이어받고, 끝난 결과를 화면에 넘긴 뒤
 * 쿼리를 지운다. 결과는 토스트가 아니라 화면의 결과 자리가 그린다 — 다이얼로그 결제(PC)와 같은 자리다.
 *
 * 마운트 시 뮤테이션이라 `mutateAsync` + `await` 다(StrictMode 의 재마운트가 콜백을 끊지 않게). 같은 복귀를 두 번
 * 처리하지 않게 처리한 키를 ref 로 기억한다 — 서버 확정은 멱등이지만 결과가 두 번 넘어간다. 쿼리를 지우는 것은
 * 새로고침·뒤로가기로 같은 결제를 다시 확정하러 가지 않게 하려는 것이다.
 *
 * effect 는 키가 바뀔 때만 돈다. `redirect` 객체와 콜백은 렌더마다 새로 만들어지므로 의존성에 넣으면 매 렌더 다시
 * 돌고, 키가 같으면 같은 복귀다. */
export function usePaymentRedirect(
  search: PaymentRedirectSearch,
  onSettled: (settled: SettledPurchase) => void,
  onHandled: () => void,
) {
  const { mutateAsync } = useCompletePaymentMutation();
  const handledKey = useRef<string | null>(null);
  const redirect = resolvePaymentRedirect(search);
  const key = redirect.kind === "complete" ? `complete:${redirect.paymentId}` : redirect.kind;

  useEffect(() => {
    if (redirect.kind === "none" || handledKey.current === key) return;
    handledKey.current = key;

    void (async () => {
      if (redirect.kind === "notCompleted") {
        onSettled({ result: "notCompleted", grant: null });
      } else {
        try {
          onSettled(toSettledPurchase(await mutateAsync(redirect.paymentId)));
        } catch {
          // 확인 요청만 실패했다. 결제는 됐을 수 있고 웹훅이 같은 결제를 맞춘다.
          onSettled({ result: "checking", grant: null });
        }
      }
      onHandled();
    })();
  }, [key]);
}
