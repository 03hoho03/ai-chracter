import type { components } from "@ai-character-chat/api-types";

export type NotificationResponse = components["schemas"]["NotificationResponse"];
export type ReportReasonCategory = components["schemas"]["ReportReasonCategory"];

/** 노벨 소장 화의 클로버를 돌려준 알림. */
export const NOVEL_REFUND_NOTIFICATION_TYPE = "novel-purchase-refund";

/** 노벨 환급 알림의 문장. 소설 제목은 넣지 않는다 — 지운 게시자 글의 사본을 남기지 않는다(어느 소설인지는 클로버
 * 내역의 시각으로 짝지어 본다). 돌려준 화·클로버 수를 모르면(그 구매가 이미 정리됐다) 수 없이 말한다.
 *
 * 문장은 왜 돌려줬는지로 갈린다. 원작이 이용 제한된 것과 지워진 것은 한 문장으로 묶는다 — 열람 종료 안내도 둘을
 * 가르지 않고, 원작이 닫힐 때는 그 원작의 소설 여럿을 한 알림으로 알려 "소장하신 노벨"을 하나로 가리킬 수 없다.
 * 사유가 없거나(사유 칸 이전의 알림) 모르는 값이면 게시자 삭제 문장으로 접는다 — 사유 칸 이전의 환급은 삭제뿐이었다. */
export function toNovelRefundNotificationText(
  refund: NotificationResponse["novelRefund"],
  reason: NotificationResponse["novelRefundReason"],
): { title: string; body: string } {
  const title = "노벨 환급 안내";
  const counts =
    refund === undefined || refund === null
      ? undefined
      : { chapters: refund.chapterCount.toLocaleString(), clovers: refund.cloverAmount.toLocaleString() };
  const spent = counts ? `화 ${counts.chapters}개에 쓰신 클로버 ${counts.clovers}개를` : "화에 쓰신 클로버를";
  switch (reason) {
    case "publisher_withdrawn":
      return { title, body: `게시자가 탈퇴해, 소장하신 ${spent} 돌려드렸어요.` };
    case "novel_restricted":
      return { title, body: `소장하신 노벨이 운영 정책에 따라 이용 제한돼, ${spent} 돌려드렸어요.` };
    case "source_restricted":
    case "source_deleted":
      return { title, body: `원작을 볼 수 없게 돼, 소장하신 ${spent} 돌려드렸어요.` };
    default:
      return counts
        ? { title, body: `게시자가 소장하신 화 ${counts.chapters}개를 지워, 쓰신 클로버 ${counts.clovers}개를 돌려드렸어요.` }
        : { title, body: "게시자가 소장하신 화를 지워, 쓰신 클로버를 돌려드렸어요." };
  }
}
