import { Button } from "@ai-character-chat/ui/components/button";
import { useNavigate } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import { useChatRoomListQuery, useStartChatMutation } from "../../../entities/chat-room";
import { ChatRoomListItemRow } from "./ChatRoomListItemRow";

function ChatRoomListSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      {[0, 1, 2].map((key) => (
        <div key={key} className="h-16 animate-pulse rounded-lg bg-muted" />
      ))}
    </div>
  );
}

/** techspec-chat-common.md §3, US-024/US-049(원본 PRD 번호) — 같은 콘텐츠에 대한 내 대화방 목록:
 * 이름 변경/초기화/삭제(entities/chat-room)와 "새 대화 시작"을 한 화면에서 다룬다. */
export function ChatRoomListView({
  contentId,
  contentType,
}: {
  contentId: string;
  contentType: "character" | "story";
}) {
  const navigate = useNavigate();
  const listQuery = useChatRoomListQuery({ contentId, contentType });
  const startChatMutation = useStartChatMutation();

  const handleStartNewChat = async () => {
    try {
      // BE의 ChatRoomCreateRequest.contentType이 아직 "character" literal만 허용한다(US-057 이전).
      const room = await startChatMutation.mutateAsync({ contentId, contentType: "character" });
      void navigate({ to: "/chat/$roomId", params: { roomId: room.id } });
    } catch {
      toast.error("새 대화를 시작하지 못했어요. 잠시 후 다시 시도해주세요.");
    }
  };

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-4 px-6 py-10">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold tracking-tight text-foreground">내 채팅목록</h1>

        {contentType === "character" && (
          <Button size="sm" className="gap-1.5" disabled={startChatMutation.isPending} onClick={() => void handleStartNewChat()}>
            <Plus aria-hidden className="size-4" />
            새 대화 시작
          </Button>
        )}
      </div>

      {listQuery.isPending && <ChatRoomListSkeleton />}

      {listQuery.isError && (
        <p className="text-sm text-destructive-text">목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {listQuery.data && listQuery.data.length === 0 && (
        <p className="text-sm text-muted-foreground">아직 대화방이 없어요. 새 대화를 시작해보세요.</p>
      )}

      {listQuery.data && listQuery.data.length > 0 && (
        <div className="flex flex-col gap-2">
          {listQuery.data.map((item) => (
            <ChatRoomListItemRow key={item.id} item={item} contentId={contentId} contentType={contentType} />
          ))}
        </div>
      )}
    </main>
  );
}
