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
  chapterId: string;
  chapterOrdinal: number;
};

/** 마지막 장 지우기 확인. 클로버를 쓰지 않고, 지우면 다음 장은 이 장이 시작한 대화부터 다시 만든다는 것을 확정
 * 전에 말한다. 이미 지워진 장(404)은 지운 것과 같다.
 *
 * 지운 뒤에는 상세를 먼저 다시 받아 화면이 그 장을 떠나게 하고, 그다음에 그 장의 본문·판 캐시를 버린다 — 순서를
 * 바꾸면 아직 그 장을 보던 화면이 본문을 다시 받아 404 를 그린다. 돌려주는 값은 지웠는가다(연 버튼이 그 장과 함께
 * 사라져 호출부가 포커스를 옮긴다). 실패 문장은 누른 순간 기록한 상태다. */
export const DeleteLastChapterModal = createCallable<DeleteLastChapterModalProps, boolean>(
  ({ call, novelId, chapterId, chapterOrdinal }) => {
    const queryClient = useQueryClient();
    const deleteMutation = useDeleteLastChapterMutation();
    const [error, setError] = useState<string | undefined>(undefined);
    const isDeleting = deleteMutation.isPending;

    async function handleDelete() {
      if (isDeleting) return;
      setError(undefined);
      try {
        await deleteMutation.mutateAsync({ novelId, chapterId });
      } catch (deleteError) {
        if (!hasNovelErrorCode(deleteError, "NOVEL_CHAPTER_NOT_FOUND")) {
          const notice = toNovelActionError(deleteError, "deleteChapter");
          setError(notice?.message ?? "장을 지우지 못했어요. 잠시 후 다시 시도해주세요.");
          // 진행 중 작업·마지막 장 아님 409 는 화면이 낡았다는 뜻이다 — 버튼 잠금과 목차를 맞춘다.
          if (notice?.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
          return;
        }
      }
      await queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
      queryClient.removeQueries({ queryKey: novelKeys.chapterAll(novelId, chapterId) });
      queryClient.removeQueries({ queryKey: novelKeys.revisions(novelId, chapterId) });
      void queryClient.invalidateQueries({ queryKey: novelKeys.list() });
      call.end(true);
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{chapterOrdinal}장을 지울까요?</DialogTitle>
            <DialogDescription className="break-keep">
              이 장의 글과 판 이력이 지워지고 되돌릴 수 없어요. 다음 장은 이 장이 시작한 대화부터 다시 만들어요. 클로버는
              쓰지 않아요.
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
              {isDeleting ? "지우는 중…" : "장 지우기"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
