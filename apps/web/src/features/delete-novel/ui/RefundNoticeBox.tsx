import type { NovelPurchaseRefundPreview } from "@/entities/novel";
import { koreanParticle } from "@/shared/lib/text/koreanParticle";

import { toRefundNotice } from "../model/refundNotice";

/** 지우기 확인 모달의 환급 고지 상자. 소설 상세가 준 삭제 전 확인 값으로 그린다 — 받는 중이면 확인 중이라고, 못
 * 받았으면 소장한 회원이 있을 때 돌려준다는 것만 말한다(지우는 길은 막지 않는다). 소장한 회원이 없으면 아무것도 없다.
 * 첫 문장만 본문 잉크다(구매 전 고지 상자와 같은 꼴). */
export function RefundNoticeBox({
  preview,
  scope,
  subject,
}: {
  /** 받는 중이면 `"pending"`, 못 받았으면 `"unknown"`. */
  preview: NovelPurchaseRefundPreview | "pending" | "unknown";
  scope: "novel" | "lastBatch";
  subject: string;
}) {
  if (preview === "pending") {
    return <p className="text-sm break-keep text-muted-foreground">노벨에서 소장한 회원이 있는지 확인하고 있어요…</p>;
  }
  if (preview === "unknown") {
    return (
      <p className="rounded-lg border border-border p-3 text-xs break-keep text-muted-foreground">
        노벨에서 {subject}{koreanParticle(subject, "을/를")} 소장한 회원이 있으면, 지울 때 그 회원들이 쓴 클로버를 자동으로 돌려드려요.
      </p>
    );
  }
  const lines = toRefundNotice(
    scope === "novel"
      ? { buyerCount: preview.novelBuyerCount, amount: preview.novelRefundAmount }
      : { buyerCount: preview.lastBatchBuyerCount, amount: preview.lastBatchRefundAmount },
    subject,
  );
  if (lines === undefined) return null;
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border p-3 text-xs break-keep text-muted-foreground tabular-nums">
      <p className="text-foreground">{lines[0]}</p>
      <p>{lines[1]}</p>
    </div>
  );
}
