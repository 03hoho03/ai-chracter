import type { NovelPurchaseRefundPreview } from "@/entities/novel";
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

/** 판매된 소설 지우기 안내 — 노벨에서 이 소설을 소장한 회원이 있으면 서버는 지우지 않고 숨긴다(소장한 회원은 계속
 * 읽고, 클로버는 돌려주지 않는다). 그때 확인 모달의 설명을 갈아 끼울 문장이다. 판매 표시가 없거나 거짓(정책 스위치
 * 꺼짐·옛 서버)이면 `undefined` — 지금의 지우기 설명과 환급 고지를 그대로 쓴다. */
export function toNovelHideDescription(
  preview: Pick<NovelPurchaseRefundPreview, "novelSold" | "novelBuyerCount"> | undefined,
): string | undefined {
  if (preview?.novelSold !== true) return undefined;
  return `노벨에서 이 소설을 소장한 회원이 ${preview.novelBuyerCount.toLocaleString()}명 있어 바로 지우지 않고 숨겨요. 내 소설과 노벨에서 사라지고 다시 고치거나 공개할 수 없어요. 소장한 회원은 산 화를 계속 읽고, 소장한 회원이 모두 없어지면 완전히 지워져요. 원래 대화방에서는 새 소설을 만들 수 있어요.`;
}

/** 노벨에서 마지막 묶음 화를 소장한 회원이 있어 그 묶음을 지울 수 없는가. 판매 표시가 없으면(꺼짐·옛 서버) 거짓이다. */
export function isLastBatchSold(preview: Pick<NovelPurchaseRefundPreview, "lastBatchSold"> | undefined): boolean {
  return preview?.lastBatchSold === true;
}

/** 판매된 마지막 묶음을 지울 수 없는 이유 — 보드 패널의 사유 줄과 지우기 확인 모달이 같은 문장을 쓴다. */
export const LAST_BATCH_SOLD_REASON = "노벨에서 소장한 회원이 있는 화라 지울 수 없어요.";

/** 삭제 전 확인 값(소설 상세)을 받지 못했을 때 지우기를 막고 다시 받게 하는가. 정책 스위치(가격 응답의
 * `novelPublicPolicyV2Enabled`)가 켜져 있으면 판매된 소설은 지워지지 않고 숨겨지며(클로버를 돌려주지 않는다) 판매된
 * 마지막 묶음은 지울 수 없어, 확인 값 없이는 맞는 안내를 할 수 없다. 꺼져 있거나 가격을 아직 못 받았으면 거짓 —
 * 지금처럼 "소장한 회원이 있으면 돌려드려요"로 말하고 지우게 둔다. */
export function isPreviewRequiredToDelete(pricing: { novelPublicPolicyV2Enabled?: boolean } | undefined): boolean {
  return pricing?.novelPublicPolicyV2Enabled === true;
}
