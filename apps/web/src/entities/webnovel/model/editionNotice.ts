import { formatKstDate } from "@/shared/lib/time/formatKstDate";

import type { WebnovelChapterResponse } from "../api/useWebnovelChapterQuery";

/** 산 뒤 고쳐진 화를 소장자가 열었을 때 화 제목 아래에 띄울 안내.
 *
 * - `newerAvailable`: 지금 판을 읽는 중 — 산 때의 판으로 읽는 길을 낸다.
 * - `readingPurchased`: 산 때의 판을 읽는 중 — 최신 판으로 돌아가는 길을 낸다.
 *
 * `purchasedEdition` 은 산 때의 판이 지금 판과 다를 때만 서버가 싣고, 산 때의 판을 골라 읽는 중에도 실린다. 그래서
 * 응답의 판이 산 때의 판과 같으면 옛 판을 읽는 중이다. 칸이 없거나 null(스위치 꺼짐·옛 서버·고쳐지지 않은 화)이면
 * 안내가 없다. 공개 날짜는 한국 날짜로 찍는다 — 읽는 사람의 시간대에 따라 날짜가 갈리지 않게. */
export type EditionNotice = {
  kind: "newerAvailable" | "readingPurchased";
  purchasedEdition: number;
  purchasedDateLabel: string;
};

export function toEditionNotice(
  chapter: Pick<WebnovelChapterResponse, "edition" | "purchasedEdition">,
): EditionNotice | undefined {
  const purchased = chapter.purchasedEdition;
  if (purchased === undefined || purchased === null) return undefined;
  return {
    kind: chapter.edition === purchased.edition ? "readingPurchased" : "newerAvailable",
    purchasedEdition: purchased.edition,
    purchasedDateLabel: formatKstDate(purchased.publishedAt),
  };
}
