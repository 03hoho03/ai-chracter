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

import {
  hasNovelErrorCode,
  novelKeys,
  toNovelActionError,
  useRestoreNovelSnapshotMutation,
  type NovelSnapshotRestoreResponse,
} from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";

type RestoreSnapshotModalProps = {
  novelId: string;
  snapshotId: string;
  snapshotName: string;
};

/** 버전 되돌리기 확인과 실행. 무엇이 바뀌고 무엇이 남는지(그 뒤에 생긴 화는 그대로, 지금 상태는 자동 저장)를 확정
 * 전에 말한다. 되돌린 결과(건너뛴 화 포함)를 돌려주고, 그만두면 `null` 이다.
 *
 * 화를 만들고 있는 동안은 서버가 거부한다 — 생성 결과가 같은 화·인물·제목을 고치기 때문이다. 그때는 끝나면 할 수
 * 있다고 말하고 상세를 다시 받는다(진행 중 작업이 화면에 보이게). */
export const RestoreSnapshotModal = createCallable<RestoreSnapshotModalProps, NovelSnapshotRestoreResponse | null>(
  ({ call, novelId, snapshotId, snapshotName }) => {
    const queryClient = useQueryClient();
    const mutation = useRestoreNovelSnapshotMutation();
    const [error, setError] = useState<string | undefined>(undefined);
    const isRestoring = mutation.isPending;

    async function handleRestore() {
      if (isRestoring) return;
      setError(undefined);
      try {
        call.end(await mutation.mutateAsync({ novelId, snapshotId }));
      } catch (restoreError) {
        const notice = toNovelActionError(restoreError, "restoreSnapshot");
        if (notice === null) {
          call.end(null);
          return;
        }
        setError(
          hasNovelErrorCode(restoreError, "NOVEL_JOB_IN_PROGRESS")
            ? "만들고 있는 화가 끝나면 되돌릴 수 있어요."
            : notice.message,
        );
        if (notice.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
        if (hasNovelErrorCode(restoreError, "NOVEL_SNAPSHOT_NOT_FOUND")) {
          void queryClient.invalidateQueries({ queryKey: novelKeys.snapshots(novelId) });
        }
      }
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="break-keep">‘{snapshotName}’ 때로 되돌릴까요?</DialogTitle>
            <DialogDescription className="break-keep">
              그때 있던 화의 글·제목·작가의 말, 소설 제목·소개, 설정 노트, 인물 메모가 그때 값으로 바뀌어요. 그 뒤에 생긴
              화는 그대로 남아요. 지금 상태는 ‘복원 전 자동 저장’으로 남겨 둬요.
            </DialogDescription>
          </DialogHeader>

          {error !== undefined && (
            <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
              {error}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end(null)}>
              취소
            </Button>
            <Button type="button" aria-disabled={isRestoring} className="aria-disabled:opacity-65" onClick={() => void handleRestore()}>
              {isRestoring ? "되돌리는 중…" : "되돌리기"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
