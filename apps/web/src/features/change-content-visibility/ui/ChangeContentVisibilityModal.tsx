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

import {
  contentKeys,
  useUpdateContentVisibilityMutation,
  type ContentVisibility,
} from "@/entities/content";

import { VISIBILITY_TRANSITION_COPY } from "../model/visibilityTransition";

type Props = {
  contentId: string;
  creatorUserId: string;
  /** 전환하려는 공개범위. 현재 값과 같은 항목은 호출부(`listVisibilityTransitions`)가 걸러 낸다. */
  targetVisibility: ContentVisibility;
};

/** techspec-content-versioning.md §1, US-115(FR-67) — 발행된 캐릭터/스토리는 완전 삭제 없이 공개범위
 * 전환만 허용된다(US-005에서 비공개 단방향 → public/link/private 3방향으로 확장). 호출부(프로필
 * 카드/상세화면 액션 메뉴)와 무관하게 성공 후 동작(토스트+캐시 무효화+닫기)이 항상 동일해
 * UpdateInfoModal/AppealModal과 같은 "자체 mutation 직접 호출" 계열로 만들었다
 * (ConfirmChatRoomActionModal처럼 호출부가 mutationFn을 주입하는 계열이 아님). */
export const ChangeContentVisibilityModal = createCallable<Props, void>(
  ({ call, contentId, creatorUserId, targetVisibility }) => {
    const queryClient = useQueryClient();
    const mutation = useUpdateContentVisibilityMutation(contentId);
    const { label, description } = VISIBILITY_TRANSITION_COPY[targetVisibility];

    function handleConfirm() {
      mutation.mutate(targetVisibility, {
        onSuccess: () => {
          toast.success(`${label}로 전환했어요.`);
          void queryClient.invalidateQueries({ queryKey: contentKeys.listByUser(creatorUserId) });
          void queryClient.invalidateQueries({ queryKey: contentKeys.detail(contentId) });
          call.end();
        },
        onError: () => toast.error(`${label} 전환에 실패했어요. 잠시 후 다시 시도해주세요.`),
      });
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>이 작품을 {label}로 전환할까요?</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>
              취소
            </Button>
            <Button type="button" disabled={mutation.isPending} onClick={handleConfirm}>
              {mutation.isPending ? "전환 중..." : `${label}로 전환`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
