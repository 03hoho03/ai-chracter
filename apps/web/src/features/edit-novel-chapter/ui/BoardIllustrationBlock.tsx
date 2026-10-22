import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ImageMinus, MoveVertical, Replace, X } from "lucide-react";
import { useId } from "react";

import { CHAPTER_REGENERATING_MESSAGE, NovelIllustrationFigure } from "@/entities/novel";

import type {
  BoardIllustration,
  IllustrationAction,
  IllustrationPlacement,
  IllustrationSource,
} from "../model/boardIllustrations";
import { IllustrationSourceMenu } from "./IllustrationSourceMenu";

type BoardIllustrationBlockProps = {
  ref: (element: HTMLDivElement | null) => void;
  illustration: BoardIllustration;
  paragraphIndex: number;
  placement: IllustrationPlacement;
  /** 그림 묶음의 이름(`toIllustrationLabel`). 아래 버튼들이 어느 그림의 것인지 가른다. */
  label: string;
  /** 보일 조작(`toIllustrationActions`). 비었으면 조작 줄이 없다 — 읽기 화면과 같은 그림만 선다. */
  actions: IllustrationAction[];
  /** 이 그림을 옮기는 중인가. */
  isMoving: boolean;
  /** 삽화 스위치가 켜져 있는가. 내린 그림의 "떼야 다시 공개할 수 있다" 안내가 이 값을 따른다(떼기가 있을 때만 맞는 말). */
  isIllustrationsOn: boolean;
  /** 이 화를 다시 만드는 중인가. 그동안은 조작을 막고 사유를 단다 — 다시 만든 판은 문단이 모두 새것이라 지금 놓은 자리가
   * 곧 사라진다. */
  isRegenerating: boolean;
  /** 같은 판을 기준으로 가는 다른 요청(삽화 요청·업로드·직접 고치기 저장)이 도는 중이거나 새 판을 받는 중인가. 두 요청이 같은
   * 판을 기준으로 가면 뒤의 것이 충돌로 끝난다 — 메뉴가 열려도 고른 출처가 조용히 무시되지 않게 여기서 막는다. */
  isBusy: boolean;
  /** 이 그림에 대해 진행 중인 요청. */
  pendingAction: IllustrationAction | undefined;
  /** 이 그림을 바꾸는 중의 진행 문구("올리는 중…"·"바꾸는 중…"). 그동안 옛 그림은 그대로 서 있다. */
  replacePendingLabel: string | undefined;
  onMove: () => void;
  onCancelMove: () => void;
  onReplace: (source: IllustrationSource) => void;
  onDetach: () => void;
};

/**
 * 보드 본문의 문단 사이 그림 한 장 — 읽기 화면 스크롤 모드와 같은 그림 블록(페이지 배경 위라 `muted` 웰), 그 아래 고치기
 * 모드에서만 작은 조작 줄(옮기기·바꾸기·떼기). 바꾸기는 붙이기와 같은 출처 셋의 메뉴다. 조작은 `ghost` 다 — 이 화면의 유일한 솔리드 채움은 상단 "다음 화 만들기"다.
 *
 * 옮기는 중이면 고른 문단과 같은 문법(회색 면 + 안쪽 무채색 윤곽)으로 표시한다. 상자의 안쪽 여백·음수 바깥 여백은 늘 같아
 * 표시가 켜지고 꺼져도 그림이 움직이지 않는다. 성공한 옮기기 뒤 포커스를 받으려고 `tabIndex=-1` 이다.
 */
export function BoardIllustrationBlock({
  ref,
  illustration,
  paragraphIndex,
  placement,
  label,
  actions,
  isMoving,
  isIllustrationsOn,
  isRegenerating,
  isBusy,
  pendingAction,
  replacePendingLabel,
  onMove,
  onCancelMove,
  onReplace,
  onDetach,
}: BoardIllustrationBlockProps) {
  const reasonId = useId();
  const isBlocked = isBusy || isRegenerating;
  const isTakenDown = illustration.withheld === "taken_down";

  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="group"
      aria-label={label}
      className={cn(
        "-mx-2 flex flex-col gap-1.5 rounded-md px-2 py-1 outline-none focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50",
        isMoving && "bg-secondary inset-ring-1 inset-ring-input",
      )}
    >
      <NovelIllustrationFigure illustration={{ ...illustration, paragraphIndex, placement }} surface="muted" />
      {isIllustrationsOn && isTakenDown && (
        <p className="text-xs break-keep text-muted-foreground">이 삽화를 바꾸거나 떼야 이 화를 다시 공개할 수 있어요.</p>
      )}
      {actions.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {actions.includes("move") &&
            (isMoving ? (
              <Button type="button" variant="ghost" size="sm" onClick={onCancelMove}>
                <X aria-hidden />
                옮기기 취소
              </Button>
            ) : (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-disabled={isBlocked}
                aria-describedby={isRegenerating ? reasonId : undefined}
                className="aria-disabled:opacity-65"
                onClick={() => {
                  if (isBlocked) return;
                  onMove();
                }}
              >
                <MoveVertical aria-hidden />
                {pendingAction === "move" ? "옮기는 중…" : "옮기기"}
              </Button>
            ))}
          {actions.includes("replace") && (
            <IllustrationSourceMenu
              label="바꾸기"
              pendingLabel={replacePendingLabel}
              icon={Replace}
              variant="ghost"
              isBlocked={isBlocked}
              describedBy={isRegenerating ? reasonId : undefined}
              hasPlacement={false}
              onPick={(source) => onReplace(source)}
            />
          )}
          {actions.includes("detach") && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-disabled={isBlocked}
              aria-describedby={isRegenerating ? reasonId : undefined}
              className="aria-disabled:opacity-65"
              onClick={() => {
                if (isBlocked) return;
                onDetach();
              }}
            >
              <ImageMinus aria-hidden />
              {pendingAction === "detach" ? "떼는 중…" : "떼기"}
            </Button>
          )}
        </div>
      )}
      {actions.length > 0 && isRegenerating && (
        <p id={reasonId} className="text-xs break-keep text-muted-foreground">
          {CHAPTER_REGENERATING_MESSAGE}
        </p>
      )}
    </div>
  );
}
