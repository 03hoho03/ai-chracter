/** 상품 한 줄의 "유료 N + 보너스 M = 총 T" 식에 들어갈 숫자 조각과, 그 식을 말로 읽는 낭독 문장.
 *
 * 숫자는 응답 값 그대로다 — 총량도 화면이 더하지 않고 서버가 준 `totalAmount` 를 쓴다(합을 두 곳에서 계산하면 둘이
 * 갈릴 수 있다). 보너스가 0인 상품도 항을 빼지 않는다: 다섯 행이 같은 식 모양이라야 세로로 견줄 수 있다. 비율("보너스
 * N%")은 쓰지 않는다 — 받는 개수가 식에 다 있고, 비율은 할인처럼 읽힌다.
 *
 * 보이는 식은 기호("+", "=")를 쓰므로 화면 읽기 프로그램에는 숨기고, 같은 사실을 기호 없는 문장으로 따로 읽힌다. */
export type CloverProductLineText = {
  paid: string;
  bonus: string;
  total: string;
  spoken: string;
};

export function describeCloverProductLine(product: {
  paidAmount: number;
  bonusAmount: number;
  totalAmount: number;
}): CloverProductLineText {
  const paid = product.paidAmount.toLocaleString();
  const bonus = product.bonusAmount.toLocaleString();
  const total = product.totalAmount.toLocaleString();
  return { paid, bonus, total, spoken: `유료 클로버 ${paid}개와 보너스 ${bonus}개, 모두 ${total}개` };
}
