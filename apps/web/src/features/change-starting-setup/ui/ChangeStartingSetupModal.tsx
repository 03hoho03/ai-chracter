import { useNavigate } from "@tanstack/react-router";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check } from "lucide-react";
import { toast } from "sonner";

import {
  CONTENT_PRIVATE_START_MESSAGE,
  CONTENT_RESTRICTED_START_MESSAGE,
  toStartChatErrorMessage,
  useChangeStartingSetupMutation,
  useChatRoomQuery,
} from "@/entities/chat-room";
import { canViewDetailPage, type ContentDetailResponse, toContentAccessStatus, useContentDetailQuery } from "@/entities/content";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { expandAuthorMacros, type AuthorMacroNames } from "@/shared/lib/text/authorMacros";

import { ConfirmStartingSetupChangeModal } from "./ConfirmStartingSetupChangeModal";

type ChangeStartingSetupModalProps = {
  roomId: string;
  /** 연 방의 `{{user}}`·`{{char}}` 이름 — 시작설정 이름에도 쓸 수 있다. */
  macroNames: AuthorMacroNames;
};

// UpdateInfoModal과 동일하게 roomId만 받아 부모
// (ChatRoomView)가 이미 채워둔 chatRoomKeys.detail 캐시를 자체 구독한다. 현재 사용 중인 시작설정은
// room.contentSnapshot.pinnedStartingSetupId(물리적 PK)로 판정 — room.startingSetupId는
// entity_id라 GET /contents/{id}가 내려주는 startingSetups[].id(물리적 PK)와 비교할 수 없다.
export const ChangeStartingSetupModal = createCallable<ChangeStartingSetupModalProps, void>(({ call, roomId, macroNames }) => {
  const isOpen = !call.ended;
  const room = useChatRoomQuery(roomId).data;
  const contentQuery = useContentDetailQuery(room?.contentId ?? "", isOpen && room !== undefined);
  const startingSetups = contentQuery.data?.startingSetups ?? [];
  // 볼 수 없는 작품(이용제한·삭제, 작가가 아닌 사람의 비공개)에서는 시작설정 변경이 새 방이라 막히고, 상세도 시작설정
  // 목록을 비워 보낸다. 빈 창 대신 왜 안 되는지 말한다.
  const blockedMessage = toBlockedMessage(contentQuery.data);
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
        // 시작설정 변경은 새 방을 만든다 — 이용제한·비공개 작품이면 새 대화 시작과 같은 이유로 막힌다.
        onError: (error) =>
          toast.error(toStartChatErrorMessage(error, "시작설정 변경에 실패했어요. 잠시 후 다시 시도해주세요.")),
      },
    );
  }

  return (
    <Dialog open={isOpen} onOpenChange={(next) => !next && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>시작 설정</DialogTitle>
        </DialogHeader>

        {blockedMessage !== undefined && <p className="text-sm text-muted-foreground">{blockedMessage}</p>}

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
                  "flex items-center justify-between gap-2 rounded-md border border-input px-3.5 py-3 text-left text-sm motion-safe:transition-colors",
                  isCurrent
                    ? "cursor-default bg-secondary/50 font-semibold text-foreground"
                    : "text-foreground enabled:hover:bg-secondary/50",
                )}
              >
                <span className="truncate">{expandAuthorMacros(setup.name, macroNames)}</span>
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

function toBlockedMessage(content: ContentDetailResponse | undefined): string | undefined {
  if (content === undefined) return undefined;
  const access = toContentAccessStatus(content.accessStatus);
  if (canViewDetailPage(access, content.isOwner)) return undefined;
  return access.kind === "accessible" ? CONTENT_PRIVATE_START_MESSAGE : CONTENT_RESTRICTED_START_MESSAGE;
}
