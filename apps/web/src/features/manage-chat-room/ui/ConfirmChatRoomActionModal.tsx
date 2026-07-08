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

type Props = {
  title: string;
  description: string;
  confirmLabel: string;
  mutationFn: MutationFn<void>;
};

/** techspec-overview.md §9, US-048 CLAUDE.md 메모가 예고한 "대화방 초기화·삭제 확인" react-call
 * 사례 — 둘 다 입력 없이 확인/취소만 있는 동일 구조라 하나의 컴포넌트로 공유한다. ReportContentModal과
 * 동일하게 실제 API 호출/토스트는 호출부의 mutationFn이 담당하고, 이 컴포넌트는 확인 UI + 제출 상태
 * 표시만 책임진다. */
export const ConfirmChatRoomActionModal = createCallable<Props, void>(
  ({ call, title, description, confirmLabel, mutationFn }) => {
    const submit = useMutationFlow(call, mutationFn);

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>
              취소
            </Button>
            <Button type="button" variant="destructive" disabled={submit.pending} onClick={() => submit()}>
              {submit.pending ? "처리 중..." : confirmLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
