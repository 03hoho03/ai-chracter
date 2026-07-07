import { useState } from "react";
import type { ApiError } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { useForm } from "react-hook-form";

import { useConfirmPasswordResetMutation } from "../api/mutations";
import {
  resetPasswordDefaultValues,
  resetPasswordSchema,
  type ResetPasswordFormValues,
} from "../model/schema";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

interface ResetPasswordFormProps {
  token: string;
}

export function ResetPasswordForm({ token }: ResetPasswordFormProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ResetPasswordFormValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: resetPasswordDefaultValues,
  });
  const [formError, setFormError] = useState<string | null>(null);

  const navigate = useNavigate();
  const confirmMutation = useConfirmPasswordResetMutation();

  async function onSubmit(values: ResetPasswordFormValues) {
    setFormError(null);
    try {
      await confirmMutation.mutateAsync({ token, newPassword: values.newPassword });
      await navigate({ to: "/login" });
    } catch (error) {
      const apiError = error as ApiError;
      if (apiError.status === 400) {
        setFormError("링크가 만료되었거나 유효하지 않아요. 재설정을 다시 요청해주세요.");
      } else {
        setFormError(GENERIC_ERROR_MESSAGE);
      }
    }
  }

  return (
    <form
      className="flex flex-col gap-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(onSubmit)(event);
      }}
    >
      {formError && (
        <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
          {formError}
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="reset-password-new">새 비밀번호</Label>
        <Input
          id="reset-password-new"
          type="password"
          autoComplete="new-password"
          placeholder="8자 이상 입력해주세요"
          aria-invalid={!!errors.newPassword}
          aria-describedby={errors.newPassword ? "reset-password-new-error" : undefined}
          {...register("newPassword")}
        />
        {errors.newPassword && (
          <p id="reset-password-new-error" role="alert" className="text-xs text-destructive">
            {errors.newPassword.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="reset-password-confirm">새 비밀번호 확인</Label>
        <Input
          id="reset-password-confirm"
          type="password"
          autoComplete="new-password"
          placeholder="다시 한 번 입력해주세요"
          aria-invalid={!!errors.confirmPassword}
          aria-describedby={errors.confirmPassword ? "reset-password-confirm-error" : undefined}
          {...register("confirmPassword")}
        />
        {errors.confirmPassword && (
          <p id="reset-password-confirm-error" role="alert" className="text-xs text-destructive">
            {errors.confirmPassword.message}
          </p>
        )}
      </div>

      <Button type="submit" size="lg" className="h-10" disabled={confirmMutation.isPending}>
        {confirmMutation.isPending ? "변경 중..." : "비밀번호 변경"}
      </Button>
    </form>
  );
}
