import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown, GripVertical } from "lucide-react";

import { StatSummary, type StoryFieldKey } from "@/features/build-story";

import { mockupCardHeader } from "../model/mockupCardHeader";

/** 빌더에서 손잡이로 순서를 바꾸는 목록(시작설정·키워드북·엔딩). 목록 순서가 뜻을 가져서 손잡이가 정보다. */
const REORDERABLE_LISTS: ReadonlySet<StoryFieldKey> = new Set([
  "startingSetups",
  "keywordNotes",
  "startingSetups.*.endings",
]);

type GuideCardListMockupProps = {
  listKey: StoryFieldKey;
  cards: readonly Record<string, unknown>[];
  /** 그림에 다 싣지 않은 나머지 카드 수. */
  more: number;
  /** 펼친 모습으로 그릴 때(전개 예시 한 장) 머리 줄 아래에 들어갈 칸 그림. */
  children?: React.ReactNode;
};

/**
 * 반복 카드 목록 그림 — 빌더의 접힌 카드 머리 줄을 쌓아 "카드가 여러 장"임을 보인다. 카드 안의 칸은 이 그림이 아니라
 * 각자의 칸 블록이 따로 그린다(칸마다 설명·나쁜 예가 붙어서). 삭제 버튼은 그리지 않는다 — 그림 속 휴지통은 정보 없이
 * "지워질까" 하는 걱정만 더한다.
 */
export function GuideCardListMockup({ listKey, cards, more, children }: GuideCardListMockupProps) {
  const isReorderable = REORDERABLE_LISTS.has(listKey);
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-4">
        {cards.map((card, index) => {
          const header = mockupCardHeader(listKey, card, index);
          return (
            // 원고에서 온 고정 목록이라 순서가 바뀌지 않아 위치를 key 로 쓴다.
            <li key={index} className="flex flex-col gap-4 rounded-xl border border-border bg-background px-4 py-3">
              <div className="flex min-h-9 min-w-0 items-center gap-2">
                {isReorderable && <GripVertical aria-hidden className="size-4 shrink-0 text-muted-foreground" />}
                <span
                  className={cn(
                    "min-w-0 truncate text-sm",
                    header.title ? "font-semibold text-foreground" : "font-medium text-muted-foreground",
                  )}
                >
                  {header.title || header.placeholderTitle}
                </span>
                <span className="min-w-0 flex-1 basis-0 truncate text-xs text-muted-foreground">
                  {header.stat ? <StatSummary stat={header.stat} /> : header.summary}
                </span>
                <ChevronDown
                  aria-hidden
                  className={cn("size-4 shrink-0 text-muted-foreground", children && "rotate-180")}
                />
              </div>
              {children}
            </li>
          );
        })}
      </ul>
      {more > 0 && <p className="m-0 text-xs text-muted-foreground">외 {more}개</p>}
    </div>
  );
}
