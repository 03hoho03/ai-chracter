import { Button } from "@ai-character-chat/ui/components/button";
import { Loader2, Play } from "lucide-react";

import type { ContentDetailResponse } from "@/entities/content";
import { expandAuthorMacros, type AuthorMacroNames } from "@/shared/lib/text/authorMacros";

import { usePlayContent } from "../lib/usePlayContent";

type StoryPlayBarProps = {
  contentId: string;
  startingSetups: NonNullable<ContentDetailResponse["startingSetups"]>;
  selectedSetupId: string | undefined;
  /** 본문의 대화 프로필 줄에서 고른 프로필. undefined 면 시작 쪽이 기본으로 정한다. */
  personaId: string | undefined;
  /** 시작설정 이름 속 `{{user}}`·`{{char}}` 를 바꿀 이름(보는 사람 기준). */
  macroNames: AuthorMacroNames;
  onRestoreSetup: (id: string) => void;
}

/** 하단 고정 바로 뽑힌 플레이. 시작설정 선택(`StoryDetailBody`,
 * 스크롤 영역)과 물리적으로 떨어지므로, 지금 무엇을 시작하는지 보이도록 선택된 이름을 버튼 위
 * 한 줄에 노출한다. */
export function StoryPlayBar({
  contentId,
  startingSetups,
  selectedSetupId,
  personaId,
  macroNames,
  onRestoreSetup,
}: StoryPlayBarProps) {
  const { handlePlay, isStarting } = usePlayContent(contentId, "story", { onRestoreSetup });

  const selectedSetup = startingSetups.find((setup) => setup.id === selectedSetupId) ?? startingSetups[0];

  if (!selectedSetup) return null;

  return (
    <div className="flex flex-col gap-1">
      <span className="truncate text-xs text-muted-foreground">{expandAuthorMacros(selectedSetup.name, macroNames)}</span>
      <Button
        size="lg"
        aria-disabled={isStarting}
        onClick={() => handlePlay(selectedSetup.id, personaId)}
        className="h-12 w-full gap-2 aria-disabled:pointer-events-none aria-disabled:opacity-65"
      >
        {isStarting ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <Play aria-hidden className="size-4" />}
        플레이
      </Button>
    </div>
  );
}
