type ResumableChapter = { id: string; ordinal: number; finishedReading: boolean };

export type ResumeTarget<T extends ResumableChapter> =
  /** 읽은 기록이 없다 — 첫 화부터. */
  | { kind: "start"; chapter: T }
  /** 이어 읽을 화. 읽던 화 그대로(읽던 자리에서)이거나, 읽던 화를 다 읽었으면 그다음 화(처음부터)다. */
  | { kind: "continue"; chapter: T };

/**
 * 작품 정보 화면의 "이어 읽기"가 열 화. 마지막으로 읽던 화를 다 읽었으면 그다음 화 처음으로, 다 읽지 않았으면 그 화로
 * 간다(읽던 자리는 읽기 화면이 저장된 위치로 되살린다). 마지막 화까지 다 읽었으면 다음 화가 없어 그 마지막 화로 간다 —
 * 끝을 다시 보거나 새 화가 생겼는지 확인하러 온 것이라 1화로 되돌리지 않는다.
 *
 * 읽던 화가 그 사이 지워졌으면(마지막 묶음 삭제) 기록이 가리킬 곳이 없다 — 아직 다 읽지 않은 첫 화로, 그것도 없으면
 * 마지막 화로 간다. 화 번호는 `ordinal`(소설 전체 번호)로 판단하고 목록 순서에 기대지 않는다. 화가 없으면
 * `undefined`.
 */
export function toResumeTarget<T extends ResumableChapter>(
  chapters: readonly T[],
  lastReadChapterId: string | undefined,
): ResumeTarget<T> | undefined {
  const ordered = [...chapters].sort((a, b) => a.ordinal - b.ordinal);
  const first = ordered[0];
  const last = ordered.at(-1);
  if (first === undefined || last === undefined) return undefined;
  if (lastReadChapterId === undefined) return { kind: "start", chapter: first };

  const lastRead = ordered.find((chapter) => chapter.id === lastReadChapterId);
  if (lastRead === undefined) {
    return { kind: "continue", chapter: ordered.find((chapter) => !chapter.finishedReading) ?? last };
  }
  if (!lastRead.finishedReading) return { kind: "continue", chapter: lastRead };
  return { kind: "continue", chapter: ordered.find((chapter) => chapter.ordinal > lastRead.ordinal) ?? last };
}
