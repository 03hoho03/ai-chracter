import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { createCallable } from "react-call";
import { useMutationFlow, type MutationFn } from "react-call/mutation-flow";

type Props = {
  contentName: string;
  mutationFn: MutationFn<void>;
};

/** techspec-admin.md §1/§4 — 삭제는 되돌릴 수 없으므로, 콘텐츠명을 정확히 입력해야만 확정 버튼이 활성화된다.
 * 관리자 코멘트는 호출부가 이미 받아 mutationFn 클로저에 담아 넘기므로 이 모달은 입력을 다시 받지 않는다. */
export const DeleteConfirmModal = createCallable<Props, void>(({ call, contentName, mutationFn }) => {
  const [confirmText, setConfirmText] = useState("");
  const submit = useMutationFlow(call, mutationFn);
  const canConfirm = confirmText.trim() === contentName;

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>콘텐츠 삭제</DialogTitle>
          <DialogDescription>
            이 작업은 되돌릴 수 없습니다. 삭제를 확정하려면 콘텐츠명{" "}
            <span className="font-medium text-foreground">{contentName}</span>을(를) 아래에 정확히 입력하세요.
          </DialogDescription>
        </DialogHeader>

        <Input
          value={confirmText}
          onChange={(event) => setConfirmText(event.target.value)}
          placeholder={contentName}
          autoFocus
        />

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end()}>
            취소
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={!canConfirm || submit.pending}
            onClick={() => submit()}
          >
            {submit.pending ? "삭제 중..." : "삭제 확정"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
