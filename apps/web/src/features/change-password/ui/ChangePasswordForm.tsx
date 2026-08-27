import { useState } from "react";
import type { ApiError } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { useChangePasswordMutation } from "../api/mutations";
import {
  changePasswordDefaultValues,
  changePasswordSchema,
  type ChangePasswordFormValues,
} from "../model/schema";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

export function ChangePasswordForm() {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ChangePasswordFormValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: changePasswordDefaultValues,
  });
  const [formError, setFormError] = useState<string | null>(null);

  const changePasswordMutation = useChangePasswordMutation();

  async function onSubmit(values: ChangePasswordFormValues) {
    setFormError(null);
    try {
      await changePasswordMutation.mutateAsync(values);
      toast.success("비밀번호가 변경되었어요.");
      reset(changePasswordDefaultValues);
    } catch (error) {
      const apiError = error as ApiError;
      if (apiError.status === 400) {
        setFormError("현재 비밀번호가 올바르지 않아요.");
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
        <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive-text">
          {formError}
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="change-password-current">현재 비밀번호</Label>
        <Input
          id="change-password-current"
          type="password"
          autoComplete="current-password"
          aria-invalid={!!errors.currentPassword}
          aria-describedby={errors.currentPassword ? "change-password-current-error" : undefined}
          {...register("currentPassword")}
        />
        {errors.currentPassword && (
          <p id="change-password-current-error" role="alert" className="text-xs text-destructive-text">
            {errors.currentPassword.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="change-password-new">새 비밀번호</Label>
        <Input
          id="change-password-new"
          type="password"
          autoComplete="new-password"
          placeholder="8자 이상 입력해주세요"
          aria-invalid={!!errors.newPassword}
          aria-describedby={errors.newPassword ? "change-password-new-error" : undefined}
          {...register("newPassword")}
        />
        {errors.newPassword && (
          <p id="change-password-new-error" role="alert" className="text-xs text-destructive-text">
            {errors.newPassword.message}
          </p>
        )}
      </div>

      <Button type="submit" className="h-10 self-start" disabled={changePasswordMutation.isPending}>
        {changePasswordMutation.isPending ? "변경 중..." : "비밀번호 변경"}
      </Button>
    </form>
  );
}
