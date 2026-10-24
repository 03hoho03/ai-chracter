import type { components } from "@ai-character-chat/api-types";

import type { NovelJobResponse } from "../api/useNovelJobQuery";
import type { NovelDetailResponse } from "../api/useNovelQuery";

export type NovelPendingBlockEdit = components["schemas"]["NovelPendingBlockEdit"];
export type NovelBlockEditPatch = components["schemas"]["NovelBlockEditPatchView"];
export type NovelBlockEditBundle = components["schemas"]["NovelBlockEditBundleView"];
export type NovelRevisionScene = components["schemas"]["NovelRevisionScene"];

type WithBlockEdits = Partial<Pick<NovelDetailResponse, "pendingBlockEdits">>;

function hasPendingPatch(edit: NovelPendingBlockEdit): boolean {
  return edit.patches.some((patch) => patch.state === "pending");
}

/** 상세의 여러 문단 수정 작업(본문 차례의 블록별 수정안). 생성 타입에서 칸이 선택이라(이 칸을 모르는 응답·시험 픽스처) 없으면
 * 빈 목록이다. 대기 수정안이 하나도 없는 작업은 뺀다 — 서버 목록과 같은 조건이고, 캐시에서 적용·버린 단위를 뺀 뒤 남는 껍데기가
 * 이것이다. `chapterId` 를 주면 그 화의 작업만. */
export function toPendingBlockEdits(novel: WithBlockEdits, chapterId?: string): NovelPendingBlockEdit[] {
  return (novel.pendingBlockEdits ?? []).filter(
    (edit) => (chapterId === undefined || edit.chapterId === chapterId) && hasPendingPatch(edit),
  );
}

/** 그 화들에 적용하지 않은 여러 문단 수정안이 있는가. */
export function hasPendingBlockEdits(novel: WithBlockEdits, chapterIds: ReadonlySet<string>): boolean {
  return toPendingBlockEdits(novel).some((edit) => chapterIds.has(edit.chapterId));
}

/** 그 화들에 적용하지 않은 AI 수정안(옛 연속 범위·여러 문단)이 있는가 — 다시 만들기·되돌리기 경고와 보드 카드 표시가 쓴다. */
export function hasPendingEdits(
  novel: Pick<NovelDetailResponse, "pendingAiEdits"> & WithBlockEdits,
  chapterIds: ReadonlySet<string>,
): boolean {
  return novel.pendingAiEdits.some((edit) => chapterIds.has(edit.chapterId)) || hasPendingBlockEdits(novel, chapterIds);
}

/** 한 작업의 수정안 몇 개(`"all"` 이면 남은 대기·낡음 전부)를 적용·버림으로 바꾼 목록 — 서버의 상태 전이와 같다(문단을
 * 비우고 상태만 남긴다). 대기 수정안이 없어진 작업은 뺀다. 칸이 없던 상세는 그대로 둔다. */
export function withSettledPatches(
  edits: NovelPendingBlockEdit[] | undefined,
  jobId: string,
  patchIds: readonly string[] | "all",
  state: "applied" | "dismissed",
): NovelPendingBlockEdit[] | undefined {
  if (edits === undefined) return undefined;
  const isTarget = (patch: NovelBlockEditPatch) =>
    patchIds === "all" ? patch.state === "pending" || patch.state === "stale" : patchIds.includes(patch.id);
  return edits
    .map((edit) =>
      edit.id === jobId
        ? {
            ...edit,
            patches: edit.patches.map((patch) => (isTarget(patch) ? { ...patch, state, paragraphs: null } : patch)),
          }
        : edit,
    )
    .filter(hasPendingPatch);
}

/** 적용이 낡음으로 거절된 수정안(`stalePatchIds`)을 지금 쓸 수 없음으로 바꾼 목록. 다시 받기 전에도 그 카드가 적용 버튼을 거둔다. */
export function withStalePatches(
  edits: NovelPendingBlockEdit[] | undefined,
  patchIds: readonly string[],
): NovelPendingBlockEdit[] | undefined {
  if (edits === undefined) return undefined;
  return edits.map((edit) => ({
    ...edit,
    patches: edit.patches.map((patch) => (patchIds.includes(patch.id) ? { ...patch, fresh: false } : patch)),
  }));
}

/** 작업이 여러 문단 수정(블록별 수정안)인가. 종류는 옛 연속 범위 수정과 같은 `ai_edit` 이지만, 서버가 여러 문단 수정 작업의
 * 문단 범위 칸을 늘 비우고 옛 수정은 늘 채운다(DB 제약) — 그래서 범위가 비었는지로 가른다. 다른 탭에서 시작한 작업도 같다. */
export function isBlockEditJob(job: Pick<NovelJobResponse, "kind" | "aiEdit">): boolean {
  return job.kind === "ai_edit" && job.aiEdit !== null && job.aiEdit.paragraphStart === null;
}
