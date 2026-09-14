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

import { useWithdrawAccountMutation } from "../api/useWithdrawAccountMutation";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

type WithdrawAccountDialogProps = {
  /** consent-gate-goal-prompt.md CG-11 — ReconsentModal 안에서는 "동의하지 않고 탈퇴"가 맞는
   * 문구라 트리거 라벨만 바꿀 수 있게 열어둔다. 기본값은 `/mypage` 호출부를 그대로 유지한다. */
  label?: string;
};

/** techspec-global-nav-profile.md §2 — 부수효과(발행작 비공개 전환, 대화기록 삭제, 초안 보존)는 전부 BE 책임이며 FE는 단일 mutation만 호출한다. */
export function WithdrawAccountDialog({ label = "회원탈퇴" }: WithdrawAccountDialogProps) {
  const navigate = useNavigate();
  const withdrawMutation = useWithdrawAccountMutation();

  const handleConfirm = () => {
    if (withdrawMutation.isPending) return;
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
        <Button variant="destructive">{label}</Button>
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
          {/* apps/web/CLAUDE.md §포커스 — 로딩 중 plain `disabled`는 브라우저가 즉시 blur해
              포커스를 <body>로 떨어뜨린다. ContentListLoadMore·ReconsentModal과 같은 처방으로
              맞춘다(`aria-disabled` + 핸들러 early return + pointer-events-none·opacity-65).
              이 버튼은 ESC를 막아 둔 ReconsentModal 안에서도 재사용되므로 키보드 복귀 수단이
              Tab 하나뿐이다. */}
          <AlertDialogAction
            variant="destructive"
            aria-disabled={withdrawMutation.isPending}
            className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
            onClick={handleConfirm}
          >
            {withdrawMutation.isPending ? "탈퇴 처리 중..." : "탈퇴하기"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
