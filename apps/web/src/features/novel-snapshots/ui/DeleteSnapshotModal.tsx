import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useRef, useState } from "react";

import { hasNovelErrorCode, toNovelActionError, useDeleteNovelSnapshotMutation } from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { koreanParticle } from "@/shared/lib/text/koreanParticle";

type DeleteSnapshotModalProps = {
  novelId: string;
  snapshotId: string;
  snapshotName: string;
  /** 지운 뒤 모달이 완전히 닫히면 포커스를 둘 곳으로 옮긴다. 지우면 모달을 연 메뉴가 그 행과 함께 사라지고, 결과를 받은
   * 직후에 옮기면 아직 닫히는 중인 모달이 포커스를 도로 가둬 결국 `<body>` 로 떨어진다 — 그래서 닫힘 뒤 자리
   * (`onCloseAutoFocus`)에서 부른다. 그만두면 부르지 않고 연 메뉴로 돌아간다. */
  onRestoreFocusAfterDelete: () => void;
};

/** 버전 지우기 확인과 실행. 이미 지워진 버전(404)은 지운 것과 같다. 지웠는가를 돌려준다 — 지우면 연 메뉴가 그 행과
 * 함께 사라지므로 닫힌 뒤 포커스는 호출부가 준 자리로 간다. 화의 판은 버전과 무관하게 남는다. */
export const DeleteSnapshotModal = createCallable<DeleteSnapshotModalProps, boolean>(
  ({ call, novelId, snapshotId, snapshotName, onRestoreFocusAfterDelete }) => {
    const isDeletedRef = useRef(false);
    const mutation = useDeleteNovelSnapshotMutation();
    const [error, setError] = useState<string | undefined>(undefined);
    const isDeleting = mutation.isPending;

    async function handleDelete() {
      if (isDeleting) return;
      setError(undefined);
      try {
        await mutation.mutateAsync({ novelId, snapshotId });
      } catch (deleteError) {
        if (!hasNovelErrorCode(deleteError, "NOVEL_SNAPSHOT_NOT_FOUND")) {
          setError(toNovelActionError(deleteError, "deleteSnapshot")?.message ?? "버전을 지우지 못했어요. 잠시 후 다시 시도해주세요.");
          return;
        }
      }
      isDeletedRef.current = true;
      call.end(true);
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
        <DialogContent
          className="sm:max-w-sm"
          onCloseAutoFocus={(event) => {
            if (!isDeletedRef.current) return;
            event.preventDefault();
            requestAnimationFrame(onRestoreFocusAfterDelete);
          }}
        >
          <DialogHeader>
            <DialogTitle className="break-keep">‘{snapshotName}’{koreanParticle(snapshotName, "을/를")} 지울까요?</DialogTitle>
            <DialogDescription className="break-keep">
              이 버전으로는 더 되돌릴 수 없어요. 화의 글과 판 이력은 그대로 남아요.
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
              {isDeleting ? "지우는 중…" : "지우기"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
