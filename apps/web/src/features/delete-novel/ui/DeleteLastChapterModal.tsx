import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { hasNovelErrorCode, novelKeys, toNovelActionError } from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { useDeleteLastChapterMutation } from "../api/useDeleteLastChapterMutation";

type DeleteLastChapterModalProps = {
  novelId: string;
  /** 지울 묶음 — 마지막에 한 번에 만든 화들. */
  batchId: string;
  /** 그 묶음의 화들 — 여럿이면 함께 지워진다고 말한다. */
  chapterIds: string[];
  /** 그 화들의 이름(`3~5화`). */
  rangeLabel: string;
};

/** 마지막 화 지우기 확인. 지우기는 마지막에 한 번에 만든 화들(묶음) 단위라 그 화가 여럿이면 함께 지워진다는 것을,
 * 클로버를 쓰지 않는다는 것과 다음 화는 그 화들이 시작한 대화부터 다시 만든다는 것을 확정 전에 말한다. 이미 지워진
 * 묶음·화(404)는 지운 것과 같다.
 *
 * 지운 뒤에는 상세를 다시 받고 지웠다고 돌려준다. 그 화들의 본문·판 캐시는 여기서 버리지 않는다 — 이 모달이 닫히는
 * 순간에는 화면이 아직 지운 화를 그리고 있어, 그 쿼리를 지우면 관찰자가 곧바로 다시 받아 404 가 난다. 호출부가 화면을
 * 그 화에서 옮긴 뒤 `removeDeletedChapterCaches` 로 버린다. 돌려주는 값은 지웠는가다(연 버튼이 그 화와 함께 사라져
 * 호출부가 포커스를 옮긴다). 실패 문장은 누른 순간 기록한 상태다. */
export const DeleteLastChapterModal = createCallable<DeleteLastChapterModalProps, boolean>(
  ({ call, novelId, batchId, chapterIds, rangeLabel }) => {
    const queryClient = useQueryClient();
    const deleteMutation = useDeleteLastChapterMutation();
    const [error, setError] = useState<string | undefined>(undefined);
    const isDeleting = deleteMutation.isPending;

    async function handleDelete() {
      if (isDeleting) return;
      setError(undefined);
      try {
        await deleteMutation.mutateAsync({ novelId, batchId });
      } catch (deleteError) {
        if (!hasNovelErrorCode(deleteError, "NOVEL_BATCH_NOT_FOUND")) {
          const notice = toNovelActionError(deleteError, "deleteChapter");
          setError(notice?.message ?? "화를 지우지 못했어요. 잠시 후 다시 시도해주세요.");
          // 진행 중 작업·마지막 묶음 아님 409 는 화면이 낡았다는 뜻이다 — 버튼 잠금과 목차를 맞춘다.
          if (notice?.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
          return;
        }
      }
      await queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
      void queryClient.invalidateQueries({ queryKey: novelKeys.list() });
      call.end(true);
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{rangeLabel}를 지울까요?</DialogTitle>
            <DialogDescription className="break-keep">
              {chapterIds.length > 1
                ? `한 번에 함께 만든 ${rangeLabel}가 모두 지워져요. `
                : ""}
              글과 판 이력이 지워지고 되돌릴 수 없어요. 다음 화는 지운 화가 시작한 대화부터 다시 만들어요. 클로버는 쓰지
              않아요.
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
              aria-disabled={isDeleting}
              className="aria-disabled:opacity-65"
              onClick={() => void handleDelete()}
            >
              {isDeleting ? "지우는 중…" : `${rangeLabel} 지우기`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
