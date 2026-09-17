import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { useAtom } from "jotai";
import { MessagesSquare } from "lucide-react";

import { contentDetailModalAtom } from "@/entities/content";
import { useSessionQuery } from "@/entities/session";

type CharacterChatHistoryLinkProps = {
  contentId: string;
}

/** US-024/US-049(원본 PRD 번호, prd.json US-056) — "내 대화 목록"은 로그인 사용자에게만 노출되는
 * 콘텐츠 단위 진입점이다(techspec-chat-common.md §3, /chats?contentId=&contentType=). 플레이가
 * 하단 바로 빠지면서(P-5) 스크롤 영역에는 이 링크만 남는다 — `border-t`도 이 조건부 블록 안으로
 * 옮겨서, 로그아웃 상태에서 divider만 남는 빈 박스가 생기지 않게 한다. */
export function CharacterChatHistoryLink({ contentId }: CharacterChatHistoryLinkProps) {
  const session = useSessionQuery();
  const [modalState, setModalState] = useAtom(contentDetailModalAtom);

  if (!session.data) return null;

  return (
    <div className="border-t border-border pt-5">
      <Button asChild variant="ghost" className="w-full gap-2" onClick={() => setModalState(undefined)}>
        {/* 모달 경유면 `open()`이 밀어 넣은 `/content/...` 엔트리를 덮어써야 /chats에서 뒤로가기가
            풀페이지 상세로 튀지 않는다(usePlayContent의 플레이 이동과 같은 이유). */}
        <Link to="/chats" search={{ contentId, contentType: "character" }} replace={modalState !== undefined}>
          <MessagesSquare aria-hidden className="size-4" />
          내 대화 목록
        </Link>
      </Button>
    </div>
  );
}
