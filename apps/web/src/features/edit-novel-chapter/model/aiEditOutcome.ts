import type { NovelJobResponse } from "@/entities/novel";

export type AiEditOutcome =
  | { kind: "preview" }
  | { kind: "unavailable"; message: string };

/** 성공으로 끝난 AI 수정 작업을 화면이 어떻게 받나. 수정안 본문이 있으면 그 장 아래에 미리보기로 보인다(소설
 * 상세의 미적용 수정안 목록에서 다시 읽는다). 서버가 본문을 비운 성공은 미리보기 없이 까닭만 말한다 — 까닭은
 * 응답의 두 칸으로 갈린다.
 *
 * - 적용 개정이 채워져 있으면 다른 곳(다른 탭·기기)에서 이미 적용했다.
 * - 장이 비어 있으면 그 장(마지막 장)을 지웠다.
 * - 그 밖은 결과가 저장된 뒤 그 장에 새 개정이 생겨(직접 수정·되돌리기·다시 만들기·다른 수정안 적용) 기준이
 *   어긋났다. 이 탭에서 버린 경우도 같은 모양이지만, 버린 탭은 그 작업을 더 지켜보지 않는다. */
export function toAiEditOutcome(job: Pick<NovelJobResponse, "revisionId" | "chapterId" | "aiEdit">): AiEditOutcome {
  if (job.aiEdit?.resultText) return { kind: "preview" };
  if (job.revisionId !== null) {
    return { kind: "unavailable", message: "이 수정안은 다른 곳에서 이미 적용했어요." };
  }
  if (job.chapterId === null) {
    return { kind: "unavailable", message: "장이 지워져 수정안을 쓸 수 없어요." };
  }
  return { kind: "unavailable", message: "그사이 장이 바뀌어 이 수정안은 적용할 수 없어요." };
}
