import type { components } from "@ai-character-chat/api-types";

export type NotificationResponse = components["schemas"]["NotificationResponse"];
export type ReportReasonCategory = components["schemas"]["ReportReasonCategory"];

/** 노벨 게시자가 소장한 화를 지워 클로버를 돌려준 알림. */
export const NOVEL_REFUND_NOTIFICATION_TYPE = "novel-purchase-refund";

/** 노벨 삭제 환급 알림의 문장. 소설 제목은 넣지 않는다 — 지운 게시자 글의 사본을 남기지 않는다(어느 소설인지는 클로버
 * 내역의 시각으로 짝지어 본다). 돌려준 화·클로버 수를 모르면(그 구매가 이미 정리됐다) 수 없이 말한다. */
export function toNovelRefundNotificationText(
  refund: NotificationResponse["novelRefund"],
): { title: string; body: string } {
  const title = "노벨 환급 안내";
  if (refund === undefined || refund === null) {
    return { title, body: "게시자가 소장하신 화를 지워, 쓰신 클로버를 돌려드렸어요." };
  }
  return {
    title,
    body: `게시자가 소장하신 화 ${refund.chapterCount.toLocaleString()}개를 지워, 쓰신 클로버 ${refund.cloverAmount.toLocaleString()}개를 돌려드렸어요.`,
  };
}
