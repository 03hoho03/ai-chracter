import { Button } from "@ai-character-chat/ui/components/button";
import { Loader2, Play } from "lucide-react";

import { usePlayContent } from "../lib/usePlayContent";

type CharacterPlayBarProps = {
  contentId: string;
}

/** 캐릭터는 인트로가 1개뿐이라 시작설정 선택 UI 없이 바로 플레이 버튼만 노출한다.
 * 하단 고정 바(모달 flex 하단 · 풀페이지 fixed)로 뽑혀 나온
 * 자리라 스크롤 영역의 "내 대화 목록"(`CharacterChatHistoryLink.tsx`)과 분리되어 있다. */
export function CharacterPlayBar({ contentId }: CharacterPlayBarProps) {
  const { handlePlay, isStarting } = usePlayContent(contentId, "character");

  return (
    <Button
      size="lg"
      aria-disabled={isStarting}
      onClick={() => handlePlay()}
      className="h-12 w-full gap-2 aria-disabled:pointer-events-none aria-disabled:opacity-65"
    >
      {isStarting ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <Play aria-hidden className="size-4" />}
      플레이
    </Button>
  );
}
