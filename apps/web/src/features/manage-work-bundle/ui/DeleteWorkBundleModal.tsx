import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { toast } from "sonner";

import { createCallable } from "@/shared/lib/callable/createCallable";

import { useDeleteWorkBundleMutation } from "../api/workBundleMutations";
import { toWorkBundleActionError } from "../model/bundleActionError";

type DeleteWorkBundleModalProps = {
  bundleId: string;
  name: string;
};

/** 묶음 지우기 확인. 지웠으면 `true` 로 끝난다 — 캐시 정리는 호출부가 화면을 옮긴 뒤에 한다
 * (`clearDeletedWorkBundle` 의 주석).
 *
 * 설명은 결과만 적는다. 묶음을 지우면 작품도 사라지는지가 이 순간 가장 큰 걱정이라 그것부터 말한다. */
export const DeleteWorkBundleModal = createCallable<DeleteWorkBundleModalProps, boolean>(({ call, bundleId, name }) => {
  const mutation = useDeleteWorkBundleMutation();

  function handleConfirm() {
    mutation.mutate(bundleId, {
      onSuccess: () => {
        toast.success("묶음을 지웠어요.");
        call.end(true);
      },
      onError: (error) => {
        const notice = toWorkBundleActionError(error, "delete");
        if (notice !== null) toast.error(notice.message);
      },
    });
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="break-keep [overflow-wrap:anywhere]">‘{name}’ 묶음을 지울까요?</DialogTitle>
          <DialogDescription>작품은 지워지지 않아요. 묶음만 없어져요.</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end(false)}>
            취소
          </Button>
          <Button type="button" variant="destructive" disabled={mutation.isPending} onClick={handleConfirm}>
            {mutation.isPending ? "지우는 중…" : "묶음 지우기"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
