type OrderedChapter = { ordinal: number };

/**
 * 화 하나의 앞뒤 화. 화 번호(`ordinal`, 소설 전체에서 1부터 이어진다)로 찾고 목록 순서에 기대지 않는다 —
 * `episodeIndex` 는 한 번에 만든 묶음 안의 순번이라 묶음마다 0부터 다시 시작해 앞뒤 판정에 쓸 수 없다. 첫 화의 앞, 마지막
 * 화의 뒤는 `undefined`.
 */
export function toAdjacentChapters<T extends OrderedChapter>(
  chapters: readonly T[],
  ordinal: number,
): { previous: T | undefined; next: T | undefined } {
  let previous: T | undefined;
  let next: T | undefined;
  for (const chapter of chapters) {
    if (chapter.ordinal < ordinal && (previous === undefined || chapter.ordinal > previous.ordinal)) previous = chapter;
    if (chapter.ordinal > ordinal && (next === undefined || chapter.ordinal < next.ordinal)) next = chapter;
  }
  return { previous, next };
}
