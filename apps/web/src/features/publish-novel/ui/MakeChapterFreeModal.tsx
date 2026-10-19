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
import { toast } from "sonner";

import { createCallable } from "@/shared/lib/callable/createCallable";

import { useMakeChapterFreeMutation } from "../api/useMakeChapterFreeMutation";
import { MAKE_CHAPTER_FREE_FAILURE_MESSAGES, toMakeChapterFreeFailure } from "../model/makeChapterFreeFailure";

type MakeChapterFreeModalProps = {
  novelId: string;
  chapterId: string;
  ordinal: number;
};

/** 공개한 유료 화를 무료로 바꾸기 전 확인. 되돌릴 수 없다는 것, 이미 산 회원에게 클로버를 돌려주지 않는다는 것, 글이 그대로라
 * 다시 확인받지 않는다는 것을 확정 전에 말한다. 되돌릴 수 없는 일이라 실행 버튼은 거두기와 같은 `destructive` 틴트다.
 *
 * 성공하면 토스트로 알리고 닫는다(공개 상태는 응답으로 바로 바뀐다). 화면이 낡았으면(그사이 그 화가 공개한 화가 아니게
 * 됐거나 스위치가 꺼짐) 토스트로 말하고 닫는다 — 다시 받은 공개 상태가 목록을 고친다. 그 밖의 실패는 모달 안에 말하고
 * 남겨 다시 누를 수 있게 한다. 끝나면 바꿨는가를 돌려준다. */
export const MakeChapterFreeModal = createCallable<MakeChapterFreeModalProps, boolean>(({ call, novelId, chapterId, ordinal }) => {
  const makeFree = useMakeChapterFreeMutation(novelId);
  const [error, setError] = useState<string | undefined>(undefined);

  async function handleConfirm() {
    if (makeFree.isPending) return;
    setError(undefined);
    try {
      await makeFree.mutateAsync(chapterId);
      toast.success(`${ordinal}화를 무료로 바꿨어요.`);
      call.end(true);
    } catch (caught) {
      const failure = toMakeChapterFreeFailure(caught);
      if (failure === "stale") {
        toast.error(MAKE_CHAPTER_FREE_FAILURE_MESSAGES.stale);
        call.end(false);
        return;
      }
      setError(MAKE_CHAPTER_FREE_FAILURE_MESSAGES.failed);
    }
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{ordinal}화를 무료로 바꿀까요?</DialogTitle>
          <DialogDescription className="break-keep">
            무료로 바꾼 화는 다시 유료로 되돌릴 수 없어요. 이미 산 회원에게 클로버를 돌려드리지 않아요. 글은 그대로라 다시
            확인받지 않아요.
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
            aria-disabled={makeFree.isPending}
            className="aria-disabled:opacity-65"
            onClick={() => void handleConfirm()}
          >
            {makeFree.isPending ? "바꾸는 중…" : "무료로 바꾸기"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
