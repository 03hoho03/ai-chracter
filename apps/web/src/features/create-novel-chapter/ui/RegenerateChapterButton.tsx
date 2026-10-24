import { Button } from "@ai-character-chat/ui/components/button";
import { RotateCcw } from "lucide-react";
import { useId } from "react";

import { chaptersInBatch, toEpisodeRangeLabel, type NovelChapterSummary } from "@/entities/novel";

import { toRegenerateAction } from "../model/regenerateAction";
import type { NovelChapterJobFlow } from "../model/useNovelChapterJob";

type RegenerateChapterButtonProps = {
  flow: NovelChapterJobFlow;
  /** 다시 만들 화. 구성안으로 쓴 화(`episodeOutlineId`)는 그 화 하나를 같은 장면 구성안으로 다시 쓴다. */
  chapter: Pick<NovelChapterSummary, "id" | "batchId"> & Partial<Pick<NovelChapterSummary, "episodeOutlineId">>;
  /** 목차 전체 — 이 화와 함께 다시 만들어지는 화들의 이름을 버튼에 적는 데 쓴다. */
  chapters: Pick<NovelChapterSummary, "batchId" | "ordinal">[];
  /** 장 작업 흐름이 모르는 다른 이유(AI 수정을 준비·요청 중이거나 상세가 아직 그 작업을 싣지 않음)로 못 누르는가.
   * 그 상태는 이 기능 밖에 있어 호출부가 넣어 준다. */
  isBlocked?: boolean;
  /** 장 작업 말고 다른 이유(AI 수정 중)로 못 누를 때 그 사유를 말하는 요소. 그 안내는 이 기능 밖에 있어 호출부가
   * 넣어 준다. */
  blockedReasonId?: string;
};

/** 이 화를 다시 쓰는 진입점. 마지막 화가 아니어도 된다. 대화로 바로 만든 화는 한 번에 만든 화들(묶음)을 함께 새로 쓰므로, 그 화가
 * 여럿이면 라벨이 범위(`1~3화 다시 만들기`)를 말한다 — 누르기 전에 다른 화도 바뀐다는 것을 안다. 구성안으로 쓴 화는 그 화 하나를 같은
 * 장면 구성안으로 새로 쓰고(서버가 두 종류를 서로 다른 라우트로 받는다), 구성 흐름 스위치가 꺼져 있으면 어느 라우트로도 다시 만들 수
 * 없어 `aria-disabled` 와 이유 한 줄을 단다. 읽기·직접 고치기·AI 수정은 그대로다.
 * 화 머리의 보조 동작이라 윤곽 버튼이다 — 이 화면의 솔리드 채움은 "다음 화 만들기" 하나다.
 *
 * 원래 대화방이 지워진 소설에서는 그리지 않는다. 다시 만들 수 없는 이유는 "다음 화 만들기" 아래 문장이 함께 말한다.
 * 다른 작업이 도는 동안은 `aria-disabled` 이고 사유를 가리킨다 — 장 작업이면 그 진행 줄, 아니면 호출부가 넣어 준
 * 사유. */
export function RegenerateChapterButton({
  flow,
  chapter,
  chapters,
  isBlocked = false,
  blockedReasonId,
}: RegenerateChapterButtonProps) {
  const unavailableReasonId = useId();
  if (flow.isRoomGone) return null;

  const action = toRegenerateAction(chapter, flow.outlineFlow);
  const batchChapters = chaptersInBatch(chapters, chapter.batchId);
  const first = batchChapters[0];
  const last = batchChapters.at(-1);
  const isUnavailable = action.kind === "unavailable";
  const isDisabled = flow.isBusy || isBlocked || isUnavailable;
  const unavailableReason = action.kind === "unavailable" ? action.reason : undefined;
  const describedBy = toDescribedBy({
    isJobRunning: flow.isJobRunning,
    statusId: flow.statusId,
    blockedReasonId,
    unavailableReasonId: unavailableReason === undefined ? undefined : unavailableReasonId,
  });

  const button = (
    <Button
      type="button"
      variant="outline"
      size="sm"
      aria-disabled={isDisabled}
      aria-describedby={isDisabled ? describedBy : undefined}
      className="aria-disabled:opacity-65"
      onClick={() => {
        if (isDisabled) return;
        if (action.kind === "outline") void flow.startOutlineRegenerate(action.chapterId);
        else if (action.kind === "batch") void flow.startRegenerate(action.batchId);
      }}
    >
      <RotateCcw aria-hidden />
      {first !== undefined && last !== undefined && batchChapters.length > 1
        ? `${toEpisodeRangeLabel(first.ordinal, last.ordinal)} 다시 만들기`
        : "이 화 다시 만들기"}
    </Button>
  );
  if (unavailableReason === undefined) return button;
  return (
    <div className="flex flex-col items-start gap-1.5">
      {button}
      <p id={unavailableReasonId} className="text-xs break-keep text-muted-foreground">
        {unavailableReason}
      </p>
    </div>
  );
}

/** 못 누를 때 가리킬 사유. 장 작업이 돌면 그 진행 줄, 아니면 호출부의 사유, 그다음이 구성 흐름이 꺼진 이유다. */
function toDescribedBy(ids: {
  isJobRunning: boolean;
  statusId: string;
  blockedReasonId: string | undefined;
  unavailableReasonId: string | undefined;
}): string | undefined {
  if (ids.isJobRunning) return ids.statusId;
  return ids.blockedReasonId ?? ids.unavailableReasonId;
}
