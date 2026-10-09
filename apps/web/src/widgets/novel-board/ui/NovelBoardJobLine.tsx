import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Loader2 } from "lucide-react";
import type { RefObject } from "react";

import { NOVEL_ROOM_GONE_MESSAGE, type NovelChapterSummary } from "@/entities/novel";
import { toChainRunningText, type NovelChapterJobFlow } from "@/features/create-novel-chapter";

type NovelBoardJobLineProps = {
  flow: NovelChapterJobFlow;
  /** "다음 화 만들기"를 못 누르는 이유 문장의 id — 상단 바 버튼이 이 문장을 가리킨다. */
  blockedReasonId: string;
  /** 고치던 글이 있어 옮겨 가지 않고 미뤄 둔 새 화. 그 화로 가는 링크를 둔다. */
  heldChapter: NovelChapterSummary | undefined;
  onOpenHeldChapter: (chapter: NovelChapterSummary) => void;
  /** "다시 시도"가 사라지기 전에 포커스를 옮겨 둘 상단 바의 "다음 화 만들기". */
  createButtonRef: RefObject<HTMLButtonElement | null>;
};

/**
 * 편집 보드 패널 맨 위의 작업 줄 — 화 만들기·다시 만들기·남은 대화 한 번에의 진행, 끝난 결과, 실패, "다음 화
 * 만들기"를 못 누르는 이유, 미뤄 둔 새 화로 가는 링크. 버튼은 상단 바에 있고 그 상태는 여기에 있어, 버튼이
 * `aria-describedby` 로 이 줄을 가리킨다. 보일 것이 없으면 아무 면도 차지하지 않는다.
 *
 * - 진행 줄은 언제나 마운트돼 있는 `aria-live` 다 — 조건부로 붙이면 붙는 순간의 문장을 화면 낭독기가 놓친다.
 *   스피너는 진행 표시라 동작 줄이기 설정에서도 돈다.
 * - 실패는 `role="alert"` 상자이고, 다시 시도할 수 있는 실패면 그 안에 버튼을 둔다. 결과 문장은 작업 흐름이 기록한
 *   상태라 상세를 다시 받아도 사라지지 않는다. 새 화에 번쩍이는 강조를 두지 않는다 — 어두운 방에서 갑작스러운 밝기
 *   변화는 놀람이고, 새 화 제목으로 옮긴 포커스가 위치를 알린다.
 */
export function NovelBoardJobLine({
  flow,
  blockedReasonId,
  heldChapter,
  onOpenHeldChapter,
  createButtonRef,
}: NovelBoardJobLineProps) {
  const blockedReason = toBlockedReason(flow);
  const statusText = toStatusText(flow);
  const error = flow.notice?.tone === "error" ? flow.notice : undefined;
  const hasContent = blockedReason !== undefined || statusText !== "" || error !== undefined || heldChapter !== undefined;

  return (
    <div className={cn("flex shrink-0 flex-col gap-2 px-4 sm:px-6", hasContent && "border-b border-border py-3")}>
      <p id={flow.statusId} aria-live="polite" aria-atomic className="flex items-center gap-2 text-sm break-keep text-muted-foreground empty:sr-only">
        {flow.isJobRunning && <Loader2 aria-hidden className="size-4 shrink-0 animate-spin" />}
        {statusText}
      </p>
      {blockedReason !== undefined && (
        <p id={blockedReasonId} className="text-sm break-keep text-muted-foreground">
          {blockedReason}
        </p>
      )}
      {heldChapter !== undefined && (
        <p className="text-sm break-keep text-muted-foreground">
          {heldChapter.ordinal}화가 생겼어요.{" "}
          <button
            type="button"
            className="font-medium text-foreground underline underline-offset-4 outline-none focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring"
            onClick={() => onOpenHeldChapter(heldChapter)}
          >
            보러 가기
          </button>
        </p>
      )}
      {error !== undefined && (
        <div role="alert" className="flex flex-col items-start gap-2 rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
          <p>{error.message}</p>
          {error.retry !== undefined && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-disabled={flow.isBusy}
              className="aria-disabled:opacity-65"
              onClick={() => {
                if (flow.isBusy || error.retry === undefined) return;
                // 다시 시도하면 이 상자가 사라진다 — 누른 버튼과 함께 포커스가 `<body>` 로 떨어지지 않게 남아 있는
                // "다음 화 만들기"로 먼저 옮긴다.
                createButtonRef.current?.focus();
                flow.retry(error.retry);
              }}
            >
              다시 시도
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** "다음 화 만들기"를 못 누르는 이유. 화 작업이 도는 중이면 여기 말고 진행 줄이 그 몫을 진다. */
function toBlockedReason(flow: NovelChapterJobFlow): string | undefined {
  if (flow.isRoomGone) return NOVEL_ROOM_GONE_MESSAGE;
  if (flow.isAiEditRunning) return "AI로 고치는 중이에요. 끝나면 새 화를 만들 수 있어요.";
  return undefined;
}

function toStatusText(flow: NovelChapterJobFlow): string {
  if (flow.isJobRunning) {
    if (flow.hasPollError) return "진행 상황을 확인하지 못하고 있어요. 잠시 뒤 다시 확인할게요.";
    return `${toRunningSubject(flow)} 이 화면을 떠나도 계속 써요.`;
  }
  return flow.notice?.tone === "done" ? flow.notice.message : "";
}

/** 진행 중인 작업이 무엇을 쓰고 있나. 남은 대화 한 번에(연쇄)는 만든 묶음 / 만들 묶음까지 말한다. */
function toRunningSubject(flow: NovelChapterJobFlow): string {
  switch (flow.runningKind) {
    case "chapter_regenerate":
      return `${flow.runningRangeLabel ?? "화"}를 다시 쓰고 있어요.`;
    case "chain_generate":
      return toChainRunningText(flow.chainProgress);
    default:
      return "새 화를 쓰고 있어요.";
  }
}

/** 이유 문장이 지금 있는가 — 상단 바 버튼이 가리킬지 정한다. */
export function hasChapterBlockedReason(flow: NovelChapterJobFlow): boolean {
  return toBlockedReason(flow) !== undefined;
}
