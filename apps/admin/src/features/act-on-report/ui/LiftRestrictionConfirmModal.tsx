import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { createCallable } from "react-call";
import { useMutationFlow, type MutationFn } from "react-call/mutation-flow";

type LiftRestrictionConfirmModalProps = {
  contentName: string;
  mutationFn: MutationFn<void>;
};

/** backlog-l-goal-prompt.md BL-7 — 신고 경유 해제는 작품 복구에 그치지 않고 신고를 처리 완료로 바꾸며,
 * 그 작품의 대화방을 최신 게시 버전으로 일괄 전환한다(되돌릴 수 없다). 그래서 버튼 한 번으로 실행하지 않고
 * 부수효과를 보여 준 뒤 확정받는다. 입력 게이트는 없다 — 삭제와 달리 작품 자체는 되돌릴 수 있어서다. */
export const LiftRestrictionConfirmModal = createCallable<LiftRestrictionConfirmModalProps, void>(
  ({ call, contentName, mutationFn }) => {
    const submit = useMutationFlow(call, mutationFn);

    function handleConfirm() {
      if (submit.pending) return;
      submit();
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>이용제한 해제</DialogTitle>
            <DialogDescription className="break-keep">
              <span className="font-medium text-foreground">{contentName}</span>의 이용제한을 해제합니다. 작품이
              원래 공개범위로 되돌아가고 이 신고는 처리 완료로 바뀝니다. 이 작품의 대화방은 최신 버전으로
              전환되며, 이 전환은 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>
              취소
            </Button>
            <Button
              type="button"
              aria-disabled={submit.pending}
              className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
              onClick={handleConfirm}
            >
              {submit.pending ? "처리 중..." : "해제 확정"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
