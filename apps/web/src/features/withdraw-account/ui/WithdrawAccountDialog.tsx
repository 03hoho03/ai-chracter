import { useState } from "react";
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
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";

import { sessionKeys, useSessionQuery } from "@/entities/session";
import { CONTACT_EMAIL } from "@/shared/config/site";

import { useWithdrawAccountMutation } from "../api/useWithdrawAccountMutation";
import { getPaidBalanceWarning, type PaidBalanceWarning } from "../model/paidBalanceWarning";
import { WITHDRAW_GENERIC_ERROR_MESSAGE } from "../model/withdrawError";
import { WithdrawPasswordForm } from "./WithdrawPasswordForm";

type WithdrawAccountDialogProps = {
  /** ReconsentModal 안에서는 "동의하지 않고 탈퇴"가 맞는
   * 문구라 트리거 라벨만 바꿀 수 있게 열어둔다. 기본값은 `/mypage` 호출부를 그대로 유지한다. */
  label?: string;
};

/** 부수효과(발행작 비공개 전환, 대화기록 삭제, 초안 보존)는 전부 BE 책임이며 FE는 단일 mutation만 호출한다.
 *
 * 비밀번호가 있는 계정은 서버가 현재 비밀번호를 다시 확인하므로 칸을 함께 보인다. 소셜 계정은 확인할 비밀번호가
 * 없어 예전 확인 버튼 그대로다. 열림을 이 컴포넌트가 쥐는 이유는 비밀번호 칸 쪽이 실패하면 다이얼로그를 열어 둔 채
 * 오류를 보여야 해서다. */
export function WithdrawAccountDialog({ label = "회원탈퇴" }: WithdrawAccountDialogProps) {
  const navigate = useNavigate();
  const { data: me } = useSessionQuery();
  const withdrawMutation = useWithdrawAccountMutation();
  const [isOpen, setIsOpen] = useState(false);
  const queryClient = useQueryClient();
  // 유료 잔액은 세션 값이다(재동의 게이트 밖이라 재동의 모달 안에서도 읽힌다). 기준은 `getPaidBalanceWarning`.
  const paidBalanceWarning = getPaidBalanceWarning(me);

  const handleOpenChange = (open: boolean) => {
    // 세션은 `staleTime: Infinity` 라, 그사이 환불·구매로 바뀐 유료 잔액을 열 때 다시 읽는다.
    if (open) void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
    setIsOpen(open);
  };

  const handleWithdrawn = () => {
    setIsOpen(false);
    toast.success("탈퇴가 완료되었어요.");
    void navigate({ to: "/" });
  };

  const handleConfirm = () => {
    if (withdrawMutation.isPending) return;
    withdrawMutation.mutate(undefined, {
      onSuccess: handleWithdrawn,
      onError: () => {
        toast.error(WITHDRAW_GENERIC_ERROR_MESSAGE);
      },
    });
  };

  return (
    <AlertDialog open={isOpen} onOpenChange={handleOpenChange}>
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
            탈퇴하면 발행한 캐릭터·스토리는 비공개로 전환되고, 대화기록과 만든 소설은 삭제돼요. 작성 중인 초안은
            보존되지만 탈퇴 후에는 접근할 수 없어요. 이 작업은 되돌릴 수 없어요.
          </AlertDialogDescription>
          <PaidBalanceWarningMessage warning={paidBalanceWarning} />
        </AlertDialogHeader>
        {me?.hasPassword ? (
          <WithdrawPasswordForm onWithdrawn={handleWithdrawn} />
        ) : (
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
        )}
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** 남은 유료 클로버 경고. 수를 알면 수로, 모르면(세션을 못 읽었다) 숫자 없이 같은 행동을 안내한다.
 *
 * 환불 신청 창구는 문의 화면이 아니라 이메일이다. 이 다이얼로그는 재동의 모달 안에서도 열리는데, 그 모달은 닫을 수
 * 없고 앱 위에 남아 있어 문의 화면으로 이동해도 그 화면을 가린다. 메일 주소는 모달과
 * 무관하게 쓸 수 있고 환불정책이 정한 신청 창구이기도 하다. 주소를 글자로 보여 메일 앱이 없어도 옮겨 적을 수 있다. */
function PaidBalanceWarningMessage({ warning }: { warning: PaidBalanceWarning }) {
  if (warning.kind === "none") return null;
  const lead =
    warning.kind === "count"
      ? `남은 유료 클로버 ${warning.paidBalance.toLocaleString()}개도 함께 사라져요.`
      : "남은 유료 클로버가 있다면 함께 사라져요.";
  return (
    <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
      {lead} 환불은 탈퇴하기 전에{" "}
      <a
        href={`mailto:${CONTACT_EMAIL}`}
        // 쉬는 상태에 이미 밑줄이 있어 포커스는 밑줄이 아니라 불투명 아웃라인으로 준다.
        className="font-medium whitespace-nowrap underline underline-offset-4 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring"
      >
        {CONTACT_EMAIL}
      </a>
      로 신청해 주세요.
    </p>
  );
}
