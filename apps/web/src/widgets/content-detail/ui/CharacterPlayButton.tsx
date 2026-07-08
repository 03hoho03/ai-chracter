import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { useSetAtom } from "jotai";
import { MessagesSquare, Play } from "lucide-react";

import { useSessionQuery } from "../../../entities/session";
import { contentDetailModalAtom } from "../../../shared/model/content-detail-modal";
import { usePlayContent } from "../lib/usePlayContent";

interface CharacterPlayButtonProps {
  contentId: string;
}

/** PRD US-016 — 캐릭터는 인트로가 1개뿐이라 시작설정 선택 UI 없이 바로 플레이 버튼만 노출한다.
 * US-024/US-049(원본 PRD 번호, prd.json US-056) — "내 대화 목록"은 로그인 사용자에게만 노출되는
 * 콘텐츠 단위 진입점이다(techspec-chat-common.md §3, /chats?contentId=&contentType=). */
export function CharacterPlayButton({ contentId }: CharacterPlayButtonProps) {
  const { handlePlay } = usePlayContent(contentId, "character");
  const session = useSessionQuery();
  const setModalState = useSetAtom(contentDetailModalAtom);

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-5">
      <Button size="lg" className="h-12 w-full gap-2" onClick={() => handlePlay()}>
        <Play aria-hidden className="size-4" />
        플레이
      </Button>

      {session.data && (
        <Button asChild variant="ghost" className="w-full gap-2" onClick={() => setModalState(null)}>
          <Link to="/chats" search={{ contentId, contentType: "character" }}>
            <MessagesSquare aria-hidden className="size-4" />
            내 대화 목록
          </Link>
        </Button>
      )}
    </div>
  );
}
