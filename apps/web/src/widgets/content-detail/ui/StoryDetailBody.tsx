import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown, Play } from "lucide-react";

import type { ContentDetailResponse } from "../../../entities/content";
import { usePlayContent } from "../lib/usePlayContent";

interface StoryDetailBodyProps {
  contentId: string;
  startingSetups: NonNullable<ContentDetailResponse["startingSetups"]>;
}

/** techspec-content-detail.md §3, PRD US-016 — 시작설정 선택(첫 항목 기본 선택) + 프롤로그
 * 미리보기(요약/펼치기) + 플레이 버튼. 스토리 전용(캐릭터는 `CharacterPlayButton` 참고). */
export function StoryDetailBody({ contentId, startingSetups }: StoryDetailBodyProps) {
  const [selectedSetupId, setSelectedSetupId] = useState(startingSetups[0]?.id);
  const [isExpanded, setIsExpanded] = useState(false);
  const { handlePlay } = usePlayContent(contentId, "story", { onRestoreSetup: setSelectedSetupId });

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
          setSelectedSetupId(value);
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

      <Button size="lg" className="h-12 w-full gap-2" onClick={() => handlePlay(selectedSetup.id)}>
        <Play aria-hidden className="size-4" />
        플레이
      </Button>
    </div>
  );
}
