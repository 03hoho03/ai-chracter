import { z } from "zod";

/** 소설 화면은 장 하나씩 보인다. 어느 장인지는 `?chapter=<장 번호>`(1부터)로 두고, **없으면 마지막 장**이다.
 * 마지막 장을 부재로 두는 이유: 새 장이 생기면 같은 주소가 그 새 장을 가리켜야 한다(번호를 박아 두면 옛 마지막
 * 장에 머문다). 모르는 값·어긋난 값은 `.catch(undefined)`로 부재에 접는다 — 던지면 라우터가 앱 크롬 없는 오류
 * 상자를 띄운다. 라우터가 `?chapter=3` 을 숫자로 파싱하므로 숫자로 받는다. */
export const novelSearchSchema = z.object({
  chapter: z.number().int().positive().optional().catch(undefined),
});

export type NovelSearch = z.infer<typeof novelSearchSchema>;

type ChapterLike = { ordinal: number };

/** 주소의 장 번호를 실제 장으로 편다. 없는 번호(지운 마지막 장, 손으로 고친 주소)와 부재는 마지막 장으로 간다.
 * 장이 하나도 없으면 `undefined`. */
export function resolveSelectedChapter<T extends ChapterLike>(chapters: readonly T[], requested: number | undefined): T | undefined {
  const last = lastChapter(chapters);
  if (requested === undefined) return last;
  return chapters.find((chapter) => chapter.ordinal === requested) ?? last;
}

/** 목차 링크가 주소에 실을 값. 마지막 장이면 부재(`undefined`)로 되돌린다 — 기본값을 주소에 다시 싣지 않는다. */
export function toChapterSearchValue(chapters: readonly ChapterLike[], ordinal: number): number | undefined {
  return lastChapter(chapters)?.ordinal === ordinal ? undefined : ordinal;
}

function lastChapter<T extends ChapterLike>(chapters: readonly T[]): T | undefined {
  let last: T | undefined;
  for (const chapter of chapters) {
    if (last === undefined || chapter.ordinal > last.ordinal) last = chapter;
  }
  return last;
}
