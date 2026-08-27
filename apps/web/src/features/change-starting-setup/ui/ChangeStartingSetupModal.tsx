import { useNavigate } from "@tanstack/react-router";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check } from "lucide-react";
import { createCallable } from "react-call";
import { toast } from "sonner";

import { useChangeStartingSetupMutation, useChatRoomQuery } from "../../../entities/chat-room";
import { useContentDetailQuery } from "../../../entities/content";
import { ConfirmStartingSetupChangeModal } from "./ConfirmStartingSetupChangeModal";

type Props = {
  roomId: string;
};

// US-081, techspec-chat-story.md §6 — UpdateInfoModal(US-079)과 동일하게 roomId만 받아 부모
// (ChatRoomView)가 이미 채워둔 chatRoomKeys.detail 캐시를 자체 구독한다. 현재 사용 중인 시작설정은
// room.contentSnapshot.pinnedStartingSetupId(물리적 PK, US-070)로 판정 — room.startingSetupId는
// entity_id라 GET /contents/{id}가 내려주는 startingSetups[].id(물리적 PK)와 비교할 수 없다.
export const ChangeStartingSetupModal = createCallable<Props, void>(({ call, roomId }) => {
  const open = !call.ended;
  const room = useChatRoomQuery(roomId).data;
  const contentQuery = useContentDetailQuery(room?.contentId ?? "", open && room !== undefined);
  const startingSetups = contentQuery.data?.startingSetups ?? [];
  const currentSetupId = room?.contentSnapshot?.pinnedStartingSetupId;
  const changeMutation = useChangeStartingSetupMutation(roomId);
  const navigate = useNavigate();

  async function handleSelect(setupId: string) {
    if (setupId === currentSetupId || changeMutation.isPending) return;
    const confirmed = await ConfirmStartingSetupChangeModal.call();
    if (!confirmed) return;

    changeMutation.mutate(
      { startingSetupId: setupId },
      {
        onSuccess: (newRoom) => {
          call.end();
          void navigate({ to: "/chat/$roomId", params: { roomId: newRoom.id } });
        },
        onError: () => toast.error("시작설정 변경에 실패했어요. 잠시 후 다시 시도해주세요."),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>시작 설정</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-1.5">
          {startingSetups.map((setup) => {
            const isCurrent = setup.id === currentSetupId;
            return (
              <button
                key={setup.id}
                type="button"
                disabled={isCurrent || changeMutation.isPending}
                onClick={() => void handleSelect(setup.id)}
                className={cn(
                  "flex items-center justify-between gap-2 rounded-md border border-input px-3.5 py-3 text-left text-sm transition-colors",
                  isCurrent
                    ? "cursor-default bg-secondary/50 font-semibold text-foreground"
                    : "text-foreground enabled:hover:bg-secondary/50",
                )}
              >
                <span className="truncate">{setup.name}</span>
                {isCurrent && (
                  <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                    <Check aria-hidden className="size-3.5" />
                    사용 중
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
});
