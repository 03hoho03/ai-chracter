import { Button } from "@ai-character-chat/ui/components/button";
import { RotateCcw } from "lucide-react";

import type { NovelChapterSummary } from "@/entities/novel";

import type { NovelChapterJobFlow } from "../model/useNovelChapterJob";

type RegenerateChapterButtonProps = {
  flow: NovelChapterJobFlow;
  chapter: Pick<NovelChapterSummary, "id" | "ordinal">;
  /** 장 작업 말고 다른 이유(AI 수정 중)로 못 누를 때 그 사유를 말하는 요소. 그 안내는 이 기능 밖에 있어 호출부가
   * 넣어 준다. */
  blockedReasonId?: string;
};

/** 장 하나를 같은 대화로 다시 쓰는 진입점. 마지막 장이 아니어도 된다. 장 머리의 보조 동작이라 윤곽 버튼이다 —
 * 이 화면의 솔리드 채움은 "다음 장 만들기" 하나다.
 *
 * 원래 대화방이 지워진 소설에서는 그리지 않는다. 다시 만들 수 없는 이유는 "다음 장 만들기" 아래 문장이 함께 말한다.
 * 다른 작업이 도는 동안은 `aria-disabled` 이고 사유를 가리킨다 — 장 작업이면 그 진행 줄, 아니면 호출부가 넣어 준
 * 사유. */
export function RegenerateChapterButton({ flow, chapter, blockedReasonId }: RegenerateChapterButtonProps) {
  if (flow.isRoomGone) return null;

  const describedBy = flow.isJobRunning ? flow.statusId : blockedReasonId;

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      aria-disabled={flow.isBusy}
      aria-describedby={flow.isBusy ? describedBy : undefined}
      className="aria-disabled:opacity-65"
      onClick={() => {
        if (flow.isBusy) return;
        void flow.startRegenerate(chapter);
      }}
    >
      <RotateCcw aria-hidden />
      이 장 다시 만들기
    </Button>
  );
}
