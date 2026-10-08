import { classifyPortOneOutcome, type PortOneOutcome } from "./portOneOutcome";

/** 포트원 SDK 를 누를 때 불러온다. 패키지는 얇은 로더이고 결제창 코드는 포트원 CDN 스크립트라, 처음 화면에 실을 이유가
 * 없다(클로버 구매·본인인증을 누르는 사람만 받는다). 청크를 못 받으면 던지고, 그건 SDK 를 못 불러온 것과 같은 일이다. */
function loadPortOneSdk() {
  return import("@portone/browser-sdk/v2");
}

type PortOneSdk = Awaited<ReturnType<typeof loadPortOneSdk>>;

/** SDK 를 불러 한 번 부르고, 어떻게 끝났는지를 분류해 돌려준다. 던지지 않는다. */
async function callPortOne(
  call: (sdk: PortOneSdk) => Promise<{ code?: string | undefined } | undefined>,
): Promise<PortOneOutcome> {
  let sdk: PortOneSdk;
  try {
    sdk = await loadPortOneSdk();
  } catch {
    return classifyPortOneOutcome({ type: "threw", isPortOneError: false });
  }
  try {
    return classifyPortOneOutcome({ type: "returned", response: await call(sdk) });
  } catch (error) {
    return classifyPortOneOutcome({ type: "threw", isPortOneError: sdk.isPortOneError(error) });
  }
}

/** 결제창에 넘기는 값. 금액·주문명·상점·채널은 전부 우리 서버의 주문 응답에서 오고, 구매자 정보는 이 호출로만 포트원에
 * 간다 — 우리 서버로 보내지도, 브라우저에 저장하지도 않는다. */
export type PortOnePaymentInput = {
  storeId: string;
  channelKey: string;
  paymentId: string;
  orderName: string;
  totalAmount: number;
  payMethod: "CARD" | "EASY_PAY";
  /** 간편결제일 때 그 제공자(서버 목록의 값 그대로). 카드는 `null`. */
  easyPayProvider: string | null;
  customer: { fullName: string; phoneNumber: string; email: string };
  /** 모바일처럼 창이 페이지를 떠나는 경우 돌아올 주소. 결과가 쿼리로 붙는다. */
  redirectUrl: string;
};

/** 본인인증창에 넘기는 값. 상점·채널·인증 id 는 우리 서버의 시작 응답에서 온다. 인증 결과(CI·생년월일)는 브라우저에
 * 오지 않고 서버가 포트원에 직접 묻는다. */
export type PortOneIdentityVerificationInput = {
  storeId: string;
  channelKey: string;
  identityVerificationId: string;
  redirectUrl: string;
};

export function requestPortOneIdentityVerification(input: PortOneIdentityVerificationInput): Promise<PortOneOutcome> {
  return callPortOne((sdk) => sdk.requestIdentityVerification(input));
}

export function requestPortOnePayment(input: PortOnePaymentInput): Promise<PortOneOutcome> {
  return callPortOne(async (sdk) => {
    const base = {
      storeId: input.storeId,
      channelKey: input.channelKey,
      paymentId: input.paymentId,
      orderName: input.orderName,
      totalAmount: input.totalAmount,
      currency: sdk.Currency.KRW,
      customer: input.customer,
      redirectUrl: input.redirectUrl,
    };
    if (input.payMethod === "CARD") {
      return sdk.requestPayment({ ...base, payMethod: sdk.PaymentPayMethod.CARD });
    }
    // 제공자는 서버가 SDK 값 그대로 내려 준다. 이 SDK 판이 모르는 값이면 결제창이 거절할 요청이라 창을 띄우지 않는다.
    const easyPayProvider = Object.values(sdk.EasyPayProvider).find((provider) => provider === input.easyPayProvider);
    if (easyPayProvider === undefined) {
      throw new sdk.PaymentError({ code: "BadRequest", message: "unknown easy pay provider" });
    }
    return sdk.requestPayment({ ...base, payMethod: sdk.PaymentPayMethod.EASY_PAY, easyPay: { easyPayProvider } });
  });
}
