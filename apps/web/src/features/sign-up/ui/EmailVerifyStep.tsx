import { useEffect, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { useFormContext } from "react-hook-form";
import { toast } from "sonner";

import { formatAuthRateLimitMessage, getAuthRateLimit } from "@/entities/session";

import { useResendVerificationCodeMutation } from "../api/mutations";
import { toResendVerificationCodeRequest } from "../model/formToServer";
import type { SignUpFormValues } from "../model/signUpSchema";

const RESEND_COOLDOWN_SECONDS = 60;

type EmailVerifyStepProps = {
  onSubmit: () => void;
  isSubmitting: boolean;
}

export function EmailVerifyStep({ onSubmit, isSubmitting }: EmailVerifyStepProps) {
  const form = useFormContext<SignUpFormValues>();

  const {
    register,
    trigger,
    formState: { errors },
  } = form;
  const email = form.getValues("email");
  const [secondsLeft, setSecondsLeft] = useState(RESEND_COOLDOWN_SECONDS);
  // AUTH_LIMIT(시간당 상한, ≤3600초)은 초 카운트다운에 꽂지 않는다 — 별도 줄의 분 단위 정적 문구로만
  // 보여준다. AUTH_COOLDOWN(60초 쿨다운)은 그대로 `secondsLeft`가 카운트다운한다.
  const [limitMessage, setLimitMessage] = useState<string | null>(null);
  const resendMutation = useResendVerificationCodeMutation();

  useEffect(() => {
    const timer = setInterval(() => {
      setSecondsLeft((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  async function handleVerify() {
    const isValid = await trigger("emailVerificationCode");
    if (isValid) onSubmit();
  }

  async function handleResend() {
    try {
      await resendMutation.mutateAsync(toResendVerificationCodeRequest(email));
      setSecondsLeft(RESEND_COOLDOWN_SECONDS);
      setLimitMessage(null);
      toast.success("인증코드를 다시 보냈어요");
    } catch (error) {
      const detail = getAuthRateLimit(error);
      if (detail === undefined) {
        toast.error("인증코드 재전송에 실패했어요. 잠시 후 다시 시도해주세요.");
        return;
      }
      switch (detail.code) {
        case "AUTH_COOLDOWN":
          setSecondsLeft(detail.retryAfterSeconds);
          setLimitMessage(null);
          break;
        case "AUTH_LIMIT":
          setLimitMessage(formatAuthRateLimitMessage(detail, "resend"));
          break;
      }
    }
  }

  return (
    <form
      className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-right-2 flex flex-col gap-5 motion-safe:duration-200"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleVerify();
      }}
    >
      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">{email}</span>로 보낸 6자리 인증코드를
        입력해주세요.
      </p>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="signup-verification-code">인증코드</Label>
        <Input
          id="signup-verification-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          placeholder="123456"
          className="text-center text-lg tracking-[0.5em]"
          aria-invalid={!!errors.emailVerificationCode}
          aria-describedby={
            errors.emailVerificationCode ? "signup-verification-code-error" : undefined
          }
          {...register("emailVerificationCode")}
        />
        {errors.emailVerificationCode && (
          <p
            id="signup-verification-code-error"
            role="alert"
            className="text-xs text-destructive-text"
          >
            {errors.emailVerificationCode.message}
          </p>
        )}
      </div>

      <div className="flex items-center justify-between text-sm">
        {/* 이 폼이 400을 받은 적 있으면(서버가 `type: "server"`로 지은 에러) 재전송을 권한다. */}
        <span className="text-muted-foreground">
          {errors.emailVerificationCode?.type === "server"
            ? "코드가 계속 안 되면 새로 받아주세요."
            : "코드를 받지 못하셨나요?"}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => void handleResend()}
          disabled={secondsLeft > 0 || resendMutation.isPending}
        >
          {secondsLeft > 0 ? `재전송 (${secondsLeft}초)` : "인증코드 재전송"}
        </Button>
      </div>

      {limitMessage && (
        <p role="alert" className="text-xs text-destructive-text">
          {limitMessage}
        </p>
      )}

      <Button type="submit" size="lg" disabled={isSubmitting}>
        {isSubmitting ? "확인 중..." : "인증하기"}
      </Button>
    </form>
  );
}
