import { koreanParticle } from "@/shared/lib/text/koreanParticle";

/** 지우기 전 환급 고지 — 노벨에서 지울 화를 소장한 회원 수와 자동으로 돌려줄 클로버. 소장한 회원이 없으면 `undefined`
 * (상자를 그리지 않는다). `subject` 는 무엇을 소장했는가("이 소설의 화", "3~5화"). 지우는 대신 공개를 거두라고 권하지
 * 않는다 — 소장한 회원에게 불리한 쪽(돌려주지 않음)으로 이끄는 문장이 된다. */
export function toRefundNotice(
  preview: { buyerCount: number; amount: number },
  subject: string,
): [string, string] | undefined {
  if (preview.buyerCount <= 0) return undefined;
  return [
    `노벨에서 ${subject}${koreanParticle(subject, "을/를")} 소장한 회원이 ${preview.buyerCount.toLocaleString()}명 있어요.`,
    `지우면 그 회원들이 쓴 클로버 ${preview.amount.toLocaleString()}개를 자동으로 돌려드리고, 지운 화는 더 볼 수 없게 돼요.`,
  ];
}
