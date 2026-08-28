import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { createCallable } from "react-call";

import { useChatRoomPlayGuideQuery } from "@/entities/chat-room";

type Props = {
  roomId: string;
};

/** techspec-chat-story.md §6, US-067 — "더보기 > 플레이가이드"에서 여는 읽기 전용 react-call 모달.
 * 입력/제출이 없어 mutationFn/useMutationFlow 없이 call.end()만으로 닫는다. */
export const PlayGuideModal = createCallable<Props, void>(({ call, roomId }) => {
  const open = !call.ended;
  const playGuideQuery = useChatRoomPlayGuideQuery(roomId, open);
  const playGuide = playGuideQuery.data?.playGuide;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>플레이가이드</DialogTitle>
          <DialogDescription>대화를 이어가는 데 도움이 되는 진행 팁이에요.</DialogDescription>
        </DialogHeader>

        {playGuideQuery.isPending ? (
          <div className="flex flex-col gap-2">
            <div className="h-4 w-full animate-pulse rounded-md bg-muted" />
            <div className="h-4 w-3/4 animate-pulse rounded-md bg-muted" />
          </div>
        ) : playGuideQuery.isError ? (
          <p className="py-4 text-center text-sm text-destructive-text">
            불러오지 못했어요. 잠시 후 다시 시도해주세요.
          </p>
        ) : playGuide ? (
          <p className="whitespace-pre-wrap text-sm text-foreground">{playGuide}</p>
        ) : (
          <p className="py-4 text-center text-sm text-muted-foreground">등록된 플레이가이드가 없어요.</p>
        )}
      </DialogContent>
    </Dialog>
  );
});
