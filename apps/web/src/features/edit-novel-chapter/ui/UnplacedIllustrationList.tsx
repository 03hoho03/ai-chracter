import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ImageMinus, ImageOff, MoveVertical, X } from "lucide-react";
import { useId } from "react";

import { CHAPTER_REGENERATING_MESSAGE } from "@/entities/novel";

import type { BoardIllustration } from "../model/boardIllustrations";

type UnplacedIllustrationListProps = {
  illustrations: readonly BoardIllustration[];
  /** 지금 놓을 자리를 고르는 그림의 id. */
  movingId: string | undefined;
  isRegenerating: boolean;
  isBusy: boolean;
  /** 진행 중인 떼기 요청의 그림 id. */
  detachingId: string | undefined;
  rowRef: (id: string, element: HTMLDivElement | null) => void;
  onPlace: (illustration: BoardIllustration) => void;
  onCancelMove: () => void;
  onDetach: (illustration: BoardIllustration) => void;
};

const WITHHELD_LABEL: Record<NonNullable<BoardIllustration["withheld"]>, string> = {
  taken_down: "운영 정책에 따라 내린 그림",
  original_restricted: "원작이 이용 제한 중인 그림",
};

/**
 * 위치 확인 필요 — 문단이 바뀌어(직접 수정·AI 수정·다시 만들기로 그 문단이 사라져) 자리를 잃은 삽화. 독자에게는 보이지
 * 않는다는 경고라 고치기 모드가 아니어도 본문 위에 선다. 항목마다 작은 썸네일과 `놓기`(고치기 모드를 켜고 본문에서 놓을
 * 문단을 고른다)·`떼기`. 페이지 배경 위의 테두리 상자 하나라 썸네일 웰은 `muted` 다.
 */
export function UnplacedIllustrationList({
  illustrations,
  movingId,
  isRegenerating,
  isBusy,
  detachingId,
  rowRef,
  onPlace,
  onCancelMove,
  onDetach,
}: UnplacedIllustrationListProps) {
  const headingId = useId();
  const reasonId = useId();
  const isBlocked = isBusy || isRegenerating;

  return (
    <section
      aria-labelledby={headingId}
      className="flex max-w-prose flex-col gap-2 rounded-lg border border-border p-3"
    >
      <h3 id={headingId} className="text-sm font-semibold text-foreground tabular-nums">
        위치 확인 필요 삽화 {illustrations.length}장
      </h3>
      <p className="text-xs break-keep text-muted-foreground">
        문단이 바뀌어 자리를 잃은 삽화예요. 독자에게는 보이지 않아요. 놓을 문단을 고르거나 떼 주세요.
      </p>
      <ul className="flex flex-col gap-1">
        {illustrations.map((illustration, index) => {
          const isMoving = illustration.id === movingId;
          const name = `위치 확인 필요 삽화 ${index + 1}`;
          return (
            <li key={illustration.id}>
              <div
                ref={(element) => rowRef(illustration.id, element)}
                tabIndex={-1}
                role="group"
                aria-label={name}
                className={cn(
                  "-mx-1.5 flex flex-wrap items-center gap-3 rounded-md px-1.5 py-1.5 outline-none focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50",
                  isMoving && "bg-secondary inset-ring-1 inset-ring-input",
                )}
              >
                {illustration.url === null ? (
                  <span aria-hidden className="flex size-12 shrink-0 items-center justify-center rounded-md bg-muted">
                    <ImageOff className="size-4 text-muted-foreground" />
                  </span>
                ) : (
                  <img
                    src={illustration.url}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    draggable={false}
                    className="size-12 shrink-0 rounded-md bg-muted object-contain"
                  />
                )}
                <span className="flex min-w-0 flex-1 flex-col text-sm break-keep">
                  <span className="text-foreground tabular-nums">삽화 {index + 1}</span>
                  {illustration.withheld !== null && (
                    <span className="text-xs text-muted-foreground">{WITHHELD_LABEL[illustration.withheld]}</span>
                  )}
                </span>
                <span className="flex gap-1">
                  {isMoving ? (
                    <Button type="button" variant="ghost" size="sm" onClick={onCancelMove}>
                      <X aria-hidden />
                      놓기 취소
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
                        onPlace(illustration);
                      }}
                    >
                      <MoveVertical aria-hidden />
                      놓기
                    </Button>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-disabled={isBlocked}
                    aria-describedby={isRegenerating ? reasonId : undefined}
                    className="aria-disabled:opacity-65"
                    onClick={() => {
                      if (isBlocked) return;
                      onDetach(illustration);
                    }}
                  >
                    <ImageMinus aria-hidden />
                    {detachingId === illustration.id ? "떼는 중…" : "떼기"}
                  </Button>
                </span>
              </div>
            </li>
          );
        })}
      </ul>
      {isRegenerating && (
        <p id={reasonId} className="text-xs break-keep text-muted-foreground">
          {CHAPTER_REGENERATING_MESSAGE}
        </p>
      )}
    </section>
  );
}
