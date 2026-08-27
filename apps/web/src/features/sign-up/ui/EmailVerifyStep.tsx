import { useEffect, useState } from "react";
import type { ApiError } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import type { UseFormReturn } from "react-hook-form";
import { toast } from "sonner";

import type { SignUpFormValues } from "../../../entities/registration";
import { useResendVerificationCodeMutation } from "../api/mutations";

const RESEND_COOLDOWN_SECONDS = 60;

interface EmailVerifyStepProps {
  form: UseFormReturn<SignUpFormValues>;
  onSubmit: () => void;
  isSubmitting: boolean;
}

export function EmailVerifyStep({ form, onSubmit, isSubmitting }: EmailVerifyStepProps) {
  const {
    register,
    trigger,
    formState: { errors },
  } = form;
  const email = form.getValues("email");
  const [secondsLeft, setSecondsLeft] = useState(RESEND_COOLDOWN_SECONDS);
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
      await resendMutation.mutateAsync({ email });
      setSecondsLeft(RESEND_COOLDOWN_SECONDS);
      toast.success("인증코드를 다시 보냈어요");
    } catch (error) {
      const apiError = error as ApiError;
      const retryAfterSeconds =
        apiError.status === 429 && apiError.detail && typeof apiError.detail === "object"
          ? apiError.detail.retryAfterSeconds
          : undefined;
      if (typeof retryAfterSeconds === "number") {
        setSecondsLeft(retryAfterSeconds);
      } else {
        toast.error("인증코드 재전송에 실패했어요. 잠시 후 다시 시도해주세요.");
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
        <span className="text-muted-foreground">코드를 받지 못하셨나요?</span>
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

      <Button type="submit" size="lg" className="h-10" disabled={isSubmitting}>
        {isSubmitting ? "확인 중..." : "인증하기"}
      </Button>
    </form>
  );
}
