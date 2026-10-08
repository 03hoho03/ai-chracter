type ReadableChapter = { ordinal: number; finishedReading: boolean };

export type NovelReadProgress = {
  /** 다 읽은 화 수. */
  finishedCount: number;
  totalCount: number;
  /** 다 읽은 화 수 ÷ 전체 화 수(0 … 1). 화가 없으면 0. */
  ratio: number;
  /** 다 읽은 화 가운데 가장 뒤 화의 번호. 다 읽은 화가 없으면 `undefined`. */
  lastFinishedOrdinal: number | undefined;
};

/** 작품 전체 진행률 — 작품 정보 화면의 목차 머리와 읽기 화면의 목차 시트가 같은 값을 보인다. 순서대로 읽지 않았을
 * 수 있어(목차에서 건너뛰기) 다 읽은 화 수와 "몇 화까지"를 따로 센다. */
export function toNovelReadProgress(chapters: readonly ReadableChapter[]): NovelReadProgress {
  let finishedCount = 0;
  let lastFinishedOrdinal: number | undefined;
  for (const chapter of chapters) {
    if (!chapter.finishedReading) continue;
    finishedCount += 1;
    if (lastFinishedOrdinal === undefined || chapter.ordinal > lastFinishedOrdinal) lastFinishedOrdinal = chapter.ordinal;
  }
  const totalCount = chapters.length;
  return {
    finishedCount,
    totalCount,
    ratio: totalCount === 0 ? 0 : finishedCount / totalCount,
    lastFinishedOrdinal,
  };
}
