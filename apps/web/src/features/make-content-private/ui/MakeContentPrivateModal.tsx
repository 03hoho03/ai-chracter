import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { useQueryClient } from "@tanstack/react-query";
import { createCallable } from "react-call";
import { toast } from "sonner";

import { contentKeys, useUpdateContentVisibilityMutation } from "../../../entities/content";

type Props = {
  contentId: string;
  creatorUserId: string;
};

/** techspec-content-versioning.md §1, US-115(FR-67) — 발행된 캐릭터/스토리는 완전 삭제 없이 비공개
 * 전환만 허용된다. 호출부(프로필 카드/상세화면 액션 메뉴)와 무관하게 성공 후 동작(토스트+캐시 무효화+
 * 닫기)이 항상 동일해 UpdateInfoModal/AppealModal과 같은 "자체 mutation 직접 호출" 계열로 만들었다
 * (ConfirmChatRoomActionModal처럼 호출부가 mutationFn을 주입하는 계열이 아님). */
export const MakeContentPrivateModal = createCallable<Props, void>(
  ({ call, contentId, creatorUserId }) => {
    const queryClient = useQueryClient();
    const mutation = useUpdateContentVisibilityMutation(contentId);

    function handleConfirm() {
      mutation.mutate("private", {
        onSuccess: () => {
          toast.success("비공개로 전환했어요.");
          void queryClient.invalidateQueries({ queryKey: contentKeys.listByUser(creatorUserId) });
          void queryClient.invalidateQueries({ queryKey: contentKeys.detail(contentId) });
          call.end();
        },
        onError: () => toast.error("비공개 전환에 실패했어요. 잠시 후 다시 시도해주세요."),
      });
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>비공개로 전환할까요?</DialogTitle>
            <DialogDescription>비공개로 전환하면 홈/검색에서 더 이상 노출되지 않습니다.</DialogDescription>
          </DialogHeader>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>
              취소
            </Button>
            <Button type="button" disabled={mutation.isPending} onClick={handleConfirm}>
              {mutation.isPending ? "전환 중..." : "비공개 전환"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
