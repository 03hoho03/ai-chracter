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
import { useNavigate, useRouter } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";

import { hasNovelErrorCode, toNovelActionError } from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { useDeleteNovelMutation } from "../api/useDeleteNovelMutation";

type DeleteNovelModalProps = {
  novelId: string;
  title: string;
  /** 진행 중인 작업이 있나. 목록처럼 모르는 자리는 `undefined` — 그때는 "있으면"으로 말한다. */
  hasActiveJob: boolean | undefined;
};

/** 소설 지우기 확인. 지운 뒤 할 일이 어디서 열었든 같아 자체 호출형이다 — 지우고, 지금 그 소설 화면이면 내 소설
 * 목록으로 옮긴 다음 그 소설의 캐시를 버린다(옮기기 전에 버리면 보고 있던 화면이 다시 받아 "찾을 수 없어요"를 한
 * 번 그린다). 이미 지워진 소설(404)은 지운 것과 같다 — 다른 탭에서 먼저 지웠다.
 *
 * 진행 중이던 작업은 멈추고 환불된다는 것을 확정 전에 말한다(서버가 같은 트랜잭션에서 환불한다). 실행 버튼은
 * 솔리드 빨강이 아니라 `destructive` 틴트이고, 버튼 순서는 `취소` 먼저다. 실패 문장은 누른 순간 기록한 상태다.
 * 돌려주는 값은 지웠는가다 — 연 버튼이 그 소설과 함께 사라지므로 호출부가 포커스를 둘 곳을 정한다. */
export const DeleteNovelModal = createCallable<DeleteNovelModalProps, boolean>(({ call, novelId, title, hasActiveJob }) => {
  const queryClient = useQueryClient();
  const router = useRouter();
  const navigate = useNavigate();
  const deleteMutation = useDeleteNovelMutation();
  const [error, setError] = useState<string | undefined>(undefined);
  const isDeleting = deleteMutation.isPending;

  async function handleDelete() {
    if (isDeleting) return;
    setError(undefined);
    try {
      await deleteMutation.mutateAsync(novelId);
    } catch (deleteError) {
      if (!hasNovelErrorCode(deleteError, "NOVEL_NOT_FOUND")) {
        setError(toNovelActionError(deleteError, "deleteNovel")?.message ?? "소설을 지우지 못했어요. 잠시 후 다시 시도해주세요.");
        return;
      }
    }
    if (router.state.location.pathname === `/novels/${novelId}`) await navigate({ to: "/novels" });
    // 이 소설의 상세·작업·장 본문·판 캐시는 키의 세 번째 자리가 소설 id 다(목록은 그 자리가 없다).
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] === "novel" && query.queryKey[2] === novelId });
    toast.success("소설을 지웠어요.");
    call.end(true);
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="break-keep">‘{title}’ 소설을 지울까요?</DialogTitle>
          <DialogDescription className="break-keep">
            모든 장과 판 이력, 설정 노트가 함께 지워지고 되돌릴 수 없어요. 원래 대화방은 그대로예요.
            {hasActiveJob === true && " 진행 중인 작업은 멈추고, 쓴 클로버는 돌려드려요."}
            {hasActiveJob === undefined && " 진행 중인 작업이 있으면 멈추고, 쓴 클로버는 돌려드려요."}
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
            {isDeleting ? "지우는 중…" : "소설 지우기"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
