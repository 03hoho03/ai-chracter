import { useState } from "react";
import type { ApiError } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { EyeIcon, EyeOffIcon } from "lucide-react";
import { useForm } from "react-hook-form";

import { sessionKeys } from "@/entities/session";
import { useLoginMutation } from "../api/mutations";
import { buildGoogleLoginUrl } from "../lib/googleLoginUrl";
import { loginDefaultValues, loginSchema, type LoginFormValues } from "../model/schema";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

/** 구글 콜백이 `?error=` 로 되돌려 보낸 코드 → 사용자용 문구. */
const GOOGLE_ERROR_MESSAGES: Record<string, string> = {
  google_state: "구글 로그인 요청이 만료되었어요. 다시 시도해주세요.",
};

type LoginFormProps = {
  redirectTo?: string;
  errorCode?: string;
}

export function LoginForm({ redirectTo, errorCode }: LoginFormProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: loginDefaultValues,
  });
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);
  const [formError, setFormError] = useState<string | null>(
    errorCode ? (GOOGLE_ERROR_MESSAGES[errorCode] ?? GENERIC_ERROR_MESSAGE) : null,
  );

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
      const apiError = error as ApiError;
      if (apiError.status === 401) {
        setFormError("이메일 또는 비밀번호가 올바르지 않습니다.");
      } else if (apiError.status === 403) {
        setFormError("이메일 인증이 완료되지 않았거나 법정대리인 동의가 필요한 계정이에요.");
      } else {
        setFormError(GENERIC_ERROR_MESSAGE);
      }
    }
  }

  return (
    <div className="flex flex-col gap-5">
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
          <Label htmlFor="login-email">이메일</Label>
          <Input
            id="login-email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? "login-email-error" : undefined}
            {...register("email")}
          />
          {errors.email && (
            <p id="login-email-error" role="alert" className="text-xs text-destructive-text">
              {errors.email.message}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="login-password">비밀번호</Label>
          <div className="relative">
            <Input
              id="login-password"
              type={isPasswordVisible ? "text" : "password"}
              autoComplete="current-password"
              placeholder="비밀번호를 입력해주세요"
              className="pr-10"
              aria-invalid={!!errors.password}
              aria-describedby={errors.password ? "login-password-error" : undefined}
              {...register("password")}
            />
            <button
              type="button"
              onClick={() => setIsPasswordVisible((prev) => !prev)}
              className="absolute -inset-y-1 right-0 flex w-10 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              aria-label={isPasswordVisible ? "비밀번호 숨기기" : "비밀번호 표시"}
            >
              {isPasswordVisible ? (
                <EyeOffIcon className="size-4" aria-hidden />
              ) : (
                <EyeIcon className="size-4" aria-hidden />
              )}
            </button>
          </div>
          {errors.password && (
            <p id="login-password-error" role="alert" className="text-xs text-destructive-text">
              {errors.password.message}
            </p>
          )}
        </div>

        <div className="flex justify-end text-sm">
          <Link to="/forgot-password" className="text-muted-foreground hover:text-foreground">
            비밀번호를 잊으셨나요?
          </Link>
        </div>

        <Button type="submit" size="lg" className="h-10" disabled={loginMutation.isPending}>
          {loginMutation.isPending ? "로그인 중..." : "로그인"}
        </Button>
      </form>

      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <div className="h-px flex-1 bg-border" />
        또는
        <div className="h-px flex-1 bg-border" />
      </div>

      <Button
        type="button"
        variant="outline"
        size="lg"
        className="h-10"
        onClick={() => {
          window.location.href = buildGoogleLoginUrl(redirectTo);
        }}
      >
        구글로 로그인
      </Button>

      <p className="text-center text-sm text-muted-foreground">
        아직 계정이 없으신가요?{" "}
        <Link to="/signup" className="font-medium text-primary hover:underline">
          회원가입
        </Link>
      </p>
    </div>
  );
}
