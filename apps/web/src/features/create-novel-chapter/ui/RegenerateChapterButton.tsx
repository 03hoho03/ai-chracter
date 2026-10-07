import { Button } from "@ai-character-chat/ui/components/button";
import { RotateCcw } from "lucide-react";

import { chaptersInBatch, toEpisodeRangeLabel, type NovelChapterSummary } from "@/entities/novel";

import type { NovelChapterJobFlow } from "../model/useNovelChapterJob";

type RegenerateChapterButtonProps = {
  flow: NovelChapterJobFlow;
  chapter: Pick<NovelChapterSummary, "batchId">;
  /** 목차 전체 — 이 화와 함께 다시 만들어지는 화들의 이름을 버튼에 적는 데 쓴다. */
  chapters: Pick<NovelChapterSummary, "batchId" | "ordinal">[];
  /** 장 작업 흐름이 모르는 다른 이유(AI 수정을 준비·요청 중이거나 상세가 아직 그 작업을 싣지 않음)로 못 누르는가.
   * 그 상태는 이 기능 밖에 있어 호출부가 넣어 준다. */
  isBlocked?: boolean;
  /** 장 작업 말고 다른 이유(AI 수정 중)로 못 누를 때 그 사유를 말하는 요소. 그 안내는 이 기능 밖에 있어 호출부가
   * 넣어 준다. */
  blockedReasonId?: string;
};

/** 이 화를 같은 대화로 다시 쓰는 진입점. 마지막 화가 아니어도 된다. 다시 만들기는 한 번에 만든 화들을 함께 새로
 * 쓰므로, 그 화가 여럿이면 라벨이 범위(`1~3화 다시 만들기`)를 말한다 — 누르기 전에 다른 화도 바뀐다는 것을 안다.
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
  if (flow.isRoomGone) return null;

  const batchChapters = chaptersInBatch(chapters, chapter.batchId);
  const first = batchChapters[0];
  const last = batchChapters.at(-1);
  const isDisabled = flow.isBusy || isBlocked;
  const describedBy = flow.isJobRunning ? flow.statusId : blockedReasonId;

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      aria-disabled={isDisabled}
      aria-describedby={isDisabled ? describedBy : undefined}
      className="aria-disabled:opacity-65"
      onClick={() => {
        if (isDisabled) return;
        void flow.startRegenerate(chapter.batchId);
      }}
    >
      <RotateCcw aria-hidden />
      {first !== undefined && last !== undefined && batchChapters.length > 1
        ? `${toEpisodeRangeLabel(first.ordinal, last.ordinal)} 다시 만들기`
        : "이 화 다시 만들기"}
    </Button>
  );
}
