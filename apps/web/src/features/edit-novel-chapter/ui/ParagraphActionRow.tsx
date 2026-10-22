import { Button } from "@ai-character-chat/ui/components/button";
import { ImagePlus, Pencil, Sparkles, X } from "lucide-react";
import { useId } from "react";

import {
  NOVEL_ILLUSTRATION_LIMIT,
  type IllustrationPlacement,
  type IllustrationSource,
  type ParagraphAction,
} from "../model/boardIllustrations";
import { IllustrationSourceMenu } from "./IllustrationSourceMenu";

type ParagraphActionRowProps = {
  /** 보일 버튼(`toParagraphActions` — 옮기는 중이 아닐 때). 스위치가 꺼져 있으면 그림 붙이기가 없다. */
  actions: ParagraphAction[];
  isAiBlocked: boolean;
  /** 이 화를 다시 만드는 중인가. 직접 고치기와 그림 붙이기를 막는다. */
  isRegenerating: boolean;
  /** AI 수정·직접 고치기가 막힌 까닭(다시 만드는 중이면 그 문장). */
  blockedReason: string | undefined;
  reasonId: string;
  /** 한 화의 삽화 상한에 닿았는가(위치 확인 필요 포함). */
  isLimitReached: boolean;
  /** 삽화 요청·업로드가 도는 중인가. 같은 판을 기준으로 가므로 그동안 붙이기를 막는다. */
  isAttachBusy: boolean;
  /** 이 줄에서 시작한 붙이기의 진행 문구("올리는 중…"·"붙이는 중…"). */
  attachPendingLabel: string | undefined;
  onAiEdit: () => void;
  onManualEdit: () => void;
  onClearSelection: () => void;
  onAttach: (source: IllustrationSource, placement: IllustrationPlacement) => void;
};

/** 붙이기 버튼이 가리킬 사유 문장. 다시 만드는 중이 먼저다(끝나기를 기다리면 풀리는 쪽이라 상한보다 지금 할 일에 가깝다). */
function toAttachReasonId({
  isRegenerating,
  reasonId,
  isLimitReached,
  limitReasonId,
}: {
  isRegenerating: boolean;
  reasonId: string;
  isLimitReached: boolean;
  limitReasonId: string;
}): string | undefined {
  if (isRegenerating) return reasonId;
  return isLimitReached ? limitReasonId : undefined;
}

/** 고른 범위의 마지막 문단 바로 아래, 문서 흐름 안의 동작 줄 — AI로 고치기·직접 고치기·그림 붙이기·선택 해제. 솔리드 채움
 * 없이 테두리·회색뿐이다(이 화면의 유일한 솔리드는 상단 "다음 화 만들기"). */
export function ParagraphActionRow({
  actions,
  isAiBlocked,
  isRegenerating,
  blockedReason,
  reasonId,
  isLimitReached,
  isAttachBusy,
  attachPendingLabel,
  onAiEdit,
  onManualEdit,
  onClearSelection,
  onAttach,
}: ParagraphActionRowProps) {
  const limitReasonId = useId();
  const isAttachBlocked = isRegenerating || isLimitReached || isAttachBusy;
  const attachDescribedBy = toAttachReasonId({ isRegenerating, reasonId, isLimitReached, limitReasonId });

  return (
    <div className="flex flex-col gap-1.5 py-1">
      <div className="flex flex-wrap gap-2">
        {actions.map((action) => {
          switch (action) {
            case "aiEdit":
              return (
                <Button
                  key={action}
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-disabled={isAiBlocked}
                  aria-describedby={isAiBlocked && blockedReason !== undefined ? reasonId : undefined}
                  className="aria-disabled:opacity-65"
                  onClick={() => {
                    if (isAiBlocked) return;
                    onAiEdit();
                  }}
                >
                  <Sparkles aria-hidden />
                  AI로 고치기
                </Button>
              );
            case "manualEdit":
              return (
                <Button
                  key={action}
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-disabled={isRegenerating}
                  aria-describedby={isRegenerating ? reasonId : undefined}
                  className="aria-disabled:opacity-65"
                  onClick={() => {
                    if (isRegenerating) return;
                    onManualEdit();
                  }}
                >
                  <Pencil aria-hidden />
                  직접 고치기
                </Button>
              );
            case "attach":
              return (
                <IllustrationSourceMenu
                  key={action}
                  label="그림 붙이기"
                  pendingLabel={attachPendingLabel}
                  icon={ImagePlus}
                  variant="outline"
                  isBlocked={isAttachBlocked}
                  describedBy={attachDescribedBy}
                  hasPlacement
                  onPick={onAttach}
                />
              );
            case "clearSelection":
              return (
                <Button key={action} type="button" variant="ghost" size="sm" onClick={onClearSelection}>
                  <X aria-hidden />
                  선택 해제
                </Button>
              );
            default:
              return null;
          }
        })}
      </div>
      {blockedReason !== undefined && (
        <p id={reasonId} className="text-sm break-keep text-muted-foreground">
          {blockedReason}
        </p>
      )}
      {isLimitReached && actions.includes("attach") && (
        <p id={limitReasonId} className="text-sm break-keep text-muted-foreground">
          {`한 화에는 삽화를 ${NOVEL_ILLUSTRATION_LIMIT}장까지 넣을 수 있어요. 다른 삽화를 떼면 넣을 수 있어요.`}
        </p>
      )}
    </div>
  );
}
