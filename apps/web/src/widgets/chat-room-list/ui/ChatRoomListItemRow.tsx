import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { Input } from "@ai-character-chat/ui/components/input";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { ArrowRight, MoreVertical, RotateCcw, Trash2 } from "lucide-react";
import { useDebounce } from "react-use";
import { toast } from "sonner";

import {
  chatRoomKeys,
  useDeleteChatRoomMutation,
  useRenameChatRoomMutation,
  useResetChatRoomMutation,
  type ChatRoomListItem,
} from "@/entities/chat-room";
import { ConfirmChatRoomActionModal } from "@/features/manage-chat-room";

const RENAME_DEBOUNCE_MS = 500;

export function ChatRoomListItemRow({
  item,
  contentId,
  contentType,
}: {
  item: ChatRoomListItem;
  contentId: string;
  contentType: "character" | "story";
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const [name, setName] = useState(item.name);
  const renameMutation = useRenameChatRoomMutation(item.id);
  const resetMutation = useResetChatRoomMutation(item.id);
  const deleteMutation = useDeleteChatRoomMutation(item.id);

  useDebounce(
    () => {
      const trimmed = name.trim();
      if (!trimmed || trimmed === item.name) return;
      renameMutation.mutate(trimmed, {
        onError: () => toast.error("이름 변경에 실패했어요. 잠시 후 다시 시도해주세요."),
      });
    },
    RENAME_DEBOUNCE_MS,
    [name],
  );

  const invalidateList = () =>
    queryClient.invalidateQueries({ queryKey: chatRoomKeys.list({ contentId, contentType }) });

  const handleReset = () => {
    void ConfirmChatRoomActionModal.call({
      title: "대화방을 초기화할까요?",
      description: "지금까지 나눈 대화가 모두 사라지고 처음 상태로 다시 시작돼요. 이 작업은 되돌릴 수 없어요.",
      confirmLabel: "초기화",
      mutationFn: async (call) => {
        try {
          await resetMutation.mutateAsync();
          toast.success("대화방을 초기화했어요.");
          void invalidateList();
          call.end();
        } catch {
          toast.error("초기화에 실패했어요. 잠시 후 다시 시도해주세요.");
        }
      },
    });
  };

  const handleDelete = () => {
    void ConfirmChatRoomActionModal.call({
      title: "대화방을 삭제할까요?",
      description: "삭제된 대화방과 대화 기록은 복구할 수 없어요.",
      confirmLabel: "삭제",
      mutationFn: async (call) => {
        try {
          await deleteMutation.mutateAsync();
          toast.success("대화방을 삭제했어요.");
          void invalidateList();
          if (pathname === `/chat/${item.id}`) {
            void navigate({ to: "/chats", search: { contentId, contentType } });
          }
          call.end();
        } catch {
          toast.error("삭제에 실패했어요. 잠시 후 다시 시도해주세요.");
        }
      },
    });
  };

  return (
    <div className="flex items-center gap-2 rounded-lg border border-border p-3">
      <div className="min-w-0 flex-1">
        <Input
          name="chatRoomName"
          value={name}
          onChange={(event) => setName(event.target.value)}
          aria-label="대화방 이름"
          className="h-8 border-none px-0 text-sm font-medium shadow-none focus-visible:ring-0"
        />
        <p className="truncate text-xs text-muted-foreground">{item.lastMessagePreview}</p>
      </div>

      <Button asChild variant="ghost" size="icon" aria-label="대화방 열기">
        <Link to="/chat/$roomId" params={{ roomId: item.id }}>
          <ArrowRight aria-hidden className="size-4" />
        </Link>
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="ghost" size="icon" aria-label="더보기">
            <MoreVertical aria-hidden className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={handleReset}>
            <RotateCcw aria-hidden />
            초기화
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onSelect={handleDelete}>
            <Trash2 aria-hidden />
            삭제
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
