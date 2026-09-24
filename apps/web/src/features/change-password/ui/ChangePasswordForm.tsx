import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useRouterState } from "@tanstack/react-router";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { getAuthFormErrorBanner, LOGIN_LINK_ERROR_TYPE } from "@/entities/session";

import { useChangePasswordMutation } from "../api/useChangePasswordMutation";
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
    setError,
    clearErrors,
    formState: { errors },
  } = useForm<ChangePasswordFormValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: changePasswordDefaultValues,
  });

  const changePasswordMutation = useChangePasswordMutation();
  // 다시 로그인한 뒤 이 화면으로 돌아오게 한다(`requireSession`이 `redirect`에 현재 href를 싣는 것과 같다).
  const currentHref = useRouterState({ select: (state) => state.location.href });

  async function handleValidSubmit(values: ChangePasswordFormValues) {
    clearErrors("root");
    try {
      await changePasswordMutation.mutateAsync(values);
      toast.success("비밀번호가 변경되었어요.");
      reset(changePasswordDefaultValues);
    } catch (error) {
      // 401(세션 소멸)은 자동으로 로그인 화면에 보내지 않는다 — 입력 중이던 값을 잃지 않게 링크만 준다(BS-9).
      const banner = getAuthFormErrorBanner(error, "change-password");
      setError("root", {
        type: banner?.showsLoginLink ? LOGIN_LINK_ERROR_TYPE : "server",
        message: banner?.message ?? GENERIC_ERROR_MESSAGE,
      });
    }
  }

  return (
    <form
      className="flex flex-col gap-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(handleValidSubmit)(event);
      }}
    >
      {errors.root && (
        <div role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
          <p>{errors.root.message}</p>
          {/* 링크 모양의 근거는 `GoogleBasicInfoStep`의 같은 배너 주석. */}
          {errors.root.type === LOGIN_LINK_ERROR_TYPE && (
            <Link
              to="/login"
              search={{ redirect: currentHref }}
              className="mt-2 inline-block rounded-sm font-medium underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              다시 로그인하기
            </Link>
          )}
        </div>
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

      <Button type="submit" size="lg" className="self-start" disabled={changePasswordMutation.isPending}>
        {changePasswordMutation.isPending ? "변경 중..." : "비밀번호 변경"}
      </Button>
    </form>
  );
}
