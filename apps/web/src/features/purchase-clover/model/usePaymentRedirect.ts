import { useEffect, useRef } from "react";
import { toast } from "sonner";

import { useCompletePaymentMutation } from "../api/useCompletePaymentMutation";
import { resolvePaymentRedirect, type PaymentRedirectSearch } from "./paymentRedirect";
import { PURCHASE_MESSAGES, toPurchaseResult, type PurchaseResult } from "./purchaseResult";

/** 결제창이 페이지를 떠났다가 허브로 돌아왔을 때(모바일) 쿼리를 읽어 확정을 이어받고, 끝나면 쿼리를 지운다.
 *
 * 마운트 시 뮤테이션이라 `mutateAsync` + `await` 다(StrictMode 의 재마운트가 콜백을 끊지 않게). 같은 복귀를 두 번
 * 처리하지 않게 처리한 키를 ref 로 기억한다 — 서버 확정은 멱등이지만 안내 토스트가 두 번 뜬다. 쿼리를 지우는 것은
 * 새로고침·뒤로가기로 같은 결제를 다시 확정하러 가지 않게 하려는 것이다.
 *
 * effect 는 키가 바뀔 때만 돈다. `redirect` 객체와 `onHandled` 는 렌더마다 새로 만들어지므로 의존성에 넣으면 매 렌더
 * 다시 돌고, 키가 같으면 같은 복귀다. */
export function usePaymentRedirect(search: PaymentRedirectSearch, onHandled: () => void) {
  const { mutateAsync } = useCompletePaymentMutation();
  const handledKey = useRef<string | null>(null);
  const redirect = resolvePaymentRedirect(search);
  const key = redirect.kind === "complete" ? `complete:${redirect.paymentId}` : redirect.kind;

  useEffect(() => {
    if (redirect.kind === "none" || handledKey.current === key) return;
    handledKey.current = key;

    void (async () => {
      if (redirect.kind === "notCompleted") {
        announcePurchaseResult("notCompleted");
      } else {
        try {
          const { status } = await mutateAsync(redirect.paymentId);
          announcePurchaseResult(toPurchaseResult(status));
        } catch {
          // 확인 요청만 실패했다. 결제는 됐을 수 있고 웹훅이 같은 결제를 맞춘다.
          announcePurchaseResult("checking");
        }
      }
      onHandled();
    })();
  }, [key]);
}

/** 구매가 끝나 다이얼로그 밖에서 알려야 하는 결과의 토스트. 다이얼로그(PC)와 리다이렉트 복귀(모바일)가 같은 문구를 쓴다.
 * 완료되지 않은 결제는 오류가 아니라(취소 포함) 중립 토스트다. 나머지 결과는 다이얼로그 안 문장이 맡는다. */
export function announcePurchaseResult(result: PurchaseResult) {
  switch (result) {
    case "paid":
      toast.success(PURCHASE_MESSAGES.paid);
      return;
    case "problem":
      toast.error(PURCHASE_MESSAGES.problem);
      return;
    case "checking":
    case "notCompleted":
      toast(PURCHASE_MESSAGES[result]);
      return;
    default:
      return;
  }
}
