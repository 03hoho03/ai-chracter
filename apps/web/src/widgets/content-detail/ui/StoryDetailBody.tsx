import { useState } from "react";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown } from "lucide-react";

import type { ContentDetailResponse } from "@/entities/content";
import { stripMediaTags, type MediaTagImages } from "@/entities/media-book";
import { expandAuthorMacros, type AuthorMacroNames } from "@/shared/lib/text/authorMacros";

import { MediaTagText } from "./MediaTagText";

type StoryDetailBodyProps = {
  startingSetups: NonNullable<ContentDetailResponse["startingSetups"]>;
  /** 프롤로그 속 칸 id 형태 태그가 가리키는 그림. */
  mediaTagImages: MediaTagImages;
  /** 시작설정 이름·프롤로그 속 `{{user}}`·`{{char}}` 를 바꿀 이름(보는 사람 기준). */
  macroNames: AuthorMacroNames;
  selectedSetupId: string | undefined;
  onSelectedSetupIdChange: (id: string) => void;
}

/** 시작설정 선택(첫 항목 기본 선택) + 프롤로그
 * 미리보기(요약/펼치기). 스토리 전용(캐릭터는 `CharacterChatHistoryLink` 참고).
 * 플레이 버튼은 하단 고정 바(`StoryPlayBar.tsx`)로
 * 분리했다. 선택 state는 그 바와 공유해야 해서 `ContentDetailView`가 소유하고 여기는 controlled로
 * 받는다. */
export function StoryDetailBody({
  startingSetups,
  mediaTagImages,
  macroNames,
  selectedSetupId,
  onSelectedSetupIdChange,
}: StoryDetailBodyProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const selectedSetup = startingSetups.find((setup) => setup.id === selectedSetupId) ?? startingSetups[0];

  if (!selectedSetup) return null;

  return (
    <div className="flex flex-col gap-3 border-t border-border pt-5">
      {/* 하나뿐이면 고를 것이 없으니 칩 대신 이름만 적는다 — 선택된 칩 하나가 `primary` 솔리드라 아래 플레이 버튼과
          함께 한 화면에 솔리드가 둘 선다(빌더 `StartingSetupPicker` 와 같은 처방). 이름은 아래 프롤로그가 어느 시작
          상황의 글인지 상자 바로 위에서 알린다. */}
      {startingSetups.length === 1 ? (
        <div className="flex flex-col gap-1.5">
          <h2 className="text-sm font-semibold text-foreground">시작 상황</h2>
          <p className="text-sm leading-snug font-medium break-keep wrap-anywhere text-foreground">‘{expandAuthorMacros(selectedSetup.name, macroNames)}’</p>
        </div>
      ) : (
        <>
          <h2 className="text-sm font-semibold text-foreground">시작 상황 선택</h2>

          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={selectedSetup.id}
            onValueChange={(value) => {
              if (!value) return;
              onSelectedSetupIdChange(value);
              setIsExpanded(false);
            }}
            aria-label="시작설정 선택"
            className="flex-wrap justify-start"
          >
            {startingSetups.map((setup) => (
              <ToggleGroupItem key={setup.id} value={setup.id}>
                {expandAuthorMacros(setup.name, macroNames)}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </>
      )}

      <div className="rounded-lg bg-secondary/50 p-4">
        {/* 접힌 요약은 글만 네 줄 보여 준다 — 그림 블록이 줄 수 자르기(`line-clamp`) 안에 들어가면 그림 하나가 요약
            자리를 다 차지하거나 잘린 채 보인다. 그림은 펼쳤을 때 제자리에 선다. 상자 면이 `secondary/50` 이라 그림
            자리 면은 그보다 한 칸 위인 `secondary` 다(`muted` 는 이 상자와 값이 같아 사라진다). */}
        {isExpanded ? (
          <MediaTagText
            text={selectedSetup.prologue}
            images={mediaTagImages}
            names={macroNames}
            className="whitespace-pre-wrap text-sm text-muted-foreground"
            surface="secondary"
          />
        ) : (
          <p className="line-clamp-4 whitespace-pre-wrap text-sm text-muted-foreground">
            {expandAuthorMacros(stripMediaTags(selectedSetup.prologue), macroNames)}
          </p>
        )}
        <button
          type="button"
          onClick={() => setIsExpanded((prev) => !prev)}
          className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline focus-visible:underline focus-visible:outline-none"
        >
          {isExpanded ? "접기" : "펼치기"}
          <ChevronDown
            aria-hidden
            className={cn("size-3.5 motion-safe:transition-transform motion-safe:duration-200", isExpanded && "rotate-180")}
          />
        </button>
      </div>
    </div>
  );
}
