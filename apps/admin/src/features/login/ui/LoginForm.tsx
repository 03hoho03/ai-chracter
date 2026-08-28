import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useForm } from "react-hook-form";

import { sessionKeys } from "@/entities/session";
import { useLoginMutation } from "../api/mutations";
import { loginDefaultValues, loginSchema, type LoginFormValues } from "../model/schema";
import { isApiError } from "@/shared/lib/api/client";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

type LoginFormProps = {
  redirectTo?: string;
}

export function LoginForm({ redirectTo }: LoginFormProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: loginDefaultValues,
  });
  const [formError, setFormError] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const loginMutation = useLoginMutation();

  async function onSubmit(values: LoginFormValues) {
    setFormError(null);
    try {
      await loginMutation.mutateAsync(values);
      await queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
      await navigate({ to: redirectTo || "/" });
    } catch (error) {
      const apiError = isApiError(error) ? error : null;
      if (apiError?.status === 401) {
        setFormError("이메일 또는 비밀번호가 올바르지 않습니다.");
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
        <Label htmlFor="admin-login-email">이메일</Label>
        <Input
          id="admin-login-email"
          type="email"
          autoComplete="email"
          placeholder="admin@example.com"
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? "admin-login-email-error" : undefined}
          {...register("email")}
        />
        {errors.email && (
          <p id="admin-login-email-error" role="alert" className="text-xs text-destructive-text">
            {errors.email.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="admin-login-password">비밀번호</Label>
        <Input
          id="admin-login-password"
          type="password"
          autoComplete="current-password"
          placeholder="비밀번호를 입력해주세요"
          aria-invalid={!!errors.password}
          aria-describedby={errors.password ? "admin-login-password-error" : undefined}
          {...register("password")}
        />
        {errors.password && (
          <p id="admin-login-password-error" role="alert" className="text-xs text-destructive-text">
            {errors.password.message}
          </p>
        )}
      </div>

      <Button type="submit" size="lg" className="h-10" disabled={loginMutation.isPending}>
        {loginMutation.isPending ? "로그인 중..." : "로그인"}
      </Button>
    </form>
  );
}
