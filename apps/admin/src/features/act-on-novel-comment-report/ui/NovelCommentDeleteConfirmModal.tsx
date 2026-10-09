import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useMutationFlow, type MutationFn } from "react-call/mutation-flow";

import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

type NovelCommentDeleteConfirmModalProps = {
  mutationFn: MutationFn<void>;
};

/** 신고된 노벨 댓글 삭제 확인. 본문을 비우고 되돌릴 수 없어 패널의 "처리 확정" 한 번으로 실행하지 않는다. 댓글에는 다시 쳐서
 * 확인할 이름이 없어 입력 게이트 없이 부수효과만 보이고 확정받는다. */
export const NovelCommentDeleteConfirmModal = createCallable<NovelCommentDeleteConfirmModalProps, void>(
  ({ call, mutationFn }) => {
    const submit = useMutationFlow(call, mutationFn);

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-sm" onOpenAutoFocus={focusInitialElement}>
          <DialogHeader>
            <DialogTitle>댓글 삭제</DialogTitle>
            <DialogDescription className="break-keep">
              이 댓글의 본문을 비우고 지웁니다. 되돌릴 수 없고, 신고는 처리완료로 바뀝니다. 신고 당시 사본은 보유 기간 동안
              남아요.
            </DialogDescription>
          </DialogHeader>

          <DialogFooter>
            <Button type="button" variant="outline" autoFocus data-initial-focus onClick={() => call.end()}>
              취소
            </Button>
            <Button
              type="button"
              variant="destructive"
              aria-disabled={submit.pending}
              className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
              onClick={() => {
                if (!submit.pending) submit();
              }}
            >
              {submit.pending ? "처리 중..." : "삭제 확정"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
