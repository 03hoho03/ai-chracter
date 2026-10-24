import { isBlockEditJob, type NovelJobResponse } from "@/entities/novel";

export type AiEditOutcome =
  | { kind: "preview" }
  | { kind: "patches" }
  | { kind: "unavailable"; message: string };

/** 성공으로 끝난 AI 수정 작업을 화면이 어떻게 받나. 수정안 본문이 있으면 그 장 아래에 미리보기로 보인다(소설
 * 상세의 미적용 수정안 목록에서 다시 읽는다). 서버가 본문을 비운 성공은 미리보기 없이 까닭만 말한다 — 까닭은
 * 응답의 두 칸으로 갈린다.
 *
 * 여러 문단 수정 작업은 장 전체 결과 본문을 늘 비운다 — 수정안은 블록마다 상세의 여러 문단 수정 목록에 있다. 그래서 본문이
 * 없다는 까닭 판정보다 먼저 가른다(가르지 않으면 성공한 작업을 "화가 바뀌었다"고 알린다).
 *
 * - 적용 개정이 채워져 있으면 다른 곳(다른 탭·기기)에서 이미 적용했다.
 * - 장이 비어 있으면 그 장(마지막 장)을 지웠다.
 * - 그 밖은 결과가 저장된 뒤 그 장에 새 개정이 생겨(직접 수정·되돌리기·다시 만들기·다른 수정안 적용) 기준이
 *   어긋났다. 이 탭에서 버린 경우도 같은 모양이지만, 버린 탭은 그 작업을 더 지켜보지 않는다. */
export function toAiEditOutcome(job: Pick<NovelJobResponse, "revisionId" | "chapterId" | "aiEdit">): AiEditOutcome {
  if (isBlockEditJob({ kind: "ai_edit", aiEdit: job.aiEdit })) return { kind: "patches" };
  if (job.aiEdit?.resultText) return { kind: "preview" };
  if (job.revisionId !== null) {
    return { kind: "unavailable", message: "이 수정안은 다른 곳에서 이미 적용했어요." };
  }
  if (job.chapterId === null) {
    return { kind: "unavailable", message: "화가 지워져 수정안을 쓸 수 없어요." };
  }
  return { kind: "unavailable", message: "그사이 화가 바뀌어 이 수정안은 적용할 수 없어요." };
}

/** 여러 문단 수정 작업이 끝난 순간의 안내. `freshCount` 는 다시 받은 상세에서 그 작업의 지금 쓸 수 있는 수정안 수다 —
 * 모델이 고칠 곳이 없다고 했거나 그사이 고른 문단이 바뀌어 하나도 없을 수 있다. */
export function toBlockEditArrivedMessage(chapterOrdinal: number | undefined, freshCount: number): string {
  const where = chapterOrdinal === undefined ? "" : `${chapterOrdinal}화 `;
  if (freshCount === 0) return `${where}수정안이 왔지만 지금 적용할 수 있는 수정안이 없어요.`;
  return `${where}수정안 ${freshCount}개가 왔어요. 고른 문단 자리에서 적용하거나 버릴 수 있어요.`;
}
