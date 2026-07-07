import { Button } from "@ai-character-chat/ui/components/button";
import { Play } from "lucide-react";

import { usePlayContent } from "../lib/usePlayContent";

interface CharacterPlayButtonProps {
  contentId: string;
}

/** PRD US-016 — 캐릭터는 인트로가 1개뿐이라 시작설정 선택 UI 없이 바로 플레이 버튼만 노출한다. */
export function CharacterPlayButton({ contentId }: CharacterPlayButtonProps) {
  const { handlePlay } = usePlayContent(contentId, "character");

  return (
    <div className="border-t border-border pt-5">
      <Button size="lg" className="h-12 w-full gap-2" onClick={() => handlePlay()}>
        <Play aria-hidden className="size-4" />
        플레이
      </Button>
    </div>
  );
}
