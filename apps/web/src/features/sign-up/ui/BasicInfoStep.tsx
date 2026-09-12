import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { EyeIcon, EyeOffIcon } from "lucide-react";
import { useFormContext } from "react-hook-form";

import type { SignUpFormValues } from "../model/signUpSchema";
import { LegalConsentFields } from "./LegalConsentFields";

const BASIC_INFO_FIELDS = [
  "email",
  "password",
  "nickname",
  "birthDate",
  "termsAgreed",
  "privacyAgreed",
] as const;

type BasicInfoStepProps = {
  onSubmit: () => void;
  isSubmitting: boolean;
}

export function BasicInfoStep({ onSubmit, isSubmitting }: BasicInfoStepProps) {
  const form = useFormContext<SignUpFormValues>();

  const {
    register,
    trigger,
    formState: { errors },
  } = form;
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);

  async function handleSubmit() {
    const isValid = await trigger(BASIC_INFO_FIELDS);
    if (isValid) onSubmit();
  }

  return (
    <form
      className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-right-2 flex flex-col gap-5 motion-safe:duration-200"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit();
      }}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="signup-email">이메일</Label>
        <Input
          id="signup-email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? "signup-email-error" : undefined}
          {...register("email")}
        />
        {errors.email && (
          <p id="signup-email-error" role="alert" className="text-xs text-destructive-text">
            {errors.email.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="signup-password">비밀번호</Label>
        <div className="relative">
          <Input
            id="signup-password"
            type={isPasswordVisible ? "text" : "password"}
            autoComplete="new-password"
            placeholder="8자 이상 입력해주세요"
            className="pr-9"
            aria-invalid={!!errors.password}
            aria-describedby={errors.password ? "signup-password-error" : undefined}
            {...register("password")}
          />
          <button
            type="button"
            onClick={() => setIsPasswordVisible((prev) => !prev)}
            className="absolute inset-y-0 right-0 flex w-9 items-center justify-center rounded-md text-muted-foreground motion-safe:transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
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
          <p id="signup-password-error" role="alert" className="text-xs text-destructive-text">
            {errors.password.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="signup-nickname">닉네임</Label>
        <Input
          id="signup-nickname"
          placeholder="다른 사용자에게 보여질 이름"
          aria-invalid={!!errors.nickname}
          aria-describedby={errors.nickname ? "signup-nickname-error" : undefined}
          {...register("nickname")}
        />
        {errors.nickname && (
          <p id="signup-nickname-error" role="alert" className="text-xs text-destructive-text">
            {errors.nickname.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="signup-birth-date">생년월일</Label>
        <Input
          id="signup-birth-date"
          type="date"
          max={new Date().toISOString().slice(0, 10)}
          aria-invalid={!!errors.birthDate}
          aria-describedby={errors.birthDate ? "signup-birth-date-error" : undefined}
          {...register("birthDate")}
        />
        {errors.birthDate && (
          <p id="signup-birth-date-error" role="alert" className="text-xs text-destructive-text">
            {errors.birthDate.message}
          </p>
        )}
      </div>

      <LegalConsentFields />

      <Button type="submit" size="lg" disabled={isSubmitting}>
        {isSubmitting ? "처리 중..." : "다음"}
      </Button>
    </form>
  );
}
