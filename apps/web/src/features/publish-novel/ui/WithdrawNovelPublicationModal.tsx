import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useState } from "react";

import { createCallable } from "@/shared/lib/callable/createCallable";

import { useWithdrawNovelPublicationMutation } from "../api/useWithdrawNovelPublicationMutation";

/** 노벨 공개 거두기 확인. 거두면 목록·작품 화면에서 바로 사라지고 소장한 회원도 못 보며 클로버는 돌려주지 않는다는
 * 것을, 다시 공개하면 소장한 화가 다시 열린다는 것과 함께 확정 전에 말한다. 실행 버튼은 `destructive` 틴트다. 거뒀으면
 * `true`. */
export const WithdrawNovelPublicationModal = createCallable<{ novelId: string }, boolean>(({ call, novelId }) => {
  const withdraw = useWithdrawNovelPublicationMutation(novelId);
  const [error, setError] = useState<string | undefined>(undefined);

  async function handleWithdraw() {
    if (withdraw.isPending) return;
    setError(undefined);
    try {
      await withdraw.mutateAsync();
      call.end(true);
    } catch {
      setError("공개를 거두지 못했어요. 잠시 후 다시 시도해 주세요.");
    }
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>노벨 공개를 거둘까요?</DialogTitle>
          <DialogDescription className="break-keep">
            목록과 작품 화면에서 바로 사라지고, 소장한 회원도 더 볼 수 없게 돼요. 클로버는 돌려드리지 않아요. 나중에 다시
            공개하면 소장한 화도 다시 열려요.
          </DialogDescription>
        </DialogHeader>

        {error !== undefined && (
          <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
            {error}
          </p>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end(false)}>
            취소
          </Button>
          <Button
            type="button"
            variant="destructive"
            aria-disabled={withdraw.isPending}
            className="aria-disabled:opacity-65"
            onClick={() => void handleWithdraw()}
          >
            {withdraw.isPending ? "거두는 중…" : "공개 거두기"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
