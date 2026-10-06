import { Loader2 } from "lucide-react";

import type { NovelAiEditFlow } from "../model/useNovelAiEdit";

type AiEditStatusProps = {
  aiEdit: NovelAiEditFlow;
};

/** AI 수정의 진행 안내와 장 고치기(AI 수정·직접 고치기·되돌리기)의 결과 안내. 진행 줄과 결과 줄은 언제나 마운트된
 * `aria-live` 이고(붙는 순간의 문장을 화면 낭독기가 놓치지 않게), 스피너는 진행 표시라 동작 줄이기 설정에서도 돈다.
 * 실패·거절은 `role="alert"` 상자다. 결과 문장은 훅이 일이 끝난 순간 기록한 상태라 상세를 다시 받아도 사라지지
 * 않는다. 진행 줄과 결과 줄을 나눈 것은 AI 수정이 도는 동안에도 직접 고치기 같은 다른 동작의 결과가 보여야 해서다.
 * 어느 장을 보고 있든 같은 자리(장 머리 아래)에 보인다 — 진행 중인 작업이 다른 장의 것이면 그 장 번호를 말한다. */
export function AiEditStatus({ aiEdit }: AiEditStatusProps) {
  const notice = aiEdit.notice;

  return (
    <>
      <p
        id={aiEdit.statusId}
        aria-live="polite"
        aria-atomic
        className="flex items-center gap-2 text-sm break-keep text-muted-foreground empty:sr-only"
      >
        {aiEdit.isRunning && <Loader2 aria-hidden className="size-4 shrink-0 animate-spin" />}
        {toProgressText(aiEdit) || null}
      </p>
      <p aria-live="polite" aria-atomic className="text-sm break-keep text-muted-foreground empty:sr-only">
        {notice?.tone === "info" ? notice.message : null}
      </p>
      {notice?.tone === "error" && (
        <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
          {notice.message}
        </p>
      )}
    </>
  );
}

function toProgressText(aiEdit: NovelAiEditFlow): string {
  if (!aiEdit.isRunning) return "";
  if (aiEdit.hasPollError) return "진행 상황을 확인하지 못하고 있어요. 잠시 뒤 다시 확인할게요.";
  const where = aiEdit.runningChapterOrdinal === undefined ? "" : `${aiEdit.runningChapterOrdinal}장 `;
  return `${where}수정안을 만들고 있어요. 이 화면을 떠나도 계속 만들어요.`;
}
