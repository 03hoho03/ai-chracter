/** 결제창이 페이지를 떠났다가(모바일) 충전 화면으로 돌아오는 동안 복귀 주소(충전하러 온 화면)를 나르는 탭 저장소 값.
 *
 * 결제창의 돌아올 주소에 쿼리로 싣지 않는 이유: 결제창은 그 주소에 결제 결과 쿼리를 덧붙이는데, 주소에 쿼리가 이미 있을
 * 때 어떻게 덧붙이는지 확정할 수 없다 — 잘못 붙으면 결과 쿼리가 앞 값에 먹혀 결제 확정이 사라진다. 그래서 돌아올 주소는
 * 쿼리 없이 두고, 결제창을 띄우기 직전에 여기 넣었다가 충전 화면이 결제창 복귀를 처리할 때 읽고 지운다. 값을 검사하는
 * 일은 충전 화면 몫이다(넣을 때도 읽을 때도 그 검사를 통과한 값만 쓴다). 키는 하나다 — 결제창은 한 번에 하나다.
 *
 * 로그아웃·탈퇴는 이 값도 지운다 — 다음 계정이 앞 계정이 있던 방으로 "돌아가기"를 보지 않게. */
const PAYMENT_RETURN_TO_STORAGE_KEY = "ttona.cloverReturnTo";

type PaymentReturnToStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/** 사이트 데이터가 차단된 브라우저에서는 `sessionStorage` 참조 자체가 던진다 — 아래 함수들이 함께 삼킨다. 저장하지
 * 못하면 결제창에서 돌아온 뒤 복귀 링크가 없을 뿐이다. */
function browserStorage(): PaymentReturnToStorage {
  return window.sessionStorage;
}

/** 결제창을 띄우기 직전에 부른다. 복귀 주소가 없으면 앞 결제가 남긴 값을 지운다. */
export function rememberPaymentReturnTo(
  returnTo: string | undefined,
  getStorage: () => PaymentReturnToStorage = browserStorage,
): void {
  try {
    if (returnTo === undefined) getStorage().removeItem(PAYMENT_RETURN_TO_STORAGE_KEY);
    else getStorage().setItem(PAYMENT_RETURN_TO_STORAGE_KEY, returnTo);
  } catch {
    // 못 두면 돌아온 뒤 복귀 링크가 없을 뿐이다.
  }
}

export function readPaymentReturnTo(getStorage: () => PaymentReturnToStorage = browserStorage): string | undefined {
  try {
    return getStorage().getItem(PAYMENT_RETURN_TO_STORAGE_KEY) ?? undefined;
  } catch {
    return undefined;
  }
}

export function clearPaymentReturnTo(getStorage: () => PaymentReturnToStorage = browserStorage): void {
  try {
    getStorage().removeItem(PAYMENT_RETURN_TO_STORAGE_KEY);
  } catch {
    // 못 지운 값은 탭을 닫으면 사라지고, 다음 결제가 덮어쓴다.
  }
}
