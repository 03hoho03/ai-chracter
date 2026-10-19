import { formatKstDate } from "@/shared/lib/time/formatKstDate";

import type { WebnovelChapterResponse } from "../api/useWebnovelChapterQuery";

/** 판 하나 — 번호, 공개 날짜(한국 날짜), 작가가 그 판을 낼 때 쓴 변경 요약. 요약이 없으면(첫 판·요약을 받기 전에 낸 판)
 * `undefined` 라 그 자리를 그리지 않는다. */
export type EditionInfo = {
  edition: number;
  dateLabel: string;
  summary: string | undefined;
};

/** 산 뒤 고쳐진 화를 소장자가 열었을 때 화 제목 아래에 띄울 안내.
 *
 * - `newerAvailable`: 지금 판을 읽는 중 — 구매 당시 판으로 읽는 길을 낸다.
 * - `readingPurchased`: 구매 당시 판을 읽는 중 — 최신 판으로 돌아가는 길을 낸다.
 *
 * `purchasedEdition` 은 구매 당시 판이 지금 판과 다를 때만 서버가 싣고, 구매 당시 판을 골라 읽는 중에도 실린다. 그래서
 * 응답의 판이 구매 당시 판과 같으면 옛 판을 읽는 중이다. 칸이 없거나 null(스위치 꺼짐·옛 서버·고쳐지지 않은 화)이면
 * 안내가 없다. `latestEdition` 은 그때 함께 오는 최신 판이다 — 이 칸을 모르는 옛 서버면 `latest` 가 없고, 화면은 두 판의
 * 날짜·요약을 보여 줄 수 없어 지금 한 줄만 그린다. 공개 날짜는 한국 날짜로 찍는다 — 읽는 사람의 시간대에 따라 날짜가
 * 갈리지 않게. */
export type EditionNotice = {
  kind: "newerAvailable" | "readingPurchased";
  purchased: EditionInfo;
  latest: EditionInfo | undefined;
};

export function toEditionNotice(
  chapter: Pick<WebnovelChapterResponse, "edition" | "purchasedEdition" | "latestEdition">,
): EditionNotice | undefined {
  const purchased = chapter.purchasedEdition;
  if (purchased === undefined || purchased === null) return undefined;
  const latest = chapter.latestEdition;
  return {
    kind: chapter.edition === purchased.edition ? "readingPurchased" : "newerAvailable",
    purchased: toEditionInfo(purchased),
    latest: latest === undefined || latest === null ? undefined : toEditionInfo(latest),
  };
}

function toEditionInfo(edition: NonNullable<WebnovelChapterResponse["purchasedEdition"]>): EditionInfo {
  const summary = edition.changeSummary?.trim();
  return {
    edition: edition.edition,
    dateLabel: formatKstDate(edition.publishedAt),
    summary: summary === undefined || summary === "" ? undefined : summary,
  };
}
