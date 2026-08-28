import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { CheckCircle2 } from "lucide-react";
import { createCallable } from "react-call";
import { toast } from "sonner";

import { useChatRoomQuery, usePinLatestVersionMutation } from "@/entities/chat-room";

type Props = {
  roomId: string;
};

/** techspec-chat-story.md §6, techspec-content-versioning.md §3, US-079 — "더보기 > 업데이트 정보"에서
 * 여는 react-call 모달. roomId만 받아 ChatRoomView가 이미 채워둔 chatRoomKeys.detail 캐시를 그대로
 * 구독해 latestVersionAvailable을 읽는다(PlayGuideModal과 동일하게 별도 프롭 스레딩 없이 자체 조회). */
export const UpdateInfoModal = createCallable<Props, void>(({ call, roomId }) => {
  const open = !call.ended;
  const room = useChatRoomQuery(roomId).data;
  const pinMutation = usePinLatestVersionMutation(roomId);
  const hasUpdate = room?.latestVersionAvailable ?? false;

  function handlePinLatestVersion() {
    pinMutation.mutate(undefined, {
      onSuccess: () => {
        toast.success("최신 버전으로 전환했어요.");
        call.end();
      },
      onError: () => toast.error("전환에 실패했어요. 잠시 후 다시 시도해주세요."),
    });
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>업데이트 정보</DialogTitle>
          {hasUpdate && (
            <DialogDescription>
              원작에 새 버전이 있어요. 전환하면 다음 응답부터 최신 내용이 적용돼요.
            </DialogDescription>
          )}
        </DialogHeader>

        {!hasUpdate && (
          <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
            <CheckCircle2 aria-hidden className="size-4 shrink-0" />
            지금 최신 버전으로 대화하고 있어요.
          </div>
        )}

        {hasUpdate && (
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>
              나중에
            </Button>
            <Button type="button" disabled={pinMutation.isPending} onClick={handlePinLatestVersion}>
              {pinMutation.isPending ? "전환 중..." : "최신 버전으로 전환"}
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
});
