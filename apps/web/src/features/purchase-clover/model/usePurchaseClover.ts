import type { CloverProductItem } from "@/entities/clover";
import { isApiError } from "@/shared/api/client";
import { requestPortOnePayment } from "@/shared/lib/portone/portoneSdk";

import { useCompletePaymentMutation } from "../api/useCompletePaymentMutation";
import { useCreatePaymentMutation, type CreatePaymentResponse } from "../api/useCreatePaymentMutation";
import type { CloverPayMethodItem } from "./payMethod";
import { toPortOneCustomer, type PurchaseFormValues } from "./purchaseForm";
import { toPurchaseResult, type PurchaseResult } from "./purchaseResult";

type PurchaseInput = {
  productKey: CloverProductItem["key"];
  payMethod: CloverPayMethodItem;
  values: PurchaseFormValues;
  /** 결제창을 띄우기 직전에 부른다. 모달 다이얼로그가 열려 있으면 바깥(결제창 iframe)의 포인터·포커스를 막으므로
   * 호출부가 여기서 다이얼로그를 내린다. */
  onCheckoutOpen: () => void;
};

function errorCode(error: unknown): unknown {
  return isApiError(error) && error.detail && typeof error.detail === "object" ? error.detail.code : undefined;
}

/** 주문 생성 실패를 화면 갈래로. 본인인증 403 은 세션을 다시 읽는 것으로 화면이 바뀐다(전역 뮤테이션 처리). */
function toCreateFailure(error: unknown): PurchaseResult {
  const code = errorCode(error);
  if (code === "PAYMENT_AGE_RESTRICTED") return "ageRestricted";
  if (code === "IDENTITY_VERIFICATION_REQUIRED") return "identityRequired";
  if (code === "PAYMENTS_UNAVAILABLE") return "unavailable";
  return "failed";
}

/** 클로버 구매: 주문 생성 → 포트원 결제창 → 서버 확정. 끝난 모양만 돌려주고 던지지 않는다.
 *
 * 금액·주문명·상점·채널은 전부 주문 응답에서 가져온다(웹에 가격 사본이 없다). 결제창이 페이지를 떠나는 경우(모바일)
 * 돌아올 곳은 이 허브이고, 거기서 리다이렉트 처리가 확정을 이어받는다. */
export function usePurchaseClover() {
  const createPayment = useCreatePaymentMutation();
  const completePayment = useCompletePaymentMutation();

  async function purchase({ productKey, payMethod, values, onCheckoutOpen }: PurchaseInput): Promise<PurchaseResult> {
    let order: CreatePaymentResponse;
    try {
      order = await createPayment.mutateAsync({ productKey, agreed: true });
    } catch (error) {
      return toCreateFailure(error);
    }

    onCheckoutOpen();
    const outcome = await requestPortOnePayment({
      storeId: order.storeId,
      channelKey: order.channelKey,
      paymentId: order.paymentId,
      orderName: order.orderName,
      totalAmount: order.totalAmount,
      payMethod: payMethod.payMethod,
      easyPayProvider: payMethod.easyPayProvider,
      customer: toPortOneCustomer(values),
      redirectUrl: `${window.location.origin}/clover`,
    });
    if (outcome !== "succeeded") return outcome;

    try {
      const { status } = await completePayment.mutateAsync(order.paymentId);
      return toPurchaseResult(status);
    } catch {
      // 확인 요청만 실패했다(포트원 조회 실패 등). 결제는 됐을 수 있고 웹훅이 같은 결제를 맞춘다.
      return "checking";
    }
  }

  return { purchase };
}
