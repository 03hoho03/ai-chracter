import type { AdminNovelChapterEditionItem } from "@/entities/admin-novel";

/** 화 응답의 판 목록(최신순). 응답에 `editions` 칸이 없으면(판을 고를 수 없는 API) 빈 목록이라 판 고르기를 그리지 않는다. */
export function chapterEditions(chapter: {
  editions?: readonly AdminNovelChapterEditionItem[];
}): readonly AdminNovelChapterEditionItem[] {
  return chapter.editions ?? [];
}

/**
 * 고른 판을 서버가 주지 않았는가 — `edition` 쿼리를 모르는 API 는 그 쿼리를 버리고 지금 판을 200 으로 주므로, 요청한 판이 아니라
 * 응답의 `edition` 으로 가른다. 화면은 판을 바꿀 때 직전 판 응답을 자리표시로 들고 있지 않아(그동안 본문은 로딩이다) 응답은 늘
 * 요청한 판의 것이다 — 자리표시를 들게 바꾸면 그동안은 늘 판이 달라 여기서 빼야 한다.
 */
export function isEditionIgnored(requested: number | null, served: number | undefined): boolean {
  return requested !== null && served !== undefined && served !== requested;
}
