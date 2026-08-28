import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { useRequestPasswordResetMutation } from "../api/mutations";
import {
  forgotPasswordDefaultValues,
  forgotPasswordSchema,
  type ForgotPasswordFormValues,
} from "../model/schema";

export function ForgotPasswordForm() {
  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors },
  } = useForm<ForgotPasswordFormValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: forgotPasswordDefaultValues,
  });
  const [isRequested, setIsRequested] = useState(false);
  const requestMutation = useRequestPasswordResetMutation();

  async function onSubmit(values: ForgotPasswordFormValues) {
    try {
      await requestMutation.mutateAsync(values);
      setIsRequested(true);
    } catch {
      toast.error("일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.");
    }
  }

  if (isRequested) {
    return (
      <p className="text-sm text-foreground">
        <span className="font-medium">{getValues("email")}</span>(으)로 비밀번호 재설정 링크를
        보냈어요. 메일함을 확인해주세요.
      </p>
    );
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
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="forgot-password-email">이메일</Label>
        <Input
          id="forgot-password-email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? "forgot-password-email-error" : undefined}
          {...register("email")}
        />
        {errors.email && (
          <p id="forgot-password-email-error" role="alert" className="text-xs text-destructive-text">
            {errors.email.message}
          </p>
        )}
      </div>

      <Button type="submit" size="lg" className="h-10" disabled={requestMutation.isPending}>
        {requestMutation.isPending ? "전송 중..." : "재설정 링크 받기"}
      </Button>
    </form>
  );
}
