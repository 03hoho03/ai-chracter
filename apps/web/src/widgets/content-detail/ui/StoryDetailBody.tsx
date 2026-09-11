import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown, Play } from "lucide-react";

import type { ContentDetailResponse } from "@/entities/content";

import { usePlayContent } from "../lib/usePlayContent";

type StoryDetailBodyProps = {
  startingSetups: NonNullable<ContentDetailResponse["startingSetups"]>;
  selectedSetupId: string | undefined;
  onSelectedSetupIdChange: (id: string) => void;
}

/** techspec-content-detail.md §3, PRD US-016 — 시작설정 선택(첫 항목 기본 선택) + 프롤로그
 * 미리보기(요약/펼치기). 스토리 전용(캐릭터는 `CharacterChatHistoryLink` 참고).
 * design-system-progress.md P-5(D-7) — 플레이 버튼은 하단 고정 바(`StoryPlayBar`, 이 파일 아래)로
 * 분리했다. 선택 state는 그 바와 공유해야 해서 `ContentDetailView`가 소유하고 여기는 controlled로
 * 받는다. */
export function StoryDetailBody({ startingSetups, selectedSetupId, onSelectedSetupIdChange }: StoryDetailBodyProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const selectedSetup = startingSetups.find((setup) => setup.id === selectedSetupId) ?? startingSetups[0];

  if (!selectedSetup) return null;

  return (
    <div className="flex flex-col gap-3 border-t border-border pt-5">
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
            {setup.name}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      <div className="rounded-lg bg-secondary/50 p-4">
        <p className={cn("whitespace-pre-wrap text-sm text-muted-foreground", !isExpanded && "line-clamp-4")}>
          {selectedSetup.prologue}
        </p>
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

type StoryPlayBarProps = {
  contentId: string;
  startingSetups: NonNullable<ContentDetailResponse["startingSetups"]>;
  selectedSetupId: string | undefined;
  onRestoreSetup: (id: string) => void;
}

/** design-system-progress.md P-5(D-7) — 하단 고정 바로 뽑힌 플레이. 시작설정 선택(`StoryDetailBody`,
 * 스크롤 영역)과 물리적으로 떨어지므로, 지금 무엇을 시작하는지 보이도록 선택된 이름을 버튼 위
 * 한 줄에 노출한다. */
export function StoryPlayBar({ contentId, startingSetups, selectedSetupId, onRestoreSetup }: StoryPlayBarProps) {
  const { handlePlay } = usePlayContent(contentId, "story", { onRestoreSetup });

  const selectedSetup = startingSetups.find((setup) => setup.id === selectedSetupId) ?? startingSetups[0];

  if (!selectedSetup) return null;

  return (
    <div className="flex flex-col gap-1">
      <span className="truncate text-xs text-muted-foreground">{selectedSetup.name}</span>
      <Button size="lg" className="h-12 w-full gap-2" onClick={() => handlePlay(selectedSetup.id)}>
        <Play aria-hidden className="size-4" />
        플레이
      </Button>
    </div>
  );
}
