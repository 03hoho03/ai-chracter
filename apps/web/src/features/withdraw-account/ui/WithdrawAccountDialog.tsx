import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@ai-character-chat/ui/components/alert-dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";

import { useWithdrawAccountMutation } from "../api/mutations";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

/** techspec-global-nav-profile.md §2 — 부수효과(발행작 비공개 전환, 대화기록 삭제, 초안 보존)는 전부 BE 책임이며 FE는 단일 mutation만 호출한다. */
export function WithdrawAccountDialog() {
  const navigate = useNavigate();
  const withdrawMutation = useWithdrawAccountMutation();

  const handleConfirm = () => {
    withdrawMutation.mutate(undefined, {
      onSuccess: () => {
        toast.success("탈퇴가 완료되었어요.");
        void navigate({ to: "/" });
      },
      onError: () => {
        toast.error(GENERIC_ERROR_MESSAGE);
      },
    });
  };

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="destructive">회원탈퇴</Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>정말 탈퇴하시겠어요?</AlertDialogTitle>
          {/* `break-keep`은 호출부 책임이다 — `DialogDescription` 프리미티브는 들고 있지 않다. 없으면 이
              문장이 **양쪽 폭 모두에서** 어절 중간에 끊긴다(실측 1280: `접근할 수 없`/`어요.` · 390:
              `비공개`/`로 전환되고`, `작성 중`/`인 초안은`, `접근`/`할 수 없어요`). 하필 대화기록 삭제를
              알리는 유일한 문장이다. */}
          <AlertDialogDescription className="break-keep">
            탈퇴하면 발행한 캐릭터·스토리는 비공개로 전환되고, 대화기록은 삭제돼요. 작성 중인 초안은
            보존되지만 탈퇴 후에는 접근할 수 없어요. 이 작업은 되돌릴 수 없어요.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>취소</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={withdrawMutation.isPending}
            onClick={handleConfirm}
          >
            {withdrawMutation.isPending ? "탈퇴 처리 중..." : "탈퇴하기"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
