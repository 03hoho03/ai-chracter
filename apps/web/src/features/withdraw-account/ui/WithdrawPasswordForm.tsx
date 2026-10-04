import { AlertDialogCancel, AlertDialogFooter } from "@ai-character-chat/ui/components/alert-dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { useWithdrawAccountMutation } from "../api/useWithdrawAccountMutation";
import {
  withdrawPasswordDefaultValues,
  withdrawPasswordSchema,
  type WithdrawPasswordFormValues,
} from "../model/schema";
import { getWithdrawError } from "../model/withdrawError";

type WithdrawPasswordFormProps = {
  onWithdrawn: () => void;
};

/** 비밀번호 계정의 탈퇴 확인 칸과 버튼. 실행 버튼이 `AlertDialogAction` 이 아닌 이유: 그 버튼은 누르는 즉시
 * 다이얼로그를 닫아, 비밀번호가 틀려도 칸 아래 오류를 보일 자리가 사라진다. 여기서는 제출 버튼이라 닫힘은
 * 성공했을 때 `onWithdrawn` 쪽이 정한다. 다이얼로그 콘텐츠 안에서 렌더돼 닫히면 함께 언마운트되므로, 다시 열면
 * 입력값과 오류가 비어 있다. */
export function WithdrawPasswordForm({ onWithdrawn }: WithdrawPasswordFormProps) {
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<WithdrawPasswordFormValues>({
    resolver: zodResolver(withdrawPasswordSchema),
    defaultValues: withdrawPasswordDefaultValues,
  });
  const withdrawMutation = useWithdrawAccountMutation();

  async function handleValidSubmit(values: WithdrawPasswordFormValues) {
    // 버튼은 `aria-disabled` 라 Enter 제출을 막지 못한다 — 진행 중 재제출은 여기서 끊는다.
    if (withdrawMutation.isPending) return;
    try {
      await withdrawMutation.mutateAsync(values);
      onWithdrawn();
    } catch (error) {
      const failure = getWithdrawError(error);
      if (failure.target === "field") {
        setError("currentPassword", { type: "server", message: failure.message }, { shouldFocus: true });
      } else {
        toast.error(failure.message);
      }
    }
  }

  return (
    <form
      className="flex flex-col gap-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(handleValidSubmit)(event);
      }}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="withdraw-current-password">현재 비밀번호</Label>
        <Input
          id="withdraw-current-password"
          type="password"
          autoComplete="current-password"
          aria-invalid={!!errors.currentPassword}
          aria-describedby={errors.currentPassword ? "withdraw-current-password-error" : undefined}
          {...register("currentPassword")}
        />
        {errors.currentPassword && (
          <p id="withdraw-current-password-error" role="alert" className="text-xs text-destructive-text">
            {errors.currentPassword.message}
          </p>
        )}
      </div>
      <AlertDialogFooter>
        <AlertDialogCancel>취소</AlertDialogCancel>
        {/* 로딩 중 plain `disabled` 를 쓰지 않는 이유는 `WithdrawAccountDialog` 의 실행 버튼 주석과 같다. */}
        <Button
          type="submit"
          variant="destructive"
          aria-disabled={withdrawMutation.isPending}
          className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
        >
          {withdrawMutation.isPending ? "탈퇴 처리 중..." : "탈퇴하기"}
        </Button>
      </AlertDialogFooter>
    </form>
  );
}
