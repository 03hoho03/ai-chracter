import type { NovelChapterSummary } from "../api/useNovelQuery";

/** 화 번호 범위의 이름 — 한 화면 `3화`, 여럿이면 `3~5화`. 한 번에 만들고 다시 만들고 지우는 단위가 여러 화일 수
 * 있어, 그 동작이 어느 화들에 걸리는지를 문장·버튼에 그대로 적는다. 뒤에 붙는 조사는 언제나 `화` 에 맞춘다
 * (`를`·`가`·`는`). */
export function toEpisodeRangeLabel(first: number, last: number): string {
  return last > first ? `${first}~${last}화` : `${first}화`;
}

/** 같은 묶음(한 번에 만든 화들)에 든 화를 화 번호 순으로. */
export function chaptersInBatch<T extends Pick<NovelChapterSummary, "batchId" | "ordinal">>(
  chapters: readonly T[],
  batchId: string,
): T[] {
  return chapters.filter((chapter) => chapter.batchId === batchId).sort((a, b) => a.ordinal - b.ordinal);
}

/** 묶음에 든 화들의 범위 이름. 화가 없으면(상세가 낡았을 때) `undefined`. */
export function toBatchRangeLabel(
  chapters: readonly Pick<NovelChapterSummary, "batchId" | "ordinal">[],
  batchId: string,
): string | undefined {
  const inBatch = chaptersInBatch(chapters, batchId);
  const first = inBatch[0];
  const last = inBatch.at(-1);
  if (first === undefined || last === undefined) return undefined;
  return toEpisodeRangeLabel(first.ordinal, last.ordinal);
}
